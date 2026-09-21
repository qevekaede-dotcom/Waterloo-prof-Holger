"""Small regression tests for the inventory's no-production readiness claim."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_inventory  # noqa: E402


class ReuseReadinessTests(unittest.TestCase):
    def test_all_candidate_filenames_present_still_does_not_verify_fc_identity(self) -> None:
        sources = [{"matches_recorded_sha256": True}]
        all_present = [
            {"artifact": "fc2.hdf5", "local_present": True},
            {"artifact": "fc3.hdf5", "local_present": True},
        ]
        self.assertFalse(build_inventory.qmesh_reuse_ready_now(sources, all_present, True))

    def test_non_au_yaml_unit_is_rejected_before_amplitude_conversion(self) -> None:
        source = (Path(__file__).parent / "../../../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/preflight/phono3py_disp.yaml").resolve()
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "wrong_unit.yaml"
            fixture.write_text(source.read_text().replace('length: "au"', 'length: "angstrom"', 1))
            with self.assertRaises(ValueError):
                build_inventory.yaml_supercell_and_amplitude(fixture)


if __name__ == "__main__":
    unittest.main()
