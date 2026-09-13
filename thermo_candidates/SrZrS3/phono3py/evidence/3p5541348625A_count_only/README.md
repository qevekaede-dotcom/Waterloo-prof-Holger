# Verified 3.5541348625-angstrom count-only evidence

This directory freezes the targeted SrZrS3 count-only preflight for
`sr_fc3_2x1x1__sr_cutoff_3p5541348625A`. The run used repository commit
`5733f0cc486fa806ca2f6a1a653cd21541f70403`, submission attempt
`20260913T144259Z-preflight-2f0ab287`, and Nibi job `21850149`.

The result reproduced the predicted inventory exactly: 787 generated QE
inputs, comprising 25 single displacements and 762 second-displacement IDs in
147 included pair groups, 122 of them nonzero. The generated YAML records
`physical_unit.length = au`, the 2x1x1 supercell has 40 atoms, and the runtime
count/shell/multiplicity audit passed with no mismatches. The scheduler receipt
records `COMPLETED`, exit `0:0`, and 10 seconds elapsed; the wrapper and
`phono3py-init` process also returned zero.

This is only a count and geometry result. The targeted subset completed, but
the full configured preflight did not; the candidate remains
`selection_eligible = false`. In particular, falling below the 800-file cap
does not validate the 3.5541348625-angstrom interaction cutoff or the 2x1x1
finite-size choice, and it does not authorize any force pilot or production
array. The cutoff consumes about 92.6% of the inscribed-sphere radius, leaving
only 0.2843 angstrom of clearance, so finite-size testing remains necessary.

`SHA256SUMS` covers the 30 byte-preserved run/submission/result files plus the
later read-only `sacct` receipt. The 787 generated `supercell-*.in` files are
not duplicated in Git; `generated_inputs.SHA256SUMS` records every basename
and byte hash from the checksum-verified audit copy. The YAML, result, and
inventory retain the displacement IDs and scientific inventory. See
`manifest.json` for all provenance anchors and explicit scope gates.

One provenance limitation is retained rather than hidden: `context.tsv` left
its `git_commit` field blank. The full commit identity is instead bound by the
run manifest together with the exact configuration and workflow hashes.
