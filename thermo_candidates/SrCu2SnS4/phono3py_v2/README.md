# SrCu2SnS4 phono3py v2 — local preparation boundary

This is a separate, **no-submit** preparation package for a corrected future
SrCu2SnS4 force campaign. It neither alters nor consumes the historical
`../phono3py/` raw records. In particular, its 4.0 angstrom pair cutoff is
passed to QE-mode phono3py as **7.5589045 bohr**, because generated QE YAML
uses `physical_unit.length: au`.

The historical 168-input campaign is not a reusable input set: it mixed a
90/720 Ry benchmark with 167 60/480 Ry calculations and used 4.0 bohr rather
than 4.0 angstrom. v2 fixes only the input-contract defect by requiring a
uniform 90/720 Ry, 3x3x3, fixed-occupation, `conv_thr=1d-09`, 96-atom QE
input for the pristine calculation and every displacement. These values are
repository-evidenced force settings, not newly demonstrated convergence.

## Safe workflow

1. Choose a new, non-existent `RUN_DIR` outside the repository. The preparer
   creates it exactly once; an existing directory, including an empty one, is
   rejected so that lineages cannot be reused.
2. Inspect the default-only plan (it creates nothing):

   ```bash
   python3 scripts/prepare_v2.py --run-dir /scratch/.../srcu-v2
   ```

3. Only after review, explicitly generate local displacement inputs with a
   verified phono3py installation and an absolute, real (non-symlink) pseudo
   directory containing all four configured regular pseudopotential files.
   The resolved `phono3py-init` executable, its hash, the semantic version
   written into the generated displacement YAML, the
   displacement YAML/supercell metadata, and pseudopotential hashes are locked
   into the run manifest. This action
   does not run QE or submit Slurm work:

   ```bash
   python3 scripts/prepare_v2.py --run-dir /scratch/.../srcu-v2 \
     --generate-displacements --pseudo-dir /path/to/SSSP/PBE/precision
   ```

4. The completed preparer output prints `run_manifest_sha256`. Retain that
   exact 64-character lowercase SHA-256 value outside mutable `RUN_DIR` in a
   separately reviewed record before any future QE evidence is accepted. A
   future, separately authorized pristine QE calculation must be audited before
   force work. The audit is bound to the exact pristine `scf.in`, its stdout,
   stderr, exit-code record, the shared `qe_output.py` parser, and that
   reviewed manifest anchor. Before copying evidence, the audit also requires
   the pristine input bytes and atom count to match the reviewed run manifest:

   ```bash
   python3 scripts/audit_pristine_v2.py --run-dir /scratch/.../srcu-v2 \
     --qe-output /scratch/.../pristine.out --qe-stderr /scratch/.../pristine.stderr \
     --exit-code /scratch/.../pristine.exit_code \
     --expected-manifest-sha256 <reviewed-preparer-output-digest>
   # Retain the audit's printed pristine_health_sha256 outside RUN_DIR.
   python3 scripts/preflight_v2.py --run-dir /scratch/.../srcu-v2 \
     --expected-manifest-sha256 <reviewed-preparer-output-digest> \
     --expected-health-sha256 <reviewed-audit-output-digest>
   ```

   Retain both digest values outside mutable `RUN_DIR`. Do **not** compute
   either flag from `RUN_DIR/run_manifest.json` or
   `RUN_DIR/health/pristine_health.json` at audit or preflight time: a mutable
   run directory can rebind its manifest, pseudo hashes, health record, and
   parser report, which defeats independent review. If either value was not
   retained or either file's bytes differ, stop and prepare/review a fresh
   lineage.

The pristine audit checks the reviewed input hash and the terminal health of
the supplied stdout, stderr, and exit-code files as separate facts. It cannot
prove those supplied logs were produced by executing that exact input. Both
the health record and preflight therefore state
`execution_provenance_verified: false`. Preflight remains a preparation gate;
it is neither an execution-provenance receipt nor scientific acceptance.

All records use exclusive creation: changing a source, setting, output, audit,
or manifest anchor requires a fresh `RUN_DIR`, not an overwritten fingerprint.
The audit rejects symlinked health/evidence destinations before it creates or
writes any health record. There are intentionally no Slurm templates in this
package.

Preflight rehashes the local phono3py dataset and pseudopotentials and checks
that every QE `ATOMIC_SPECIES` entry names exactly one configured pseudo file.
The run manifest also fingerprints `dataset_semantics.py`, and preflight
requires the same validator bytes before replaying the stored semantic report.
It also requires PyYAML (a phono3py runtime dependency) to re-prove the YAML
semantics; without that dependency it stops fail-closed rather than treating a
dataset hash as a physical cutoff check.

## Scientific boundary

Every generated force input explicitly sets `nosym=.true.` and `noinv=.true.`;
this is a uniform-input requirement, not a convergence result. No claim is
made here that the 2x2x1 supercell, 0.06-bohr amplitude, or 4.0-A
pair cutoff is converged. NAC and explicit SOC are absent; no q-mesh,
force-constant, or kappa calculation is prepared or released. A healthy
pristine audit is a terminal-output and complete-force-block requirement, not
a proof that the reviewed input produced the supplied output, and not a
scientific stability or convergence conclusion.
