# Work log

## 2026-09-20 — package index assembled

Created this independent, read-only index package. It links to existing small
evidence and reproducibility records only; it does not copy QE logs, force
sets, HDF5 files, or material inputs, and it does not create or alter any
`READY_TO_ATTACH/` directory.

The SrZrS3 entry is traced to its compact audit and rejected-diagnostic record.
The Rb2Cu2SnS4 entry preserves the distinction between the historical failed
production element, the still-untouched old postprocess, and the newly
submitted narrow recovery chain. No cluster query, calculation, rerun, or
postprocessing was performed while assembling this package.

## 2026-09-20 — Rb recovery evidence index updated

The saved terminal-evidence capture now records `22312416` as `COMPLETED/0:0`
and `22312417` as `FAILED/1:0`. The latter reached FC2/FC3 creation and all
five q-mesh stages: only qmesh-04 has a directly retained zero exit code,
while the preceding four successes are control-flow-implied by later qmesh-04
execution. It failed only at its final scan because
`fc3.hdf5` lacks `force_constants`; no `kappa_summary.json` or
`kappa_L_first_pass.csv` was produced. This is an evidence-index update, not a
new calculation or scientific result. The compact record is
[`postprocess_22312417_evidence_summary_20260920.json`](../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_evidence_summary_20260920.json).

## 2026-09-20 — Rb read-only HDF5 audit integrated

The later saved read-only audit adds direct artifact checks without changing the
recorded scheduler outcome: FC2/FC3 integrity, shapes, finite values, maps,
version, and atom binding pass, as do its harmonic and off-diagonal gates.
These are limited checks, not acceptance of a physical force-constant model or
full phonon stability. All q-mesh transitions fail; for 90->105 A, trace/3
changes are 4.2663%, 4.0831%, and 4.04694%, while the largest diagonal changes
are about 10.192%, 9.692%, and 9.594% at 300/600/900 K. The 105-A tensor is a
rejected diagnostic only, so no accepted kappa_L exists. The local finalizer
was repaired but did not write a remote summary or launch recomputation or a
submission. This remains a local documentation update only.
