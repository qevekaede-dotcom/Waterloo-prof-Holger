# SrZrS3 phono3py campaign

This directory defines the SrZrS3 finite-displacement campaign. The
time-bounded 2x1x1 first pass has now completed force collection and FC2/FC3
construction, but it does **not** provide an accepted lattice-thermal-
conductivity result. The first explicit no-NAC 12x5x3 RTA calculation found a
minimum sampled frequency of `-1.0716026422440281 THz`; the q-mesh ladder was
therefore stopped at the harmonic-frequency integrity gate. The run is
permanently labelled `first_pass_unconverged`, and its finite kappa tensor is
retained only as a rejected diagnostic. See
[`evidence/first_pass_unconverged/`](evidence/first_pass_unconverged/).

The machine-readable campaign design remains [`campaign.json`](campaign.json).
Its preferred `5e-5 Ry/bohr` pristine-force threshold was not weakened: the
observed `9.342e-5 Ry/bohr` is preserved as a failed gate with a separate,
explicit first-pass exception record. Null production choices remain stop
gates for any converged/default claim.

Heavy QE calculations, displacement generation, force-constant construction,
and phono3py transport postprocessing belong on a DRAC compute node. This
repository checkout is for preparation, versioned configuration, transfer,
and lightweight validation.

## Starting evidence and why a new relax is mandatory

The structure is the experimentally observed Materials Project entry
`mp-558760`, not the different `mp-5193` Pnma polymorph. The archived
high-precision final cell and coordinates are in the last `Begin final
coordinates` block of
[`../logs/SrZrS3.relax.out`](../logs/SrZrS3.relax.out). The rounded SCF input
is retained as a QE template and cross-check, not as the primary geometry.

The completed electronic workflow selected 50/400 Ry and an 8x4x2 final SCF
mesh for its own energy tests. Those tests did not establish force accuracy
for phonons. In the archived vc-relax final SCF block:

- QE reports total force `0.001307 Ry/bohr`;
- the largest Cartesian force component is `0.00050303 Ry/bohr`;
- the old geometry optimization was allowed to stop at
  `forc_conv_thr = 0.001 Ry/bohr`.

The campaign therefore starts with a fixed-cell ionic relaxation using the
high-precision output geometry, planned conservative settings of 80/640 Ry
and 10x5x3, `conv_thr = 1e-10 Ry`, and
`forc_conv_thr = 1e-5 Ry/bohr`. These stricter settings are planned choices,
not previously demonstrated convergence. The separate displaced-supercell
force pilot remains mandatory.

The tight-relax gate accepts at most `5e-5 Ry/bohr` for the largest force
component and stops hard above `1e-4 Ry/bohr`. Pnma (No. 62) must survive the
recorded tolerance scan. The archived high-precision geometry is already
Pnma at `1e-6 angstrom`, so this material is not silently idealized.

## Critical QE/phono3py distance-unit rule

The phono3py QE interface uses atomic units for length: `bohr`, also written
`au`. This applies to `--amplitude`, `--cutoff-pair`, and any other
distance-like CLI setting. The conversion fixed in the config is

```text
1 bohr = 0.529177210903 angstrom
CLI bohr = design angstrom / 0.529177210903
```

For example, the primary 0.03-angstrom displacement candidate is passed as
`--amplitude 0.0566917837388`, and a 4.0-angstrom pair cutoff is passed as
`--cutoff-pair 7.558904498503`. After every displacement generation,
`phono3py_disp.yaml` must contain `physical_unit: ... length: au`; otherwise
the workflow stops before force submission.

This also corrects a historical interpretation: the old SrCu2SnS4 command
`--cutoff-pair 4` meant **4 bohr = 2.116708843612 angstrom**, not 4 angstrom.
The current campaign never uses an unqualified distance. See the official
[calculator-unit table](https://phonopy.github.io/phono3py/interfaces.html)
and [QE workflow](https://phonopy.github.io/phono3py/qe.html).

## Gated workflow

1. Extract the final high-precision cell and positions from the archived
   vc-relax output, inject them into a new immutable fixed-cell relax input,
   and record source/config/pseudopotential hashes.
2. Accept the relaxed structure only after QE completion, atom-count, force,
   maximum-position-shift, and Pnma checks all pass.
3. On a compute node, generate count-only phono3py datasets for every declared
   supercell/cutoff candidate. Record the exact command, YAML, units, number
   of displacements, atom count, and cell metrics. A candidate with more than
   800 displacement supercells is ineligible for force submission, but its
   audited count remains a valid preflight result and does not erase cheaper
   candidates.
4. Run positive/negative amplitude probes at 0.02, 0.03, and 0.04 angstrom,
   covering symmetry-inequivalent Sr/Zr/S sites and Sr-S, Zr-S, and S-S pair
   shells. Test both the single-displacement central slope `D1` and the
   double-displacement four-sign mixed difference `D2_pair`; the latter is
   required because an FC2-like slope alone does not resolve FC3 signal.
   Include duplicate-noise, cutoff, `conv_thr`, and 2x2x2 versus 3x3x3
   force-k-mesh tests. Compare only after subtracting a pristine force
   calculated with exactly the same setting.
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
8. Test the explicit q-mesh ladder at 300, 600, and 900 K. Acceptance requires
   less than 3% change in trace/3, less than 5% in every diagonal tensor
   component, at all three temperatures, for two consecutive mesh steps.

## Preflight choices, not production settings

| Role | Supercell | Atoms | Planned/reference edge lengths [angstrom] |
| --- | --- | ---: | --- |
| Exploratory count-only lower-cost hypothesis | 2x1x1 | 40 | 7.677, 8.641, 14.003 |
| Exploratory count-only lower-cost hypothesis | 3x1x1 | 60 | 11.515, 8.641, 14.003 |
| Economic candidate | 3x2x1 | 120 | 11.515, 17.282, 14.003 |
| Preferred-size candidate | 4x2x1 | 160 | 15.354, 17.282, 14.003 |
| FC2 range check | 5x2x1 | 200 | generated value must be recorded |
| FC2 escalation only | 4x2x2 | 320 | generated value must be recorded |

The 2x1x1 and 3x1x1 rows record the historical 3.70-angstrom count-only
screen that was planned here and has now completed remotely: each generated
1003 displacement supercells and therefore exceeded the 800-file hard cap.
They remain audit history, not accepted settings, and cannot become
selection-eligible from count evidence alone. Their stored
edge lengths are planned/reference calculations, not generated measurements:
they come from applying the diagonal replication matrices to the versioned
reference cell `(3.838453236, 8.641205776, 14.002978756)` angstrom. This gives
2x1x1 edges `(7.676906472, 8.641205776, 14.002978756)` angstrom and a
half-shortest-edge reference bound of `3.838453236` angstrom; 3x1x1 gives
`(11.515359708, 8.641205776, 14.002978756)` angstrom and a bound of
`4.320602888` angstrom. A minimum-image pair-distance scan of the final
20-atom fractional coordinates in the same versioned source places 3.70
angstrom between reference shells at `3.613697991` and `3.783161892`
angstrom. These are reference-only calculations, not phono3py pair-group
evidence from the accepted remote structure. Thus 3.70 angstrom is a bounded
exploratory screen geometrically inside both reference half-cell bounds, but
that necessary check does not establish interaction-range convergence or
eliminate finite-size effects. Using the config's conversion constant,
`3.70 / 0.529177210903 = 6.99198666111535` bohr (the stored binary64 value).

The remote count-only run has now resolved that hypothesis: both 2x1x1 and
3x1x1 produced 1003 displacement supercells. Read-only inspection of their
accepted-structure YAMLs showed the same shell/species/site multiplicities,
although their raw displacement IDs and some symmetry-selected displacement
directions are not identical. Lowering the cutoff to 3.60 angstrom would
remove only the 3.604263809- and 3.616141604-angstrom S--S shells and predict
859 files, so 3.60 angstrom is rejected as still above the hard cap.

The only newly enumerated lower-cost hypothesis was 2x1x1 at
`3.5541348625` angstrom (`6.71634150010947` bohr), the midpoint of the
accepted-structure shell gap from `3.526178139` to `3.582091586` angstrom.
Thresholding the 3.70-angstrom YAML predicted 787 files. A fresh targeted Nibi
run has now reproduced that prediction exactly: 25 single displacements plus
762 included second-displacement IDs, with 147 included pair groups of which
122 are nonzero. Its generated YAML, exact shells, multiplicities, 787-file
inventory, submission chain, process records, and scheduler receipt are frozen
under [`evidence/3p5541348625A_count_only/`](evidence/3p5541348625A_count_only/).
The independent review verdict was `SHIP` for the **count-only gate only**.

This measured count replaces the former unrun prediction as the candidate's
status, but it does not promote the candidate scientifically. The 2x1x1
inscribed radius is `3.8384532612` angstrom, so the cutoff consumes about
92.6% of it and leaves only `0.2843183987` angstrom of clearance. A larger-cell
comparison and explicit probes of the newly excluded 3.582091586-,
3.604263809-, and 3.616141604-angstrom shells are still required. No 3x1x1
counterpart was newly enumerated because the earlier 3.70-angstrom pair had the
same displacement count while increasing every force cell from 40 to 60 atoms.

The previously declared routine FC3 pair-cutoff design values remain 4.0, 5.0,
and 6.0 angstrom, with their converted bohr values in the JSON. The no-cutoff
variants are count-only cost bounds and must never be submitted automatically.
Candidate status does not imply that any matrix or cutoff is scientifically
adequate. All existing production selections remain null and every production
gate remains closed pending explicit scientific, force, and resource review.

The completed remote count attempt was restricted to exactly this one signed
candidate identity:

```text
sr_fc3_2x1x1__sr_cutoff_3p5541348625A
```

The plan and execute records agree on candidate-subset SHA-256
`03818d4d8a130f6ff6b8d8f0df6668f7bcd87cb01d995ae58acd36bed0e94504`.
The frontend carried it through the Slurm exports, attempt context, campaign
CLI, and final inventory, so the targeted run did not silently enumerate the
older candidates. Its inventory correctly records only
`requested_scope_complete=true`; `preflight_complete` and
`full_config_preflight_complete` remain false, and `selection_eligible` remains
false. Calling preflight without candidate arguments is still the full-
enumeration mode and forbids the subset expectation option.

## Force and transport acceptance

The reference displaced-force setting is the most conservative member of the
pilot (80/640 Ry, 3x3x3, and `conv_thr=1e-10 Ry`). A cheaper setting passes
only if all declared limits hold: maximum component difference at most
`5e-5 Ry/bohr`, RMS component difference at most `1e-5 Ry/bohr`, relative
RMS difference at most 2%, and duplicate noise at most `5e-6 Ry/bohr`.
Before broader pilots, a six-SCF timing/noise batch limits concurrency to two
force tasks for this material. Later pilot batches are capped at 32 new SCFs;
production starts in batches of at most 32, then 64, and remains blocked until
a measured core-hour budget is explicitly recorded. A displacement-count cap
alone is not a resource authorization.

The q-mesh ladder is 12x5x3, 16x7x4, 20x9x5, 23x10x6, and 27x12x8 in the
primitive reciprocal basis. A largest tested mesh that fails the two-step
criterion may be reported only as `first_pass_unconverged`.

The first-pass solver is phono3py RTA with PBE, no explicit SOC, no isotope
scattering, no boundary scattering, and no NAC. Born effective charges and a
dielectric tensor have not been calculated. A result may therefore be called
only a calculated, no-NAC first pass. The no-NAC command must explicitly use
`--nonac` and reject an accidental `BORN` file or YAML `nac_params`; an NAC
sensitivity test is required
before a final physical-convergence claim. This kappa_L would still not by
itself make the earlier electronic-only `zT_e` a final thermoelectric zT.
