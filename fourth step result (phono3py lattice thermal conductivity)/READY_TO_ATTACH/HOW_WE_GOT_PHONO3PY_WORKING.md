# How we got phono3py working (QE + DRAC/Nibi), and every trap on the way

This is the write-up promised for the phonon task: a working recipe for
third-order force constants and lattice thermal conductivity with phono3py
on top of Quantum ESPRESSO, plus every failure we hit and how each one was
diagnosed and fixed. All scripts referenced here are in the public repo
(https://github.com/qevekaede-dotcom/Waterloo-prof-Holger under
`thermo_candidates/SrCu2SnS4/phono3py/scripts/`), and the cluster guide is
`DRAC_SETUP.md` at the repo root.

## 1. What actually runs, in one page

Material: SrCu2SnS4, relaxed P3_121 structure from our earlier first pass.

1. **Displacement generation (any machine).** phono3py 4.x, QE interface:
   `phono3py-init --qe -c unitcell.in --dim 2 2 1 --cutoff-pair 4.0
   --tolerance 1e-3` -> 168 displaced 96-atom supercells (out of 13,848
   without the pair cutoff).
2. **Force campaign (cluster, three chained SLURM jobs).**
   - stage 0: on-machine force-convergence checks against a 90/720 Ry,
     3x3x3 benchmark (accept a cheaper setting only if every force
     component agrees within 5e-5 Ry/bohr), then input generation at the
     decided settings. For us: the 2x2x2 k-mesh FAILED the criterion
     (max |dF| = 1.6e-4) so 3x3x3 was kept; 60/480 Ry PASSED
     (max |dF| = 5.2e-6) and was used.
   - stage 1: a 168-task SLURM array, one pw.x force SCF per displacement,
     with health checks and one automatic retry. About 44 min per
     calculation on 32 cores.
   - stage 2: gate on all 168 healthy, then FORCES_FC3, fc2/fc3, a q-mesh
     ladder at 300 K, and kappa_L(300-900 K) tables. Runs in a Python
     virtual environment holding phono3py 4.x (see trap 6).
3. **Cost.** Roughly 4,000 CPU-core-hours on Nibi under the group
   allocation; about a day of wall time end to end now that the pipeline
   works.

The installation of phonopy/phono3py itself (pip, on macOS and on WSL) was
the easy part. Every real problem was elsewhere.

## 2. The traps, in the order we hit them

**Trap 1 — phono3py 4.x moved its setup commands.** Symptom: commands from
older tutorials (`phono3py -d ...`, `phono3py --cf3 ...`) do nothing or
error; it looks like a broken install. Cause: in the 4.x series all
dataset-creation commands live in a separate `phono3py-init` executable.
Fix: use `phono3py-init` for displacement generation and force collection;
`phono3py` itself only runs the transport calculations. (If an attempt to
use phono3py "did not run", this plus trap 2 are the most likely reasons.)

**Trap 2 — silent symmetry collapse to P1.** Symptom: phono3py wants tens
of thousands of displacements (83k for us) instead of a few hundred.
Cause: coordinates written with 6 decimals do not satisfy the default
symmetry tolerance, so the P3_121 cell is read as P1. Fix: pass
`--tolerance 1e-3` everywhere (generation and postprocessing). Result:
168 displacements, space group correctly recognized.

**Trap 3 — cluster login "connection closed" that looks like a key
problem.** Symptom: SSH key freshly registered in CCDB, yet Nibi closes
the connection right after "Success. Logging you in...", and Narval loops
Duo. Cause: since fall 2025 each Alliance cluster must be individually
activated at ccdb.alliancecan.ca/me/access_systems (four agreement
questions). Neither the key nor Duo was ever the problem. Fix: activate
the cluster on that page; login works immediately afterwards.

**Trap 4 — Nibi SLURM specifics.** Two failed submissions to learn:
(a) Nibi has no default partition — CPU jobs up to 12 h go to
`cpubase_bycore_b2`; (b) accounts are split by resource, so the allocation
must be charged as `def-<PI>_cpu`, not `def-<PI>`.

**Trap 5 — MPI+OpenMP oversubscription: QE ~10x slower than it should
be.** Symptom: a force SCF that should take under an hour is still on
iteration 7 after ten hours; the job dies on its time limit, and every
job chained behind it waits forever (`DependencyNeverSatisfied`). The
tell-tale line in the QE output: "Parallel version (MPI & OpenMP), running
on 352 processor cores" against a 32-core request. Cause: the Alliance QE
module is a hybrid MPI+OpenMP build; with no thread cap, each of the 32
MPI ranks spawned ~11 OpenMP threads onto the same 32 cores. Fix: `export
OMP_NUM_THREADS=1` in the environment every batch script sources. After
the fix the same stage finished in under 3 h.

**Trap 6 — getting phono3py 4.x onto the cluster at all.** Three layers:
(a) the Alliance wheelhouse pins `pip install phono3py` to 3.25, which
predates `phono3py-init` and cannot read a 4.x dataset; (b) bypassing the
wheelhouse config reaches PyPI, but the Alliance Python vetoes PyPI's
prebuilt Linux binary wheels, forcing source builds — and the 4.3.3 source
package is rejected by current build tooling (scikit-build-core >= 0.10
renamed a key its config still uses), while the dependency chain then
tries to compile scipy from source and dies looking for OpenBLAS. Fix
(zero compilation): shadow the wheel veto for the install command only —
write a permissive `_manylinux.py` into a scratch folder, put that folder
on PYTHONPATH, and `pip install phono3py==4.4.0`; everything then arrives
as prebuilt wheels. Exact commands: `DRAC_SETUP.md`, section 3. Version
note: our displacement dataset was generated with 4.3.3; 4.4.0 was
verified beforehand to read that exact dataset identically.

**Trap 7 — QE "lone vector": a deterministic crash on a specific subset
of displacements.** Symptom: out of 168 force runs, 24 die within ~20
seconds, always right after the memory-estimate printout, always the same
MPI ranks, on many different nodes — and the failed displacement IDs are
regularly spaced, exactly one inside each block of paired displacements.
The CRASH file says `sym_rho_init_shell: lone vector`. Cause: in each
pair block exactly one displacement combination *preserves* a symmetry
operation (visible as fewer irreducible k-points: 10 vs 14); for those
configurations QE's charge-symmetrization setup fails when G-vector
symmetry shells are split across the 32-rank parallel distribution. The
undisplaced (full-symmetry) check cell trips the same bug. Fix: add
`nosym = .true., noinv = .true.` to exactly those inputs and rerun them.
Physics is unchanged — symmetry there is only a shortcut in the k-point
sum; the full mesh is then sampled explicitly at the same cutoffs and
convergence threshold (~2x cost on the affected runs). phono3py applies
its own symmetrization to the force constants afterwards.

## 3. Process rules that saved us (learned the hard way)

- **Check `sacct` within a day of submitting.** A chained pipeline dies
  silently: if stage 0 hits its time limit, every dependent job shows
  `DependencyNeverSatisfied` forever. Our first submission sat dead for
  more than two weeks before anyone looked.
- **Snapshot failures before rerunning.** A rerun overwrites the failed
  run's output and CRASH files in place. `scripts/slurm/collect_evidence.sh`
  copies every unhealthy run's files into a timestamped folder first.
- **Per-machine convergence checks, not copied parameters.** The stage-0
  force checks re-decide the k-mesh and cutoffs on the cluster itself; for
  us they rejected the cheaper k-mesh and accepted the cheaper cutoffs —
  the opposite of guessing.
- **One phono3py version family end to end** for dataset generation and
  force collection, with any substitution verified against the actual
  dataset before use.

## 4. Validation attached to the result

- All 168 force runs pass three health checks (JOB DONE, SCF convergence,
  forces present) at conv_thr 1e-9.
- The kappa tensor obeys the trigonal symmetry (kappa_xx = kappa_yy;
  off-diagonal components ~1e-8) and the derived tables were re-checked
  against the raw phono3py HDF5 output.
- Minimum phonon frequency on the final mesh: -2e-6 THz, i.e. zero to
  numerical precision — no imaginary modes, so the relaxed structure is
  dynamically stable at this level of theory.
- Known open point, stated rather than hidden: the q-mesh ladder at 300 K
  (7,7,3 -> 15,15,7) still moves ~5% between the last steps instead of
  settling below our 3% target, so the reported numbers carry a ~5%
  q-mesh uncertainty and use the largest mesh.
