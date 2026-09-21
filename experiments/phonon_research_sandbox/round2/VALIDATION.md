# Second-round validation — local preparation only

Date: 2026-09-22. Baseline: `dfefd48`. No new material calculation, FC fitting,
transport solve or remote query was performed. The existing shared/v2 source
code, scientific thresholds and English PPT were not changed.

## Worker checks and coordinator acceptance

| Artifact | Focused validation | Scope |
|---|---|---|
| Execution receipts | Worker: 11 synthetic tests, compilation, JSON syntax. Coordinator: 3 selected success/corruption/nonzero-exit cases passed. | Protocol under stated accidental-corruption model; no QE/MPI integration. |
| q/supercell | Worker: 9 exact-arithmetic tests, example JSON and SVG XML checks. Coordinator: non-diagonal CLI case returned q·T = [0,2,0], det=5, conditional 100 atoms with actual basis false. | Geometry only; no eigenvectors or physical stability. |
| Rb reuse inventory | Worker: deterministic regeneration, compilation, 2 synthetic regression tests. Coordinator: those 2 cases passed; inspected source hashes/fields and preflight candidate matched by YAML hash. | Presence cannot establish readiness; explicit au length required for conversion. |
| Rb component figure | Recomputed 48 changes and 12 joint verdicts directly from saved audit tensors, with exact current-denominator convention. Every value agrees within floating-point reproduction tolerance. | No fit, extrapolation, FC or new HDF5 audit. |
| Duplicate-source candidate | Read-only manifest grouping: 541 singletons, 64 pairs, one 11-task group. YAML/manifest digest agreement and one-to-one label mapping checked; the largest group has same-atom opposite vectors. | No force noise measured, original generated inputs not reopened, no automatic reuse/deletion or guaranteed savings. |
| Dashboard | Headless Chrome: 3 new tool cards, new chart loads, zero JavaScript errors, body widths 1440/390 equal viewport widths. New panel and figure visually inspected. | Local file UI; no personal browser session used. |

Scoped reproducible test commands (from repository root):

```bash
python3 -m unittest discover -s experiments/phonon_research_sandbox/tooling/execution_receipts/tests -v
python3 -m unittest discover -s experiments/phonon_research_sandbox/tooling/q_commensurability -p 'test_*.py' -v
python3 -m unittest discover -s experiments/phonon_research_sandbox/analysis/rb_reuse -p 'test_*.py' -v
```

These synthetic tests must not be presented as scientific measurements. Detailed
receipt checks are recorded in [its validation file](../tooling/execution_receipts/VALIDATION.md).
The chart environment was existing `thermo-bt2` Python with matplotlib 3.11.0 /
numpy 2.4.6. Bundled document Python lacked matplotlib; no installation was needed.

## Evidence interpretation

- 12 out of 12 saved zz transition/temperature checks fail; 6 out of 12 trace
  checks pass individually. This explains why averages cannot replace tensor
  checks; it does not establish converged material anisotropy or an error bar.
- The preflight candidate hash matches the locally saved YAML and production
  manifest, binding the saved 3.70 Å generation record to that dataset. It is
  stronger than just reading an unselected campaign candidate; it is still
  historical evidence, not current remote-file validation.
- Headerless pilot sacct rows retain inferred AllocCPUS / ReqMem labels, with
  the inference and source schema stated. Requested memory is not measured RSS.
- The q checker uses a stated column-basis convention and exact rational
  arithmetic. An IFC interpolation test is not rejected merely because it
  cannot contain a particular q as a frozen periodic distortion.
- All receipt verification records keep production QE provenance, v2
  integration and scientific acceptance false. Final-anchor integrity does
  not prove semantic input consumption, dependency completeness, or a
  pre-launch commitment.
- The duplicate-source analysis is a candidate follow-up, not an additional
  acceptance gate. Its source grouping and nominal vector cancellation do not
  establish equivalent complete SCF inputs, healthy execution or repeat noise.

## Independent review and preservation closure

Fresh Sol disposition: **SHIP for local preparation scope**, zero actionable
findings. The review covers the three tools, chart/Q&A and repeated-source
candidate; it did not rerun unchanged broad suites. See
[ROUND2_SOL_REVIEW](../review/ROUND2_SOL_REVIEW.md).

The complete earlier sandbox WORKLOG byte prefix is preserved. The round-two
diff changes no material-source directory, raw QE input/output, historical
numeric result, sent body or READY_TO_ATTACH. All three pre-existing worktrees
remain clean. New Markdown/HTML destinations and source hashes were checked;
the new plots and panel were visually inspected. `git diff --check dfefd48`
passes after normalizing only the newly generated SVG's trailing spaces.

No material obtained accepted κL or full zT; no existing v2 execution release
was changed. The closing Git checkpoint records only local reviewed artifacts.
