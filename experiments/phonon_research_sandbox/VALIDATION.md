# Validation and interpretation record

Validation date: 2026-09-21. Scope: local software, derived summaries and presentation artifacts. No new physical result was computed. No live cluster status was inspected.

The separate [2026-09-22 local-development validation](round2/VALIDATION.md)
records new standalone tools and diagnostics. The checks below remain the first
round's historical validation; their unchanged suites were not rerun in round 2.

## Code

The tooling worker ran the existing full shared campaign suite once: **435 passed**. The coordinator inspected the changed source/tests, then independently ran only the focused affected checks:

```sh
PYTHONPATH=thermo_candidates/scripts/phono3py_campaign /usr/bin/python3 -m unittest -v \
  thermo_candidates.scripts.phono3py_campaign.tests.test_qe_output \
  thermo_candidates.scripts.phono3py_campaign.tests.test_srcu_legacy_gate
```

**13 passed**, including actual preserved SrCu historical evidence and the new complete-force/JOB-DONE/late-MPI-ABORT regression.

```sh
PYTHONPATH=thermo_candidates/scripts/phono3py_campaign \
  /Users/kaede/scientific-tools/envs/thermo-bt2/bin/python -m unittest discover \
  -s thermo_candidates/SrCu2SnS4/phono3py_v2/tests -p test_v2.py
```

**18 passed**. This environment supplies PyYAML; system Python lacks it. The tests use synthetic software fixtures explicitly as tests, not research data. They do not demonstrate real phono3py displacement generation, QE execution or material convergence.

## Data and artifacts

- Rb analysis recomputes 105 data rows from the saved audit JSON. All 12 archived temperature/transition rows agree with the current-denominator convention. No new remote HDF5 bytes were opened.
- The deck data extraction independently recomputes the final Rb transition and reads the original electronic derived CSV files. Source SHA-256 values are stored in `presentation/reproducibility/deck_data.json`.
- Presentation package: **11 slides**, **3 native editable charts**, **2 native editable tables**. Embedded chart workbook values and chart caches match. Package integrity, declared layout/font checks and artifact-runtime reimport pass. All 11 final slides were rendered and visually inspected.
- Every PPT XML text part was searched for Chinese characters: none found. The EN/ZH speaking script is a separate Markdown file.
- The final PPTX uses Arial and ten-significant-digit chart snapshots for Excel portability. Chart display labels use two decimals. Original research data retain their precision.
- Native PowerPoint application opening/editing has **not** been tested. Runtime rendering does not prove native application behavior.
- Markdown relative links were checked for existing local destinations. Browser checks and independent review disposition are appended below when complete.

## Preservation and scientific self-review

- Original HANDOFF archive equals `git show cf21cce:HANDOFF.md` byte-for-byte.
- Historical worklogs retain their entire previous byte prefix; new entries append only.
- Changed path inventory contains no `READY_TO_ATTACH/`, raw QE inputs/logs, historical numeric results or original sent-body sources.
- New claims keep PF/τ separate from absolute PF, electronic-only zT separate from full zT, saved integrity separate from scientific convergence, and proposed thresholds separate from implemented ones.
- Pending physical questions remain: SrCu corrected baseline and all relevant convergence dimensions; SrZr soft-mode origin; Rb force-model and q-mesh convergence. No accepted κL or final zT is created by these validations.

## Final UI and independent-review disposition

- Headless Chrome desktop/mobile checks: no JavaScript errors; 12 transition
  rows and 105 tensor rows present. Page width equals viewport width at both
  1440 px and 390 px. Table scrolling is contained and full tensor details are
  collapsed by default. Desktop and mobile renders inspected.
- Fresh independent Sol review found three issues, preserved in
  `review/INDEPENDENT_SOL_REVIEW.md`. Q-commensurate SrZr mode construction and
  conditional three-level physical convergence studies resolved two findings.
  V2 now reports `execution_provenance_verified=false`; future trusted execution
  receipts remain unimplemented and are required before real-run acceptance.
- Narrow follow-up review accepted those changes and conditioned local-scope
  ship on replacing one stale error message. The coordinator made that exact
  text-only correction and confirmed the old wording is absent. No logical
  code change followed the passing 18-test v2 run.
- Final disposition: the reviewer's condition is fulfilled for **local
  plan/preparation scope only**. It does not authorize jobs or certify a
  scientific force/phonon/kappa result.
