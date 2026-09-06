# Research continuity instructions

Before changing this repository, read `CLAUDE.md` (standing scientific and
file-handling rules), then `HANDOFF.md` (current state), then the relevant
material/package `CLAUDE.md`. These rules apply to Codex as well as Claude.
Use `README.md` for navigation; historical handoffs are not active task lists.

## Source of truth across computers

- GitHub holds the shared research history. Fetch and compare remote branches
  before deciding what is current; `main` has previously lagged active work.
- Inspect local changes first. Never overwrite uncommitted work or assume
  ignored files can be recovered from GitHub. Private background material and
  QE scratch are deliberately outside Git.
- Read the original inputs, logs, and machine-readable results for the task at
  hand. A handoff is an index and status summary, not a substitute for evidence.
- Preserve every `READY_TO_ATTACH/` as a frozen record of sent attachments.

## Long-running research sessions

- Keep `HANDOFF.md` concise: verified completion, limitations, next action,
  source paths, and any blocker. Update it at substantial milestones.
- Append dated steps, failed attempts, and validation to the relevant
  `WORKLOG.md`; use the root log for repository-wide maintenance. Do not
  rewrite past log entries. Keep stable instructions here and in `CLAUDE.md`,
  not only in chat history.
- On resuming, re-read these files and inspect Git status before acting.
  A past job ID or log is historical evidence, not a live cluster status.
- Heavy QE calculations and phonon postprocessing belong on DRAC compute
  nodes under the current workflow. Local machines handle preparation,
  transfer, Git, writeup, and lightweight read-only validation. A cleanup or
  status request is not an instruction to launch or rerun calculations.
- Finish with the scientific-rigor review required by `CLAUDE.md`. Flag
  unresolved issues explicitly; do not silently strengthen a first-pass claim.
