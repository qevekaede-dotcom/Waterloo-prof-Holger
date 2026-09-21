# v2 preparation work log

## 2026-09-20 — corrected local preparation boundary

- Created a separate v2 plan only; no SSH, Slurm submission, QE, or phono3py
  calculation was run.
- Locked the intended 4.0 angstrom pair cutoff to 7.5589045 bohr for QE-mode
  phono3py and retained the historical 2x2x1 matrix and 0.06-bohr amplitude
  only as unvalidated starting parameters.
- Required a new empty run directory, a uniform 90/720-Ry QE input contract,
  a pristine terminal-health audit, at least 168 displacement inputs, and
  exclusive-write SHA-256 fingerprints before preflight can pass.

## 2026-09-20 — coordinator safety review corrections

- Corrected the phono3py generation argument from `inputs/unitcell.in` to
  `unitcell.in` because generation runs with `inputs/` as its working directory.
- Added explicit uniform `nosym=.true.` and `noinv=.true.` requirements.
- Generation now rejects non-absolute, symlinked, missing, or non-regular
  pseudopotentials and records all four pseudopotential SHA-256 values.
- Replaced the local pristine parser with the shared campaign `inspect_force_run`
  contract and made stdout, stderr, exit-code, parser, and input fingerprints
  mandatory evidence. No calculations or submissions were run.

## 2026-09-20 — provenance hardening review

- Added the resolved executable path and hash, and bound the semantic phono3py
  version written into the generated displacement YAML to the future run
  manifest. The unsupported `phono3py-init --version` probe is not used.
- Added hashes for `unitcell.in`, `supercell.in`, and `phono3py_disp.yaml`;
  preflight rehashes all three rather than relying on a manifest alone.
- Preflight now rehashes the live pseudopotential files at the stored absolute
  directory and checks every QE input's `ATOMIC_SPECIES` filenames.
- Bound the pristine health record to its document type, exact current shared
  parser hash, and explicit zero process exit code. No calculations or
  submissions were run.

## 2026-09-20 — semantic and health-evidence hardening

- Added a fail-closed PyYAML semantic gate for the generated QE displacement
  YAML and fragment IDs; it checks units, matrix, atom counts, amplitude,
  cutoff inclusion, a nonzero included pair, and exact ID/fragment bijection.
- Health evidence is copied into `RUN_DIR/health/evidence/`; future preflight
  rejects symlinks, rehashes and replays the shared parser rather than trusting
  a claimed health JSON. No calculations or submissions were run.

## 2026-09-20 — adversarial boundary tests

- Added explicit rejection tests for unit, matrix, amplitude, cutoff flags,
  displacement IDs, forged parser replay, run/evidence symlinks, pseudo path,
  and element-to-pseudopotential mapping mutations.
- The preparer now rejects a dangling `RUN_DIR` symlink before resolving the
  path, so dry-run or generation cannot silently operate on its target.
- These are hermetic fixture tests. No real displacement generation, QE run,
  SSH session, or Slurm submission was performed.

## 2026-09-20 — independent manifest-anchor hardening

- The completed preparer now prints the exact SHA-256 of the finished
  `run_manifest.json`. Pristine audit and preflight both require this digest as
  an explicit, strict lowercase-hex argument from separately retained/reviewed
  preparer output; neither command may derive it from mutable `RUN_DIR` data.
- The pristine health record carries that anchor, and preflight compares the
  exact manifest bytes and health anchor before trusting dataset or
  pseudopotential fingerprints. A pseudo mutation plus an in-run manifest
  rebind therefore still fails against the original reviewed digest.
- Preflight now directly parses retained `health/evidence/pristine.exit_code`,
  requires one non-negative integer, equality to the health record, and zero.
- The audit now rejects a symlink in `RUN_DIR/health` or
  `RUN_DIR/health/evidence` before any directory creation or evidence write;
  an adversarial fixture proves an external symlink target remains untouched.
- These hardening changes were tested locally only. No SSH, Slurm submission,
  QE, phono3py calculation, or scientific-result change occurred.

## 2026-09-20 — independent pristine-health-anchor hardening

- The audit now prints the SHA-256 of the exact final
  `health/pristine_health.json`; preflight requires that separate, strict
  lowercase-hex anchor before parsing or trusting any health-record field.
  Its report records both the reviewed manifest and pristine-health anchors.
- Health evidence paths are now an exact canonical mapping to the three copied
  files in `health/evidence/`; relative escapes and alternate in-run paths are
  rejected even if an attacker supplies a recomputed health digest.
- The documented workflow requires retaining both preparer and audit digests
  outside mutable `RUN_DIR`; recomputing either from a changed run directory is
  explicitly forbidden.
- Adversarial local fixtures cover a copied-stdout plus rebinding attack under
  the original health anchor and canonical-path bypass attempts. No SSH, Slurm
  submission, QE, phono3py calculation, or scientific-result change occurred.

## 2026-09-21 — pristine binding and validator provenance repair

- The pristine audit now verifies the exact `forces/pristine/scf.in` digest
  against the externally anchored run manifest and requires the configured
  96-atom contract before it creates or copies any health evidence. Previously,
  a changed input could receive a locally healthy audit record and fail only at
  the later preflight.
- Preparation now records the SHA-256 of the imported
  `dataset_semantics.py` validator, and preflight requires that exact validator
  before replaying dataset semantics. The preparer hash alone did not bind this
  imported acceptance dependency.
- The shared QE output inspector now rejects fatal signatures in the final
  PWSCF stdout even after a complete force block and `JOB DONE`. Focused parser,
  archived-evidence, and v2 tests passed. No historical script or raw result was
  changed, and no QE, phono3py postprocessing, SSH, or Slurm action was run.

## 2026-09-21 — execution-provenance limitation correction

- Independent review identified that binding the pristine input hash and
  auditing caller-supplied stdout, stderr, and exit-code files do not prove the
  logs were produced by executing that exact input. The existing `healthy`
  field remains limited to terminal parser status for the supplied evidence.
- Pristine health and preflight reports now state
  `execution_provenance_verified: false` and carry an explicit plain-language
  audit scope. Preflight remains preparation-only and does not establish
  execution provenance or scientific acceptance.
- A future trusted-runner receipt protocol is documented in the sandbox
  tooling report as a plan only. No execution wrapper, submission path, QE run,
  postprocessing, SSH session, or Slurm action was implemented or performed.
