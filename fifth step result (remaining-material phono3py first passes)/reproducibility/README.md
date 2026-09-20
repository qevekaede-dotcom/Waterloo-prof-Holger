# Reproducibility index

This package intentionally links to the authoritative versioned sources rather
than duplicating run trees or large artifacts. Heavy QE and phono3py work is
performed on DRAC compute nodes; a local checkout is for inspection,
preparation, and lightweight validation.

## SrZrS3

- [Campaign record](../../thermo_candidates/SrZrS3/phono3py/README.md)
- [First-pass force audit script](../../thermo_candidates/SrZrS3/phono3py/scripts/audit_firstpass_forces.py)
- [First-pass postprocess script](../../thermo_candidates/SrZrS3/phono3py/scripts/postprocess_firstpass.py)
- [Immutable lightweight evidence and remote artifact hashes](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/README.md)

The reported 12x5x3 non-NAC command, input assumptions, remote run root, and
force/FC integrity checks are recorded in that evidence README. Its rejected
status is part of the reproduction result, not an optional interpretation.

## Rb2Cu2SnS4

- [Campaign configuration](../../thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json)
- [Force-output audit program](../../thermo_candidates/Rb2Cu2SnS4/phono3py/audit_force_firstpass.py)
- [Curated provenance, manifests, and historical job-ID files](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/README.md)
- [Shared submission and postprocess implementation](../../thermo_candidates/scripts/phono3py_campaign/README.md)

The current narrow recovery is not reproducible from this index alone because
its immutable DRAC attempt evidence is still live/pending. First obtain a
terminal scheduler record and audit it; do not repurpose the old `21934081`
postprocess or resubmit the full array.
