# Sandbox handoff — second local-development round

Date: 2026-09-22. Branch: `codex/phonon-research-sandbox`.
Worktree: `/Users/kaede/.codex/worktrees/phonon-research-sandbox`.
Read [README](README.md), [current scientific state](CURRENT_STATE.md), then
[round 2](round2/README.md). No current Nibi state was checked.

## Saved checkpoints

- Base `cf21cce`: latest fetched complete-three-material-phonons branch at fork.
- `246037c`: isolated sandbox and evidence/status reconciliation.
- `25555c1`: terminal-QE/parser and v2 input-integrity fixes.
- `a2bf49d`: reviewed plans, dashboard, learning guide, English PPT and script.
- `dfefd48`: first-round final navigation and handoff.
- `323ccc6`: second-round all-temperature Rb diagnostics and bilingual report Q&A.
- Closing second-round commit: use `git log -1 --oneline` and compare the remote;
  final task reply records the exact hash. Do not amend/force-push old checkpoints.

## Completed local work

1. Three scientific proposals with controls, criteria, dependencies, resource
   estimation basis and stop conditions. They are proposals, not compute approval.
2. Chinese offline dashboard; existing 105-row Rb table plus a 48-cell component
   change figure. Twelve zz checks fail while six trace-only checks pass. No fit.
3. Eleven-slide entirely English PPT with editable charts/tables; separate EN/ZH
   script and twelve new report Q&A answers. PPT unchanged in round 2.
4. Standalone execution-receipt recorder/verifier: hashed input delivered over
   recorder-owned stdin, explicit argv/cwd/environment, stream/exit evidence and
   separate final anchor. Eleven synthetic tests. No QE/MPI/v2 integration.
5. Exact-rational q/supercell checker: columns convention, S^T q integer test,
   conditional atom counts, separate frozen-mode/IFC interpretations. Nine tests;
   phase SVG is mathematics only, not an atomic mode.
6. Rb reuse inventory: local manifest/YAML/preflight hashes matched, remote FC
   bytes unverified; explicit unit/metadata limits and two regression tests.
7. New duplicate-source candidate: 65 repeated-source-hash groups; an 11-task
   group has same-atom cancelling displacements in the saved YAML. Existing
   force outputs may provide a useful repeat-noise check, but have not been
   compared. No deduplication or guaranteed resource savings claimed.

Validation: [first round](VALIDATION.md), [second round](round2/VALIDATION.md).
Review: [first-round Sol](review/INDEPENDENT_SOL_REVIEW.md),
[second-round independent Sol](review/ROUND2_SOL_REVIEW.md).
Check the second-round review disposition before adapting any new tool.
Its final disposition is SHIP for local preparation scope, with zero actionable
findings. This does not release or validate a real material calculation.

## Scientific questions still unanswered

- No accepted κL or final zT for any material. Electronic first passes lack
  established dense-k transport convergence and explicit SOC; PF/τ is not PF.
- SrCu v2 has no corrected real force dataset. Its existing reports still state
  execution_provenance_verified=false. The standalone final-anchor prototype
  does not provide a pre-launch external commitment or prove consumption of all
  named dependencies, and is not a trusted QE runner.
- SrZr negative-mode origin, archived q basis and eigenvector/atom mapping remain
  unresolved. Conditional 100-atom geometry is not a validated distortion cell.
- Rb force-model/q-mesh convergence remains unresolved. Current remote FC bytes
  and equivalence/health of the duplicate-source tasks remain unchecked.
- Roy's next-priority reply is not recorded. Sending the revised status update
  was user-confirmed on September 21; the exact sent email was not retrieved.

## Next concrete tasks, chosen by scientific benefit

- If Rb is prioritized, first consider the [existing-data noise probe](round2/duplicate_sources/README.md).
  After separate authorization for a bounded remote read, verify the 11 inputs
  and pristine, extract healthy final force blocks and compare only genuinely
  equivalent calculations. No new job is needed for this evidence question.
- If SrCu is prioritized, adapt the receipt protocol to the actual v2 manifest,
  QE input/pseudo resolution and intended scheduler/MPI path in disposable local
  tests first. Preserve false releases until the adapter and independent anchors
  are reviewed; do not just flip the current provenance flag.
- If SrZr is prioritized, retrieve/replay the existing FC2 mode with authorized
  compute placement, establish q/reference/eigenvector bases, then apply the
  geometry checker. Do not start new FC3 while the instability is unresolved.
- Use the [report Q&A](round2/REPORT_QA_EN_ZH.md) to rehearse explanations and
  discuss the three options with Roy. No message has been sent by this round.

All original raw records, sent bodies and READY_TO_ATTACH directories remain
frozen. Worklogs are append-only. No SSH, job mutation, heavy physics solve,
outbound email, main merge or other-worktree edit occurred.
