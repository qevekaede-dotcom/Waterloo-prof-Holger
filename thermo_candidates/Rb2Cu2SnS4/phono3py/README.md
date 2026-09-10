# Rb2Cu2SnS4 phono3py campaign

This directory defines the pending Rb2Cu2SnS4 finite-displacement campaign.
It does **not** contain a lattice-thermal-conductivity result yet. The machine
readable source of truth is [`campaign.json`](campaign.json); every `null`
production choice is an intentional stop gate.

Heavy QE calculations, displacement generation, force-constant construction,
and phono3py transport postprocessing belong on a DRAC compute node. This
repository checkout is for preparation, versioned configuration, transfer,
and lightweight validation.

## Starting evidence and the explicit Ibam standardization

The material is the experimentally observed `mp-18006` Ibam primitive cell.
The primary geometry is the final high-precision `Begin final coordinates`
block in
[`../logs/Rb2Cu2SnS4.relax.out`](../logs/Rb2Cu2SnS4.relax.out). The SCF input
rounds that cell and the positions; it is a QE template and cross-check, not
the authoritative starting geometry.

The completed electronic workflow selected 90/720 Ry and a 3x5x5 final SCF
mesh for its energy tests. Those tests did not establish displaced-force
accuracy. In the archived vc-relax final SCF block:

- QE reports total force `0.000908 Ry/bohr`;
- the largest Cartesian force component is `0.00026738 Ry/bohr`;
- the old geometry optimization was allowed to stop at
  `forc_conv_thr = 0.001 Ry/bohr`.

This is too loose for finite displacements. The campaign starts with a
fixed-cell ionic relaxation at planned conservative settings of 100/800 Ry,
4x7x7, `conv_thr = 1e-10 Ry`, and
`forc_conv_thr = 1e-5 Ry/bohr`. These are planned choices, not a claim that
force convergence has already been established; the supercell-force pilot is
still mandatory.

The high-precision archived geometry is only numerically close to Ibam. A
spglib scan identifies P-1 through `5e-4 angstrom`, C2/c at `1e-3` to
`2e-3 angstrom`, and Ibam at `5e-3 angstrom`. Therefore this campaign makes
one explicit scientific choice before the tight relax:

```text
spglib.standardize_cell(to_primitive=True,
                        no_idealize=False,
                        symprec=0.005 angstrom)
```

This is not a silent cleanup. The attempt must preserve both structures and
their hashes, spglib's original-input-to-primitive index map, and a separate
periodic-minimum-image atom match between the raw and idealized conventional
representations. The latter supplies per-atom displacement, origin shift,
deformation gradient, strain, and volume change; it is not represented as a
single composed original-to-final periodic-image map. The workflow stops if
any atom moves more than 0.01 angstrom, any absolute principal strain exceeds
0.001, or relative volume changes by more than 0.001. The standardized 18-atom
cell must be exact Ibam down to `1e-6 angstrom` before the tight relax and
displacement work.

## Critical QE/phono3py distance-unit rule

The phono3py QE interface uses atomic units for length: `bohr`, also written
`au`. This applies to `--amplitude`, `--cutoff-pair`, the symmetry tolerance,
and the one-value length-like generalized-grid input. The conversion fixed in
the config is

```text
1 bohr = 0.529177210903 angstrom
CLI bohr = design angstrom / 0.529177210903
```

For example, the primary 0.03-angstrom displacement candidate is passed as
`--amplitude 0.0566917837388`, and the 4.25-angstrom cutoff candidate is
passed as `--cutoff-pair 8.031336029660`. After every displacement generation,
`phono3py_disp.yaml` must contain `physical_unit: ... length: au`; otherwise
the workflow stops before force submission.

This also corrects a historical interpretation: the old SrCu2SnS4 command
`--cutoff-pair 4` meant **4 bohr = 2.116708843612 angstrom**, not 4 angstrom.
The current campaign never uses an unqualified distance. See the official
[calculator-unit table](https://phonopy.github.io/phono3py/interfaces.html)
and [QE workflow](https://phonopy.github.io/phono3py/qe.html).

## Gated workflow

1. Extract the high-precision archived geometry, perform the audited Ibam
   standardization above, and record every source/config/pseudopotential hash.
2. Run the fixed-cell tight relax. Accept only after QE completion, atom-count,
   force, position-shift, and strict post-standardization Ibam gates pass. The
   maximum accepted force component is `5e-5 Ry/bohr`; above `1e-4` is a hard
   stop.
3. On a compute node, generate count-only phono3py datasets for every declared
   matrix/cutoff candidate with explicit `--pa P`. Record the command, YAML,
   units, generated vectors, atom count, and displacement count. More than
   1000 displacement supercells is a hard stop.
4. Run positive/negative amplitude probes at 0.02, 0.03, and 0.04 angstrom,
   probes spanning Rb/Cu/Sn/S and the Rb-S, Cu-S, Sn-S, and S-S pair shells,
   duplicate-noise checks, cutoff tests, `conv_thr` tests, and 2x2x2 versus
   3x3x3 force-k-mesh tests with a small 4x4x4 confirmation subset. Compare
   induced forces only after subtracting a pristine force calculated with the
   identical setting.
5. Make and record a scientific selection. Until then,
   `production.selection_required` stays `true`, and both the selected
   supercell and selected cutoff stay `null`.
6. Generate a dynamic task map from the accepted dataset. Every production
   SCF uses the same `nosym=.true.` and `noinv=.true.` policy as its matching
   pristine calculation. Failed attempts remain immutable, and collection
   runs with an `afterany` dependency so failure evidence is retained.
7. Construct FC2/FC3 only after every output has `JOB DONE`, a complete force
   block with the expected atom order, matching hashes, and a valid pristine
   force for `--cfz`.
8. Rotate every full conductivity tensor into the orthonormal Ibam conventional
   axes, then test the q-grid ladder at 300, 600, and 900 K. Acceptance requires
   less than 3% change in trace/3 and less than 5% in every conventional-axis
   diagonal at all temperatures for two consecutive steps.

## Preflight choices, not production settings

The QE primitive basis is strongly tilted, so simple diagonal replications are
poor choices. The declared nine-integer phono3py matrices must be checked from
their generated cell, not interpreted by eye. They use the verified column
convention: for row lattice vectors, `A_supercell = transpose(M) * A_unitcell`.

| ID | `--dim` values | Determinant | Atoms | Role |
| --- | --- | ---: | ---: | --- |
| M72 | `0 1 1 2 0 1 2 1 0` | 4 | 72 | economic candidate |
| M108 | `0 1 1 3 0 1 3 1 0` | 6 | 108 | validation candidate |
| M216 | `0 2 1 3 0 1 3 2 0` | 12 | 216 | harmonic/approved escalation only |

M72 is approximately 10.987 x 11.804 x 13.897 angstrom; M108 extends the
short direction to approximately 16.480 angstrom. The 216-atom choice is not
routine FC3 production and is count-only unless a new review explicitly
allows escalation.

The cutoff design values are 3.70 angstrom (lower-cost screen), 4.25 angstrom
(between the approximately 4.200 and 4.320 angstrom shells), and 5.00 angstrom
(between the approximately 4.878 and 5.162 angstrom shells). Their exact CLI
bohr values are in the JSON. M108/5.00 forces may be reused for an M108/4.25
analysis only if the smaller dataset is proven to be an exact indexed subset
and every structure, input, output, unit, atom-order, and content hash agrees.

## Force accuracy, q grids, and tensor frame

The reference displaced-force setting is 100/800 Ry, 3x3x3, and
`conv_thr=1e-10 Ry`, with the 4x4x4 confirmation subset. A cheaper setting
passes only if all declared limits hold: maximum component difference at most
`5e-5 Ry/bohr`, RMS component difference at most `1e-5 Ry/bohr`, relative
RMS difference at most 2%, and duplicate noise at most `5e-6 Ry/bohr`.

Raw phono3py Cartesian xx/yy/zz are not the conventional Ibam a/b/c
components for this tilted primitive cell. For accepted primitive row lattice
`A`, the config defines a right-handed conventional transform `T`. The audit
forms `C=T*A`, obtains the closest orthonormal row frame
`R=(C*C^T)^(-1/2)*C`, and reports

```text
kappa_conventional = R * kappa_cartesian * R^T
```

Both raw and rotated full symmetric tensors are retained. A reference `R` is
included only as a cross-check; it must be recomputed from the accepted tight
relax geometry.

Because a three-number primitive-axis mesh can obscure conventional-axis
resolution, the q-grid ladder uses generalized regular grids (`use_grg=true`)
from length-like design values of 45, 60, 75, 90, and 105 angstrom, converted
to QE-interface CLI bohr in the JSON. Every run records the generated integer
GRG matrix, full/irreducible counts, and reciprocal spacing. An off-diagonal
conventional component larger than 5% of trace/3 triggers investigation.

The first-pass solver is phono3py RTA with PBE, no explicit SOC, no isotope
scattering, no boundary scattering, and no NAC. Born effective charges and a
dielectric tensor have not been calculated. A result may therefore be called
only a calculated, no-NAC first pass; an NAC sensitivity test is required
before a final physical-convergence claim. This kappa_L would still not by
itself make the earlier electronic-only `zT_e` a final thermoelectric zT.
