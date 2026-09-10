from __future__ import annotations

import unittest

from qe_input import (
    AtomicPosition,
    FinalCoordinates,
    QEInputError,
    build_fixed_cell_relax_input,
    build_pristine_scf_input,
    extract_final_coordinates,
    parse_qe_input,
    replace_geometry_from_final_coordinates,
    replace_qe_geometry,
)


SOURCE_INPUT = """&CONTROL
  calculation = 'scf',
  disk_io = 'medium',
  outdir = './tmp/final',
  prefix = 'Example',
  pseudo_dir = '/old/pseudo',
/
&SYSTEM
  ecutrho = 400,
  ecutwfc = 50,
  occupations = 'fixed',
  ibrav = 0,
  nat = 3,
  ntyp = 2,
/
&ELECTRONS
  conv_thr = 1d-08,
/
&IONS
/
&CELL
/
ATOMIC_SPECIES
  A  10.0 A.upf
  B  20.0 B.upf
ATOMIC_POSITIONS crystal
  A 0.000000 0.000000 0.000000 0 0 0
  B 0.250000 0.250000 0.250000
  B 0.750000 0.750000 0.750000
K_POINTS automatic
  4 4 4 0 0 0
CELL_PARAMETERS angstrom
  5.100000 0.000000 0.000000
  0.000000 5.200000 0.000000
  0.000000 0.000000 5.300000
"""


def final_block(
    first_coordinate: str = "0.000000000000",
    *,
    first_label: str = "A",
    cell_a: str = "5.100000000",
) -> str:
    return f"""Begin final coordinates
CELL_PARAMETERS (angstrom)
  {cell_a} 0.000000000 0.000000000
  0.000000000 5.200000000 0.000000000
  0.000000000 0.000000000 5.300000000

ATOMIC_POSITIONS (crystal)
{first_label} {first_coordinate} 0.000000000123 0.000000000456
B 0.249999999876 0.250000000111 0.250000000222
B 0.750000000333 0.749999999777 0.750000000444
End final coordinates
"""


class ParseQEInputTests(unittest.TestCase):
    def test_parses_required_cards_and_counts(self) -> None:
        parsed = parse_qe_input(SOURCE_INPUT)
        self.assertEqual((parsed.nat, parsed.ntyp, parsed.ibrav), (3, 2, 0))
        self.assertEqual(parsed.ecutwfc_ry, 50.0)
        self.assertEqual(parsed.ecutrho_ry, 400.0)
        self.assertEqual(
            [(item.label, item.pseudopotential) for item in parsed.atomic_species],
            [("A", "A.upf"), ("B", "B.upf")],
        )
        self.assertEqual(parsed.position_unit, "crystal")
        self.assertEqual(parsed.atomic_positions[0].constraints, (0, 0, 0))
        self.assertEqual(parsed.k_points.grid, (4, 4, 4))
        self.assertEqual(parsed.k_points.shift, (0, 0, 0))
        self.assertEqual(parsed.cell_parameters[2], (0.0, 0.0, 5.3))

    def test_rejects_missing_or_duplicate_structural_records(self) -> None:
        with self.assertRaisesRegex(QEInputError, "ATOMIC_SPECIES card"):
            parse_qe_input(SOURCE_INPUT.replace("ATOMIC_SPECIES", "SPECIES", 1))
        duplicate_nat = SOURCE_INPUT.replace("  nat = 3,", "  nat = 3,\n  nat = 3,")
        with self.assertRaisesRegex(QEInputError, "exactly one nat"):
            parse_qe_input(duplicate_nat)
        duplicate_card = SOURCE_INPUT + "\nK_POINTS automatic\n  4 4 4 0 0 0\n"
        with self.assertRaisesRegex(QEInputError, "exactly one K_POINTS"):
            parse_qe_input(duplicate_card)

    def test_rejects_atom_count_and_species_ambiguity(self) -> None:
        wrong_count = SOURCE_INPUT.replace("  nat = 3,", "  nat = 2,")
        with self.assertRaisesRegex(QEInputError, "extra or ambiguous row"):
            parse_qe_input(wrong_count)
        unknown_species = SOURCE_INPUT.replace(
            "  B 0.750000 0.750000 0.750000",
            "  C 0.750000 0.750000 0.750000",
        )
        with self.assertRaisesRegex(QEInputError, "do not match"):
            parse_qe_input(unknown_species)


class PrepareInputsTests(unittest.TestCase):
    def test_builds_fixed_cell_relax_and_preserves_structure(self) -> None:
        original = parse_qe_input(SOURCE_INPUT)
        generated = build_fixed_cell_relax_input(
            SOURCE_INPUT,
            outdir="/scratch/run/relax",
            prefix="Example_relax",
            pseudo_dir="/scratch/pseudos",
            conv_thr=1e-10,
            forc_conv_thr=1e-5,
            ecutwfc=60,
            ecutrho=480,
            kmesh=(3, 3, 3),
            etot_conv_thr=1e-8,
            tstress=True,
            electron_maxstep=300,
            mixing_beta=0.25,
        )
        parsed = parse_qe_input(generated)
        self.assertEqual(parsed.cell_parameters, original.cell_parameters)
        self.assertEqual(parsed.atomic_positions, original.atomic_positions)
        self.assertEqual((parsed.ecutwfc_ry, parsed.ecutrho_ry), (60.0, 480.0))
        self.assertEqual(parsed.k_points.grid, (3, 3, 3))
        self.assertIn("calculation = 'relax'", generated)
        self.assertIn("outdir = '/scratch/run/relax'", generated)
        self.assertIn("prefix = 'Example_relax'", generated)
        self.assertIn("pseudo_dir = '/scratch/pseudos'", generated)
        self.assertIn("disk_io = 'low'", generated)
        self.assertIn("tprnfor = .true.", generated)
        self.assertIn("forc_conv_thr = 1.000000000000d-05", generated)
        self.assertIn("conv_thr = 1.000000000000d-10", generated)
        self.assertIn("etot_conv_thr = 1.000000000000d-08", generated)
        self.assertIn("tstress = .true.", generated)
        self.assertIn("electron_maxstep = 300", generated)
        self.assertIn("mixing_beta = 0.25", generated)
        self.assertIn("ion_dynamics = 'bfgs'", generated)

    def test_relax_rejects_active_cell_dynamics_and_duplicate_target(self) -> None:
        active_cell = SOURCE_INPUT.replace("&CELL\n/", "&CELL\n  cell_dynamics = 'bfgs',\n/")
        with self.assertRaisesRegex(QEInputError, "active cell_dynamics"):
            build_fixed_cell_relax_input(
                active_cell,
                outdir="out",
                prefix="x",
                pseudo_dir="pseudo",
                conv_thr=1e-10,
                forc_conv_thr=1e-5,
                ecutwfc=50,
                ecutrho=400,
                kmesh=(2, 2, 2),
            )
        duplicate_prefix = SOURCE_INPUT.replace(
            "  prefix = 'Example',", "  prefix = 'Example',\n  prefix = 'Other',"
        )
        with self.assertRaisesRegex(QEInputError, "duplicate prefix"):
            build_fixed_cell_relax_input(
                duplicate_prefix,
                outdir="out",
                prefix="x",
                pseudo_dir="pseudo",
                conv_thr=1e-10,
                forc_conv_thr=1e-5,
                ecutwfc=50,
                ecutrho=400,
                kmesh=(2, 2, 2),
            )

    def test_extracts_last_complete_final_coordinate_block(self) -> None:
        output = final_block("0.100000000001") + final_block("0.200000000002")
        final = extract_final_coordinates(output, expected_atoms=3)
        self.assertEqual(final.atomic_positions[0].coordinate_tokens[0], "0.200000000002")
        self.assertEqual(final.cell_parameters[0][0], 5.1)  # type: ignore[index]

    def test_injects_changed_high_precision_vc_relax_geometry(self) -> None:
        output = final_block("0.123456789012", cell_a="5.234567890123")
        injected = replace_geometry_from_final_coordinates(
            SOURCE_INPUT, output, expected_atoms=3, require_cell=True
        )
        parsed = parse_qe_input(injected)
        self.assertEqual(parsed.cell_parameters[0][0], 5.234567890123)
        self.assertEqual(parsed.atomic_positions[0].coordinates[0], 0.123456789012)
        self.assertIn("5.234567890123 0.000000000 0.000000000", injected)
        self.assertIn("A 0.123456789012 0.000000000123", injected)

        final = extract_final_coordinates(output, expected_atoms=3)
        self.assertEqual(replace_qe_geometry(SOURCE_INPUT, final), injected)

        relax = build_fixed_cell_relax_input(
            injected,
            outdir="out",
            prefix="tight",
            pseudo_dir="pseudo",
            conv_thr=1e-10,
            forc_conv_thr=1e-5,
            ecutwfc=50,
            ecutrho=400,
            kmesh=(2, 2, 2),
        )
        self.assertEqual(
            parse_qe_input(relax).cell_parameters,
            parsed.cell_parameters,
        )

    def test_geometry_injection_requires_cell_by_default(self) -> None:
        positions_only = """Begin final coordinates
ATOMIC_POSITIONS (crystal)
A 0.0 0.0 0.0
B 0.25 0.25 0.25
B 0.75 0.75 0.75
End final coordinates
"""
        with self.assertRaisesRegex(QEInputError, "missing CELL_PARAMETERS"):
            replace_geometry_from_final_coordinates(
                SOURCE_INPUT, positions_only, expected_atoms=3
            )
        replaced = replace_geometry_from_final_coordinates(
            SOURCE_INPUT, positions_only, expected_atoms=3, require_cell=False
        )
        self.assertEqual(
            parse_qe_input(replaced).cell_parameters,
            parse_qe_input(SOURCE_INPUT).cell_parameters,
        )

    def test_injects_programmatically_standardized_geometry(self) -> None:
        standardized = FinalCoordinates(
            "crystal",
            (
                AtomicPosition("A", (0.0, 0.0, 0.0)),
                AtomicPosition("B", (0.2, 0.3, 0.4)),
                AtomicPosition("B", (0.8, 0.7, 0.6)),
            ),
            "angstrom",
            (
                (5.0, 0.0, 0.0),
                (0.0, 5.5, 0.0),
                (0.0, 0.0, 6.0),
            ),
        )
        parsed = parse_qe_input(replace_qe_geometry(SOURCE_INPUT, standardized))
        self.assertEqual(parsed.cell_parameters[1][1], 5.5)
        self.assertEqual(parsed.atomic_positions[1].coordinates, (0.2, 0.3, 0.4))

    def test_rejects_incomplete_final_coordinate_history(self) -> None:
        with self.assertRaisesRegex(QEInputError, "trailing incomplete"):
            extract_final_coordinates(
                final_block() + "\nBegin final coordinates\nATOMIC_POSITIONS crystal\n"
            )
        with self.assertRaisesRegex(QEInputError, "no complete"):
            extract_final_coordinates("PWSCF output without final geometry")

    def test_builds_pristine_scf_with_high_precision_positions(self) -> None:
        generated = build_pristine_scf_input(
            SOURCE_INPUT,
            final_block("0.000000000987"),
            outdir="/scratch/run/pristine",
            prefix="Example_pristine",
            pseudo_dir="/scratch/pseudos",
            conv_thr=1e-10,
            ecutwfc=70,
            ecutrho=560,
            kmesh=(2, 3, 4),
            kshift=(0, 1, 0),
            nosym=True,
            noinv=True,
        )
        parsed = parse_qe_input(generated)
        self.assertEqual(parsed.cell_parameters, parse_qe_input(SOURCE_INPUT).cell_parameters)
        self.assertEqual(parsed.k_points.grid, (2, 3, 4))
        self.assertEqual(parsed.k_points.shift, (0, 1, 0))
        self.assertEqual(parsed.atomic_positions[0].constraints, (0, 0, 0))
        self.assertIn("A 0.000000000987 0.000000000123 0.000000000456 0 0 0", generated)
        self.assertIn("calculation = 'scf'", generated)
        self.assertIn("tprnfor = .true.", generated)
        self.assertIn("nosym = .true.", generated)
        self.assertIn("noinv = .true.", generated)

    def test_pristine_rejects_changed_cell_or_atom_order(self) -> None:
        with self.assertRaisesRegex(QEInputError, "CELL_PARAMETERS differs"):
            build_pristine_scf_input(
                SOURCE_INPUT,
                final_block(cell_a="5.200000000"),
                outdir="out",
                prefix="x",
                pseudo_dir="pseudo",
                conv_thr=1e-10,
                ecutwfc=50,
                ecutrho=400,
                kmesh=(2, 2, 2),
            )
        with self.assertRaisesRegex(QEInputError, "ordering/species"):
            build_pristine_scf_input(
                SOURCE_INPUT,
                final_block(first_label="B"),
                outdir="out",
                prefix="x",
                pseudo_dir="pseudo",
                conv_thr=1e-10,
                ecutwfc=50,
                ecutrho=400,
                kmesh=(2, 2, 2),
            )


if __name__ == "__main__":
    unittest.main()
