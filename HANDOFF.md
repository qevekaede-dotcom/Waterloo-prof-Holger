# Research handoff — current state

Repository evidence checked 2026-09-21. Current experiment branch:
`codex/phonon-research-sandbox`, forked from
`origin/codex/complete-three-material-phonons` at `cf21cce`.
No current Nibi state was checked and no remote job action was taken.

Local tool development continued on 2026-09-22; see [round 2](experiments/phonon_research_sandbox/round2/README.md). No new material calculation changed the scientific state below.

Read `CLAUDE.md`, `AGENTS.md`, and scoped rules before changes.
Use [the current evidence entry](experiments/phonon_research_sandbox/CURRENT_STATE.md)
and [sandbox deliverables](experiments/phonon_research_sandbox/README.md).

## Verified repository state

| Material | Electronic first pass | Phonon limitation |
|---|---|---|
| SrCu2SnS4 | Complete | Historical first pass rejected under current contract; 4 bohr, mixed settings, unhealthy terminal outputs, tensor mesh nonconvergence. v2 preparation only. |
| SrZrS3 | Complete | 788 force records including pristine, FC2/FC3 generated. Minimum sampled −1.0716 THz rejects kappa. Origin unresolved. |
| Rb2Cu2SnS4 | Complete | Saved FC/q-mesh artifact audit passes limited integrity checks; all four tested mesh transitions fail. No accepted kappa_L. |

Electronic first pass does not prove dense-k transport convergence. PF/tau is
not absolute PF and zT_e is not full zT. All three lack accepted kappa_L;
full zT also needs a relaxation-time model. No explicit SOC in those passes.

The user confirmed sending the revised Roy update on 2026-09-21; the exact
sent email was not independently retrieved. Roy's next-priority choice remains
pending. Full three-material phonon writeup is an unsent draft. Every existing
`READY_TO_ATTACH/` and sent-body source stays frozen.

## Next action and recovery

Continue from [sandbox HANDOFF](experiments/phonon_research_sandbox/HANDOFF.md),
which records implementation, validation, review and commit checkpoints.
The three material plans are proposals. No new QE, FC fitting, kappa solve or
job submission is authorized by this handoff. Heavy work belongs on DRAC.

Do not rerun Rb's completed force array or promote its 105-A diagnostic tensor.
Do not treat SrZrS3's finite tensor as valid or erase imaginary frequencies to
obtain kappa. Do not treat SrCu2SnS4's unit conversion as scientific validation.
Preserve historical blocked jobs and archived failure evidence.

The [previous handoff](docs/archive/HANDOFF_before_phonon_sandbox_2026-09-21.md)
is preserved verbatim, including all historical snapshots and communications.
Its dated running states and superseded action lists are not current tasks.
