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

## Rb2Cu2SnS4: numerical artifacts, but no accepted phonon result

Saved evidence records recovery `22312416` as `COMPLETED/0:0`. Its dependent
wrapper `22312417` is `FAILED/1:0`, solely at the final scan because its
wrapper expects `force_constants` while the FC3 file stores the `fc3` key. The
saved read-only HDF5 audit passes FC2/FC3 file integrity, shapes, finite values,
maps, phono3py version, and 18-primitive/72-supercell atom binding; its
harmonic and off-diagonal gates also pass. These are limited numerical and
binding checks, not scientific force-constant validation or proof of full
phonon stability.
The terminal capture directly retains only the 105-A q-mesh zero exit; earlier
sequential-stage execution is control-flow-implied, while the audit directly
reads the resulting saved HDF5 artifacts.

The audit evaluates all four q-mesh transitions and rejects each one. For the
final 90->105-A transition, trace/3 changes are 4.2663%, 4.0831%, and 4.04694%
and the maximum diagonal changes are about 10.192%, 9.692%, and 9.594% at 300,
600, and 900 K. Thus the 105-A tensor is a rejected diagnostic only. There is
no `kappa_summary.json` or `kappa_L_first_pass.csv`, no accepted kappa_L, and
no zT combination. The local finalizer was repaired to return nonzero and use
an explicitly rejected-diagnostic CSV name when any gate fails; it has not
been run remotely, and no recomputation/submission occurred. See the [source evidence](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_failure_evidence_20260920.txt), [read-only audit](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json), and [machine-readable synthesis](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_evidence_summary_20260920.json).
