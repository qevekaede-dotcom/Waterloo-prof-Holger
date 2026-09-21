# Local execution-receipt prototype

This directory contains a standalone, stdlib-only prototype for binding one
local process execution to reviewed input bytes. It is deliberately not wired
into `phono3py_v2`, does not release QE or Slurm execution, and does not change
`execution_provenance_verified=false` anywhere in the existing workflow.

The recorder defaults to a non-mutating dry run. `--execute` is required to
start a process. The only included executable example is a deterministic
`SYNTHETIC` Python worker; it never imports or runs QE, phono3py, force-constant
fitting, or a kappa calculation.

## What it records

Before launch, the recorder creates a fresh UUID-named run directory and
records:

- SHA-256 of the exact input bytes, each named pseudopotential, the recorder,
  the executable, and explicitly named command files;
- the exact argv, working directory, UTC start time, and a small explicit
  allowlist of non-secret environment variables;
- an exact `stdin.snapshot`. The same in-memory bytes that were hashed and
  snapshotted are passed by the recorder to the child process on standard
  input. This binds the recorded input hash to the bytes offered on that
  recorded child process's stdin; it does not establish semantic consumption.

After the child exits, it records UTC end time, elapsed time, process exit
code, stdout/stderr hashes, and any immediately observed drift in the external
input, pseudopotential, executable, recorder, or named command files. The
launch, completion, streams, snapshot, and final receipt use exclusive
creation. A reused run UUID or pre-existing anchor fails closed.

The final receipt SHA-256 is written to a separate anchor directory after the
process and receipt are complete. This is an independently retained final
digest, not a pre-launch external timestamp or precommitted launch record.
Complete verification requires that anchor outside the run directory. It
rejects receipt swaps, output changes, source drift, symlinks, identity
mismatches, and noncanonical evidence mappings. A nonzero exit is
distinguished from corrupt evidence: it produces `verified_nonzero_exit` with
`integrity_ok=true` and `execution_succeeded=false`. A launch without
completion is `incomplete`.

## Bounded synthetic use

Use temporary directories and an absolute Python executable. The UUID must be
a fresh lowercase RFC 4122 version-4 value. The following is a shape example;
replace every angle-bracket placeholder locally:

```bash
python3 execution_receipt.py record \
  --run-root <absolute-temp-runs> \
  --anchor-dir <absolute-separate-temp-anchors> \
  --run-id <fresh-uuid4> \
  --input <absolute-synthetic-input> \
  --pseudo Synthetic=<absolute-synthetic-pseudo> \
  --command-file synthetic_worker=<absolute-path>/examples/synthetic_worker.py \
  --cwd <absolute-temp-workdir> \
  --env OMP_NUM_THREADS=1 \
  -- <absolute-python> <absolute-path>/examples/synthetic_worker.py
```

That command only prints the plan. Add `--execute` before `--` to run the
synthetic worker and create evidence. Then verify with the external anchor:

```bash
python3 execution_receipt.py verify \
  --run-dir <absolute-temp-runs>/<fresh-uuid4> \
  --anchor-file <absolute-separate-temp-anchors>/<fresh-uuid4>.anchor.json
```

Allowed environment keys are `LANG`, `LC_ALL`, `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and
`VECLIB_MAXIMUM_THREADS`. The child receives only the explicitly supplied
subset. Extending this allowlist for a future reviewed runner requires code
review; the prototype never captures the caller's full environment.

## Threat model and limits

This prototype detects accidental corruption, stale or mixed run directories,
source changes, swapped receipts, and incomplete local executions. It is not
adversarial attestation. The same local user or a privileged actor can alter
the process, recorder, source files, clock, kernel behavior, run directory,
and external anchor together. SHA-256 chains expose mismatches only when at
least one trusted copy or digest remains independent; they do not prove who
ran a command, what code the operating system actually executed, or that an
uncompromised host produced the evidence.

There is still a narrow time-of-check/time-of-use window for external
pseudopotentials, command files, and the executable. Pre-launch, immediate
post-run, and verification-time hashes detect persistent drift, but cannot
prove a file was never temporarily swapped and restored during execution.
The exact input is stronger because recorder-owned bytes are streamed to
stdin. The receipt proves delivery to the operating-system process interface,
not that the program read every byte or interpreted it as intended. Named
pseudopotentials and command files are declared tracked dependencies. Their
hashes do not prove the child opened or used them, and the recorder cannot show
that the declared list contains every transitive library or data dependency.

Symlink checks cover the explicitly controlled files and the run tree. They do
not establish that every ancestor directory is immutable or free of symlink or
mount rebinding, and the prototype has no race-resistant directory-fd/openat
implementation. There is no MPI, scheduler, container, remote-host, or QE
integration in this directory.

The receipt records an exact working-directory path because the execution
contract requires it. Real receipts can therefore contain host paths and must
be stored according to project privacy rules. The tracked `SYNTHETIC` example
JSON uses placeholders and contains no machine identity, private path, or full
environment.

Passing receipt verification establishes only the integrity and linkage of
this local evidence under the stated accidental-error model. It does not show
QE terminal health, SCF convergence, force completeness, numerical
convergence, physical validity, scheduler completion, or accepted lattice
thermal conductivity. Any future QE adaptation still needs independent code
review and integration with the existing parser and scientific gates.

See [VALIDATION.md](VALIDATION.md) for the exact bounded test command and
result.
