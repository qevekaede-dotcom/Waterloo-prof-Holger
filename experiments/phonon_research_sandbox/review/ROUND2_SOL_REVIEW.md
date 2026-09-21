# Round-two independent Sol review

Date: 2026-09-22. Review baseline: `dfefd48`; reviewed committed checkpoint
`323ccc6` plus the round-two tracked/untracked working-tree artifacts. Reviewer
did not implement the reviewed tools or analyses.

## Disposition: SHIP

No fix-first scientific or code finding remains in the reviewed local-preparation
scope. The new artifacts answer bounded questions without promoting any material
to accepted lattice thermal conductivity, changing a scientific threshold, or
authorizing execution. No raw record or `READY_TO_ATTACH/` path is changed by the
reviewed diff.

## Evidence checked

1. **Execution receipt boundary.** `tooling/execution_receipts/execution_receipt.py:177-213`
   hashes the input and declared dependencies before creating a plan and checks
   that the retained input bytes match the input digest. Lines 222-263 create the
   run evidence before passing those retained bytes to the child stdin; lines
   284-335 record exit/output digests and create the final external anchor only
   after completion. Verification at lines 369-465 binds the receipt to that
   anchor, checks canonical evidence names, stream/snapshot digests, source drift,
   the exact executable position, the environment allowlist and nonzero exit.
   This is consistent with the stated accidental-corruption model. The limits are
   explicit in `tooling/execution_receipts/README.md:77-116`: the anchor is not a
   pre-launch commitment, stdin delivery is not semantic consumption, declared
   pseudopotentials are not proven opened, and the recorder is not a QE, MPI or
   scheduler runner. Every machine-readable scope record keeps v2 integration,
   production QE provenance and scientific acceptance false.

2. **q/supercell mathematics and physical boundary.** The implementation uses
   integer nonsingular 3x3 matrices, exact rational q values, `A_super =
   A_reference S`, and computes the three generator phases as `S^T q`
   (`tooling/q_commensurability/q_commensurability.py:73-142,158-227`). The
   determinant multiplier is `abs(det(S))`; the code neither requires a diagonal
   matrix nor generates atomic motion. A narrow independent CLI probe of the
   non-diagonal example returned `q·T = [0,2,0]`, determinant 5 and
   `commensurate=true`, while the physical frozen-mode preconditions remained
   false. The 100-atom value is therefore correctly conditional on a 20-atom
   reference cell and a verified common basis, as documented at
   `tooling/q_commensurability/README.md:22-77`.

3. **Rb reuse provenance and units.** `analysis/rb_reuse/build_inventory.py:77-107`
   binds the local manifest, archived YAML and the unique saved preflight
   candidate by the YAML SHA-256. Lines 62-74 require the YAML length unit to be
   `au`/bohr before deriving the first displacement amplitude; lines 145-208 keep
   production authorization, accepted kappa and current reuse readiness false.
   FC2/FC3 are described only as historical remote-audit artifacts, while their
   local candidate paths are reported absent. The saved generation record, rather
   than an unselected campaign proposal, supplies the 3.70 Å cutoff and 679
   displacement count. Headerless `sacct` values are labeled inferred
   `AllocCPUS`/`ReqMem`, not measured RSS or a core-hour forecast.

4. **Rb component reanalysis.** `analysis/rb_component_diagnostics/build_diagnostics.py:18-52`
   recomputes each diagonal and trace change with the denser current value as the
   denominator and cross-checks it against the saved audit, including each joint
   verdict. The resulting CSV contains 48 rows: a narrow count confirmed 12/12
   `zz` failures and 6/12 trace checks passing in isolation. The figure and
   `round2/REPORT_QA_EN_ZH.md:61-83` correctly distinguish component
   cancellation/dilution from tensor convergence and avoid extrapolating a
   converged value or physical error bar.

5. **New repeated-source candidate.** Independent grouping of the 680 saved
   manifest tasks reproduced 606 source-hash groups: 541 singletons, 64 pairs and
   one 11-task group, hence 74 records beyond one per recorded hash. The generator
   binds the manifest to the saved YAML before mapping the largest group
   (`round2/duplicate_sources/analyze_sources.py:16-63`). All 11 mapped pairs are
   included same-atom nominal cancellations, but their recorded source hash is
   different from pristine. `round2/duplicate_sources/README.md:16-25` therefore
   proposes only a future bounded existing-data check: verify inputs, settings and
   health before comparing force blocks; preserve every phono3py mapping; never
   count a reused force as an independent repeat. It does not claim measured
   noise, deletable tasks, automatic reuse or guaranteed savings.

## Residual boundaries accepted for this checkpoint

- The receipt prototype still needs a separately reviewed QE/MPI/scheduler and
  v2 integration before it can close `execution_provenance_verified=false`.
- The actual SrZr direct/reciprocal basis, atom mapping and eigenvectors remain
  unverified; the q helper establishes lattice arithmetic only.
- Rb FC identity and the repeated-source force outputs remain historical/local
  records until a separately authorized bounded remote read. No new q-mesh,
  force, FC or kappa calculation follows from this review.

I did not rerun the unchanged broad suites. I inspected their recorded focused
validation and used only narrow read-only probes for the non-diagonal q case,
the 48-row component counts, the manifest multiplicity histogram and the
11-record nominal-cancellation flags. Scientific-rigor outcome: quantities and
units are source-traced, calculated versus historical/inferred facts are
distinguished, and no PF/tau, electronic-only zT, SOC, sampled-grid, kappa or
convergence claim is strengthened.
