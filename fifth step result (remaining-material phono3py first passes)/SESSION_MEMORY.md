# Session memory

## Continuation state

- This package is an index, not an attachment package and not a new source of
  truth. Read the linked material records before changing a scientific status.
- SrZrS3 has complete force-accounting and structurally valid FC2/FC3 arrays,
  but its non-NAC 12x5x3 frequency gate failed. It remains
  `first_pass_unconverged`; no valid kappa_L or zT combination may be claimed.
- Rb2Cu2SnS4 has passed its upstream FIRE/pristine/preflight/pilot gates.
  Original production element 361 was recovered; element 462 failed at QE
  module start-up. Recovery `22312416` and dependent postprocess `22312417`
  are only known here as submitted and queued. Do not infer execution or
  scientific success from those job IDs.
- `21934081` is historical and must remain untouched. Do not resubmit the
  whole original array merely because one element failed.

## Safe next evidence check, when separately authorized

Use a bounded, read-only DRAC scheduler-and-artifact check. Establish the
terminal scheduler state and strict force audit before discussing FC2/FC3 or
kappa_L. If authentication fails, record the state as unverified and stop;
do not retry repeatedly.
