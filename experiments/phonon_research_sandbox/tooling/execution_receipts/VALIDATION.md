# Validation record

Date: 2026-09-22

All validation was local and bounded. Test fixtures used temporary directories,
small text files, and the deterministic `examples/synthetic_worker.py`. No QE,
MPI, phono3py, force-constant fitting, kappa calculation, SSH, Slurm, or remote
operation was invoked.

## Commands and observed results

Syntax compilation:

```bash
python3 -m py_compile \
  experiments/phonon_research_sandbox/tooling/execution_receipts/execution_receipt.py \
  experiments/phonon_research_sandbox/tooling/execution_receipts/examples/synthetic_worker.py \
  experiments/phonon_research_sandbox/tooling/execution_receipts/tests/test_execution_receipt.py
```

Observed result: exit code 0; no output.

Bounded regression suite:

```bash
python3 -m unittest discover \
  -s experiments/phonon_research_sandbox/tooling/execution_receipts/tests \
  -v
```

Observed result: `Ran 11 tests in 1.438s` and `OK`. The cases cover:

1. default dry run creates no run or anchor;
2. successful stdin delivery, snapshot equality, and external-anchor verify;
3. stale/reused run identity cannot overwrite evidence;
4. mutable input and pseudopotential drift are distinguished;
5. nonzero exit remains complete evidence but is not execution success;
6. altered stdout is rejected;
7. a swapped receipt fails against the retained anchor;
8. symlinked source or evidence is rejected;
9. missing completion is reported as incomplete;
10. child environment is explicit, allowlisted, and minimal;
11. declared command-file drift is distinguished.

The successful verification case additionally proves that a copied anchor
inside the run directory is rejected even when its bytes match the external
anchor.

Tracked example JSON syntax:

```bash
python3 -m json.tool \
  experiments/phonon_research_sandbox/tooling/execution_receipts/examples/SYNTHETIC_PLAN.json \
  >/dev/null
python3 -m json.tool \
  experiments/phonon_research_sandbox/tooling/execution_receipts/examples/SYNTHETIC_VERIFICATION.json \
  >/dev/null
```

Observed result: both commands exited 0 with no retained output.

## Scientific-rigor review

This prototype generated no scientific quantities and changed no existing
input, output, raw record, result, or frozen package. It traces only synthetic
process bytes and metadata. Therefore there are no calculated values, units,
materials claims, convergence claims, or kappa results to validate.

Passing this suite does not establish a production execution provenance gate.
It does not change the existing v2 `execution_provenance_verified=false`
status, release a QE run, or satisfy terminal-health, numerical-convergence,
or scientific-acceptance requirements. The remaining security and provenance
limits are stated in `README.md`, including untrusted-host and coordinated
tampering limits, time-of-check/time-of-use windows, incomplete dependency
enumeration, parent-path rebinding, and the absence of QE/MPI/scheduler
integration.
