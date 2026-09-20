# Results index

## SrZrS3: rejected diagnostic, not a result

The 788-force dataset and FC2/FC3 integrity checks passed, but the explicit
non-NAC RTA mesh `(12, 5, 3)` has a minimum frequency of
`-1.0716026422440281 THz` at `[0.0, 0.4, 0.0]`; 12 sampled modes are below
`-0.1 THz`. The status is therefore `first_pass_unconverged` and no denser mesh
was run. The finite conductivity tensor is retained only as a rejected
diagnostic: [CSV](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/kappa_m1253_rejected_diagnostic.csv) and [audit](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json).

It must not be presented as kappa_L or combined with electronic transport to
report thermoelectric zT.

## Rb2Cu2SnS4: no phonon result yet

There is no accepted FC2, FC3, q-mesh calculation, or kappa_L file. The
historical force-production evidence is [here](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/README.md). The new narrow
recovery and dependent postprocess are queued only, so they are not results.
