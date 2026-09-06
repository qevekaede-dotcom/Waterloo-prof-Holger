# Waterloo thermoelectric sulfides — screening workspace

Undergraduate research workspace (Kleinke group, University of Waterloo):
first-principles screening of thermoelectric sulfide candidates with
Quantum ESPRESSO, BoltzTraP2, and phono3py.

| Read this | For |
| --- | --- |
| [HANDOFF.md](HANDOFF.md) | Current verified state, open issues, next research work |
| [README_START_HERE.md](README_START_HERE.md) | Reading order for new/resumed sessions |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md) | Continuity, scientific caveats, file handling, rigor review |
| [RESEARCH_BACKGROUND.md](RESEARCH_BACKGROUND.md) | Project motivation and candidate selection |
| [Material workspace](thermo_candidates/README.md) | Inputs, original records, derived results |
| [WORKFLOW_EXPLAINED.md](WORKFLOW_EXPLAINED.md), [learning](learning/README.md) | Beginner tutorial and curriculum |
| [DRAC_SETUP.md](DRAC_SETUP.md) | Cluster workflow; verify environment before reuse |
| [WINDOWS_SETUP.md](WINDOWS_SETUP.md) | Historical WSL setup, not the active compute plan |
| [Repository audit](docs/REPOSITORY_AUDIT.md), [WORKLOG.md](WORKLOG.md) | Branch reconciliation, cleanup and verification |

## Current research state

| Material | Electronic first pass | Lattice thermal conductivity |
| --- | --- | --- |
| SrCu2SnS4 | Complete | First pass complete; convergence limits remain |
| SrZrS3 | Complete | Next campaign; no results recorded |
| Rb2Cu2SnS4 | Complete | Pending |

Each electronic workflow has independent convergence tests, relaxation,
SCF/NSCF, and 300–900 K transport tables. SrCu2SnS4's residual-corrected
first-pass average kappa_L is 0.3639 W m^-1 K^-1 at 300 K [calculated,
PBE, no SOC, RTA, no NAC]. This is not a fully converged tensor or a final
zT; see [status and limitations](HANDOFF.md).

The numbered step-result folders are presentation packages; the material
workspace retains the authoritative raw/derived records. Every
`READY_TO_ATTACH/` is a frozen record of sent files. The fourth package's
interim email is sent; its full three-material writeup is not.

## Working across computers

**GitHub is the shared source of truth.** A local checkout is a working
copy for inspection, editing, and validation. Another clone is unnecessary
when an existing checkout can be updated safely. Heavy computation and
phonon postprocessing belong on DRAC, not this Mac.

1. Run `git status --short --branch`; preserve any uncommitted work.
2. Run `git fetch origin`; inspect remote branches and recent commits.
   Do not assume `main` contains the latest research work.
3. Switch to `main` (or an explicitly agreed task branch). Use
   `git pull --ff-only` on its clean, matching checkout; never reset local
   work just to force a sync.
4. Read `HANDOFF.md`; update it at milestones and append a work-log entry.
   Review and explicitly stage relevant files before committing/pushing.

The 2026-09-06 cleanup started from `0024114` on
`claude/canada-computing-center-task-d165w2`, which included the other
research branches and was then 13 commits ahead of `main`. This work was
merged into `main` through [PR #1](https://github.com/qevekaede-dotcom/Waterloo-prof-Holger/pull/1)
at the user's request. **Use `main` as the current shared baseline.**
The temporary `codex/research-repository-cleanup` branch was deleted locally
and on GitHub; its commits remain in `main`. Other research branches remain.

Not in this repo: QE scratch data (regenerable, ~34 GB) and the group's
internal/private material (ML screening dataset, slides, correspondence).
Existing local ignored files were left untouched; GitHub cannot restore
them. Do not publish private correspondence, internal datasets, or credentials.
