# Session memory

## Continuation state

- This package is an index, not an attachment package and not a new source of
  truth. Read the linked material records before changing a scientific status.
- SrZrS3 has complete force-accounting and structurally valid FC2/FC3 arrays,
  but its non-NAC 12x5x3 frequency gate failed. It remains
  `first_pass_unconverged`; no valid kappa_L or zT combination may be claimed.
- Rb2Cu2SnS4 has passed its upstream FIRE/pristine/preflight/pilot gates.
  Original production element 361 was recovered; element 462 failed at QE
  module start-up. Saved terminal evidence records recovery `22312416` as
  `COMPLETED/0:0` and dependent wrapper `22312417` as `FAILED/1:0`. The wrapper
  reached FC2/FC3 and all five q-mesh stages; it failed only at its final scan
  because it expected `force_constants` in `fc3.hdf5`, whose FC3 dataset is
  named `fc3`. A saved read-only HDF5 audit passes FC2/FC3 integrity, shapes,
  finite values, maps, version, atom binding, harmonic, and off-diagonal checks.
  Those limited checks do not validate the physical force constants or full
  phonon stability. Every q-mesh transition fails, including 90->105 A (largest
  diagonal changes about 10.192%, 9.692%, and 9.594% at 300/600/900 K); the
  105-A tensor is a rejected diagnostic only. No accepted kappa_L, remote
  summary, recomputation, or submission exists. See the linked compact evidence
  summary and read-only audit in the results index.
- `21934081` is historical and must remain untouched. Do not resubmit the
  whole original array merely because one element failed.

## Safe next action, when separately authorized

The user has confirmed sending the reviewed Roy status update. See
`EMAIL_TO_ROY_REVIEWED.md` for the conversational source and provenance.
Await Roy's scientific-priority guidance; no reply has been recorded.

No further scheduler polling is needed for this terminal chain. Rb progress now
requires a reviewed decision about denser q-mesh or broader convergence work;
the completed force array should not be rerun. SrZrS3 requires a scientific
decision about its sampled instability. Heavy calculations remain on DRAC and
need explicit execution authorization; a read-only status request alone does
not authorize them.
