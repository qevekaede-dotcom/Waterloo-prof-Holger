# Frozen 3.70-angstrom count-only evidence

This directory preserves the five raw files independently copied from the
read-only audit staging directory `/tmp/srzrs3-preflight-evidence.YNYbe0`.
Their bytes and SHA-256 values match that staging source. The original remote
provenance root was
`/scratch/yuhansun/phono3py-runs/20260911-continuation-4e9b64c/SrZrS3/slurm_attempts/preflight/20260911T125726Z-preflight-e054b797`.

The two candidate YAMLs and preflight results are count-only evidence. Both
2x1x1 and 3x1x1 at 3.70 angstrom generated 1003 displacement supercells,
above the campaign hard cap of 800. Nothing in this directory is production
FC3 acceptance evidence. `campaign.json` binds the 3.5541348625-angstrom
prediction to the versioned 2x1x1 YAML and inventory by repository-relative
path and SHA-256.

`SHA256SUMS` covers only the five byte-preserved source artifacts. The
machine-readable `manifest.json` records their sizes, hashes, and provenance.
