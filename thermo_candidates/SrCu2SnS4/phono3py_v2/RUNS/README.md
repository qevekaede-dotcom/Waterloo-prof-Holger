# v2 run-directory boundary

Do not place a run in this repository by default. A v2 `RUN_DIR` must be a
new, non-existent, non-symlink directory chosen for one reviewed attempt
(normally a DRAC scratch path). `scripts/prepare_v2.py` refuses any existing
directory and
the scripts in this package never call `sbatch`, `ssh`, or QE themselves.

`RUNS/` is ignored so a local attempt cannot accidentally mix with the frozen
historical `phono3py/` record. No run directory has been initialized by this
package.
