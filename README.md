# Waterloo thermoelectric sulfides — screening workspace

Undergraduate research workspace (Kleinke group, University of Waterloo):
first-principles screening of thermoelectric sulfide candidates with
Quantum ESPRESSO, BoltzTraP2, and phono3py.

| Read this | For |
| --- | --- |
| `RESEARCH_BACKGROUND.md` | What the project is and where candidates come from |
| `README_START_HERE.md` | Orientation inside the workspace |
| `HANDOFF.md` | Current status + the immediate next task |
| `WORKFLOW_EXPLAINED.md` | Beginner-level tutorial for every calculation step |
| `learning/` | Hands-on curriculum (tools, code, data, comparisons) |
| `WINDOWS_SETUP.md` | Running the current phonon campaign on a Windows workstation (WSL2) |
| `CLAUDE.md` | House rules: scientific caveats, file handling, rigor review |

Materials: SrCu2SnS4, SrZrS3, Rb2Cu2SnS4 — first-pass electronic transport
done for all three (`thermo_candidates/*/results/`); lattice thermal
conductivity via phono3py is in progress
(`thermo_candidates/SrCu2SnS4/phono3py/`).

Not in this repo: QE scratch data (regenerable, ~34 GB) and the group's
internal/private material (ML screening dataset, slides, correspondence).
