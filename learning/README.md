# Learning Curriculum

A hands-on study path for this workspace, written for a complete beginner.
The conceptual companion is `../WORKFLOW_EXPLAINED.md` (what DFT is, why we
compute, what every parameter means) — read its sections 1–3 first if you
have never seen any of this. The documents here go deeper into *doing*:
running the tools, reading the code, handling the data, and judging the
materials.

## Verification status

All seven documents were drafted by reading the repo, then fact-checked by an
adversarial reviewer that re-opened every cited source, re-computed derived
values, and flagged any house-rule violation. All passed with zero critical
issues. Rb2Cu2SnS4's first pass has since completed and its real numbers
(sampled PBE gap 0.7811 eV; p-type favored by both metrics) are now folded in.

## The documents

| # | File | What you learn |
|---|---|---|
| 1 | `01_tools_quantum_espresso.md` | Quantum ESPRESSO in practice: input-file anatomy, running pw.x/dos.x, reading every important line of the logs |
| 2 | `02_tools_boltztrap2.md` | BoltzTraP2 in practice: the three CLI stages, file formats and column meanings, our compatibility shim, known pitfalls |
| 3 | `03_code_walkthrough.md` | Every script in this repo: what it does, how the code works, and the patterns to copy for a new material |
| 4 | `04_per_material_playbook.md` | The 7-step pipeline as a playbook: task → why it exists → data produced → checks, with all three materials' real numbers |
| 5 | `05_comparing_materials.md` | How to compare candidates and judge "is this material promising?" — metrics, assumptions, and the worked comparison |
| 6 | `06_data_handling.md` | Practical data skills: every CSV column, unit conversions, plotting recipes, sanity-check habits |
| 7 | `07_exercises.md` | Hands-on exercises with an answer key, all verifiable against files in this repo |
| 8 | `08_phonons_and_kappa_L.md` | Phonons, fc2/fc3, and the phono3py campaign for lattice thermal conductivity — written while the SrCu2SnS4 campaign runs; numbers marked [pending] until it finishes |

## Suggested paths

- **"I just want to understand our results"**: 04 → 05 → 06.
- **"I want to be able to rerun and extend the calculations"**: 01 → 02 → 03 → 04.
- **"Give me quick practical skills"**: 06 → 07.

## Conventions

Values are tagged [calculated] / [database] / [experimental]; every table
column carries units; the scientific house rules of `../CLAUDE.md` apply to
every sentence here (PF/tau is not an absolute power factor; electronic zT_e
is not the final zT; no SOC; "best" means best on the sampled grid;
convergence parameters are per-material).

Status note: all three materials (SrCu2SnS4, SrZrS3, Rb2Cu2SnS4) have now
completed their first pass; the comparison document carries Rb2Cu2SnS4's real
values (sampled PBE gap 0.7811 eV, p-type favored by both metrics).
