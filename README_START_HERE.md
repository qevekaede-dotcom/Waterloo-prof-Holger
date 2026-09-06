# Start Here

For a new or resumed session, read [CLAUDE.md](CLAUDE.md) and
[AGENTS.md](AGENTS.md) for scientific/file-handling rules, then
[HANDOFF.md](HANDOFF.md) for verified state and next research work.
Before editing a material or package, read its scoped `CLAUDE.md` and the
original evidence. Old logs and archived handoffs are history, not active
instructions to restart completed calculations.

Completely new to DFT, Quantum ESPRESSO, or BoltzTraP2? Read
`WORKFLOW_EXPLAINED.md` first — it explains from zero background what these
calculations are, what every parameter means, how each was chosen, and how to
read every result file in this workspace.

To go deeper — tool usage, code walkthroughs, data-handling skills, and the
material-comparison methodology — work through the curriculum in `learning/`
(start at `learning/README.md`).

Use this folder for the project:

```text
thermo_candidates/
```

The old single-material folder `thermo_SrCu2SnS4/` was removed because it
duplicated the new three-candidate workspace.

## Current Status

The three experimentally observed Materials Project CIF files have been
downloaded and validated:

```text
thermo_candidates/SrCu2SnS4/structures/SrCu2SnS4.cif
thermo_candidates/SrZrS3/structures/SrZrS3.cif
thermo_candidates/Rb2Cu2SnS4/structures/Rb2Cu2SnS4.cif
```

The complete QE and BoltzTraP2 workflow for `SrCu2SnS4` is finished:

- cutoff and k-point convergence tests
- variable-cell relaxation
- final SCF and dense NSCF
- BoltzTraP2 interpolation and 300-900 K transport tables

Start learning from:

```text
thermo_candidates/SrCu2SnS4/results/workflow_summary.md
thermo_candidates/SrCu2SnS4/results/transport_best_power_factor.csv
```

All three first-pass workflows are now complete. `SrZrS3` and `Rb2Cu2SnS4`
each repeated the full convergence workflow with their own parameters rather
than copying SrCu2SnS4's; their results are in the respective `results/`
folders. The side-by-side comparison is in `learning/05_comparing_materials.md`.

SrCu2SnS4 also has first-pass lattice thermal conductivity from the completed
168-displacement DRAC campaign. SrZrS3 and Rb2Cu2SnS4 phonons remain pending.
The fourth-step interim email and its two attachments were sent; the full
three-material writeup remains a draft. See `HANDOFF.md` for limitations
and `README.md` for cross-computer Git workflow.
