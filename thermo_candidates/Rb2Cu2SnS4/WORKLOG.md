# Work log: Rb2Cu2SnS4 first-pass workflow

Lab-notebook record for this material. Newest entry at the bottom.

---

## 2026-07-02 — starter inputs and cutoff convergence launched

**Context.** Third candidate in the queue (rank 1 in the renewed list);
started after the SrZrS3 first pass completed so the machine runs one heavy
job at a time.

**1. Structure.** `structures/Rb2Cu2SnS4.cif` = mp-18006, Ibam, given as the
18-atom primitive cell (Rb4 Cu4 Sn2 S8; a=b=c=9.49 A with non-orthogonal
angles). Reciprocal-lattice lengths 0.70/1.23/1.26 A^-1, so balanced k-meshes
need roughly half as many points along the first axis.

**2. Starter inputs** were generated earlier with the sanctioned
`scripts/make_qe_inputs.py`. Pseudos are mixed: Rb norm-conserving ONCV,
Cu PAW, Sn/S ultrasoft - dual 8 (ecutrho = 8 x ecutwfc) is required by the
PAW/ultrasoft members.

**3. Cutoff test design** (own test): 50-100 Ry against the 100 Ry
reference (SSSP suggests 90/720, Cu-driven, same situation as SrCu2SnS4);
fixed 2x4x4 mesh (spacing 0.35/0.31/0.32 A^-1), fixed occupations,
conv_thr 1e-8, stress printed. Series launched in the background.

**Next.** Extract `cutoff_results.csv`, select the cutoff, then the k-point
test (mesh list scaled to the reciprocal shape), vc-relax, final SCF, dense
NSCF, and BoltzTraP2 on the same 300-900 K / 1e19-1e21 cm^-3 grid.

---

## 2026-07-02 — cutoff result; k-point test launched

**1. Cutoff result.** All six runs JOB DONE. Deltas vs the 100 Ry reference:
80 -> 0.509, **90 -> 0.0896**, meV/atom; pressure plateau 2.5-2.7 kbar from
60 Ry. **Selected 90/720 Ry** - essentially the same convergence point as
SrCu2SnS4 (0.104 meV/atom at 90 Ry), which is physically expected since the
same hard Cu PAW pseudopotential dominates both materials. Record:
`qe/convergence/cutoff_results.csv`.

**2. Runtime anomaly investigated, physics clean.** ecut_80 showed 1h56m
wall but only 8m27s CPU (ecut_90: 1h37m wall, 17m26s CPU) while all six runs
took a uniform 17-18 SCF iterations. The wall/CPU gap means the laptop was
suspended or heavily loaded during those runs, not that the SCF struggled -
the energy-vs-cutoff curve is smooth and fixed occupations converged
normally everywhere.

**3. k-point test launched** at 90/720 Ry: meshes 2x4x4, 3x5x5, 4x7x7,
5x9x9 (reference), scaled to the reciprocal ratios ~1:1.76:1.81 so the
spacing stays balanced. Extraction mirrors the standard CSV format.

**Next.** Choose relax + final-SCF meshes, then vc-relax onward.

---

## 2026-07-02 — k-point series re-parallelized (4 -> 12 ranks)

The overnight runs were heavily throttled (laptop sleep + background
scheduling): k_2x4x4 took 3.3 h and k_3x5x5 6.0 h wall, versus ~17 min CPU
for the same-size run in the daytime cutoff test. SCF iteration counts were
uniform (17-18) - a machine effect, not a physics problem.

With the user's go-ahead (M5 Pro, 18-core CPU, 24 GB unified memory), the
running k_4x7x7 was stopped and the series relaunched with
`QE_NP=12 QE_NK=2` (2 k-point pools x 6-way plane-wave parallel) wrapped in
`caffeinate -i` to block idle sleep for the duration of the job. Pool count
was capped at 2 because pools replicate memory: the 4-rank single-pool run
used ~6.8 GB total, so 4 pools would have exceeded 24 GB, while 2 pools sit
around 10-14 GB. Completed meshes were skipped by the run script; k_4x7x7
restarted from scratch. `run_kpoint_convergence.sh` gained the same QE_NK
support the production scripts already had. Expected ~2.5-3x speedup.
(The 20-core GPU is unused: QE GPU acceleration is CUDA/NVIDIA-only.)

At 12 ranks the speedup was confirmed: k_4x7x7 finished in 2088 s and
k_5x9x9 in 4817 s.

---

## 2026-07-03 — k-point result; meshes chosen; vc-relax launched

**1. k-point result** (`qe/convergence/kpoint_results.csv`). Deltas vs the
5x9x9 (203 irreducible k) reference: 2x4x4 -> 0.175, 3x5x5 -> 0.016,
4x7x7 -> 0.0015 meV/atom. This material converges unusually fast with
k-points.

**2. Meshes chosen**, same protocol as the other two materials (relax mesh
inside the ~0.25 meV/atom band, final SCF one tier denser):
  - vc-relax: **2x4x4** (0.175 meV/atom; cf. SrCu2SnS4 0.253, SrZrS3 0.286)
  - final SCF: **3x5x5** (0.016 meV/atom)

**3. vc-relax launched** at 90/720 Ry + 2x4x4 from the mp-18006 primitive
cell (`prepare_relax.py` / `run_relax.sh`, thresholds as before:
etot 1e-5 Ry, force 1e-3 Ry/bohr, pressure 0.5 kbar, BFGS, cell_dofree all,
fixed occupations), 12 ranks / 2 pools under `caffeinate -i`;
log -> `logs/Rb2Cu2SnS4.relax.out`.

**Next.** Health checks (criteria met, symmetry still Ibam, sane volume
drift), extract relaxed CIF, final SCF at 3x5x5 (expect 156 electrons ->
78 occupied bands by pseudo arithmetic), dense NSCF, BoltzTraP2.

---

## 2026-07-03 — vc-relax complete; final SCF launched

**1. vc-relax result** (`logs/Rb2Cu2SnS4.relax.out`, 49m48s wall, 12 ranks):
BFGS converged in 8 steps / 9 SCF cycles; all three criteria met; final
pressure 0.07 kbar; final enthalpy -1568.2380702 Ry.

**2. Structure check** (extract_relaxed_structure.py, 10 frames): symmetry
**kept Ibam (#72)**; volume 446.410 -> 450.561 A^3 (**+0.93%**) - slightly
larger drift than SrCu2SnS4 (+0.48%) / SrZrS3 (+0.63%) but still normal for
PBE. Relaxed CIF -> `structures/Rb2Cu2SnS4.relaxed.cif`.

**3. Final SCF launched** at 90/720 Ry, 3x5x5, on the relaxed structure
(12 ranks / 2 pools, caffeinate). Density -> `qe/tmp/final/`.

**Next.** Verify 156 electrons / 78 occupied bands, size the dense NSCF
(nbnd ~105 with ~35% headroom; mesh matched to the ~0.08 A^-1 spacing
standard of the other two materials), then BoltzTraP2.

---

## 2026-07-03 — final SCF complete; dense NSCF launched

**1. Final SCF** (`logs/Rb2Cu2SnS4.scf.out`, 13m14s wall, 12 ranks): JOB
DONE; **156.00 electrons -> 78 occupied bands** (matches the pseudo valence
arithmetic 4x9 Rb + 4x11 Cu + 2x14 Sn + 8x6 S); 38 irreducible k-points at
3x5x5; highest occupied level 6.2203 eV; total energy -1568.23828522 Ry.

**2. Dense NSCF sizing** (reasoning in `qe/prepare_nscf.py`):
  - nbnd = **105** (78 occupied + 27 empty, ~35% headroom);
  - mesh = **8x14x14** -> spacing 0.088/0.088/0.090 A^-1, ~10% coarser than
    the 0.08 standard: in this primitive-cell orientation QE's automatic
    grids reduce only ~2x by symmetry, so matching 0.08 exactly (9x16x16,
    ~1150 irreducible points) would about double the cost for a marginal
    gain. Deviation stated here and covered by the standing
    transport-mesh-convergence caveat shared by all three materials.

**3. NSCF launched** (12 ranks / 2 pools, caffeinate, disk_io=nowf,
diago_full_acc). Expect ~780 irreducible points; the gap number comes from
this run.

**Next.** Read VBM/CBM/gap, fix-and-run the BoltzTraP2 template (same three
bugs expected as SrZrS3's), summarize, then the three-material comparison.

---

## 2026-07-03 — dense NSCF complete; BoltzTraP2 launched

**1. Dense NSCF** (`logs/Rb2Cu2SnS4.nscf.out`, 5h27m wall, 12 ranks / 2 pools):
JOB DONE; 788 irreducible k-points (8x14x14); 105 bands / 156 electrons;
VBM 6.2402 eV, CBM 7.0213 eV -> sampled PBE gap **0.7811 eV** - the largest
of the three candidates (SrCu2SnS4 0.3445, SrZrS3 0.6096).

**2. BoltzTraP2 template had the same three bugs as SrZrS3's** - fixed in
`boltztrap2/run_bt2.sh` before running: qe_source path missing `/final`; bare
`btp2` CLI (NumPy 2 crash) -> `btp2_compat.py` shim (copied); half-open
`300:900:100` range and through-zero `-1e21:1e21:1e20` doping -> `300:1000:100`
and the explicit 14-level list. The pre-made template ships with these bugs
for every material; this is now the second confirmation.

**3. BoltzTraP2 launched** (`BT2_NP=8`, caffeinate): interpolate -m 5 ->
integrate -> dope; `summarize_transport.py` adapted from the SrZrS3 version
(header identifiers/meshes swapped, transport math identical).

**Next.** Summarize -> `results/`; then update the three-material comparison
in `learning/05_comparing_materials.md`, `WORKFLOW_EXPLAINED.md` section 6,
`Roy_task_status.md`, and this material's README/CLAUDE.

---

## 2026-07-03 — Seebeck(mu) figure for the Roy report

`boltztrap2/plot_seebeck.py` cloned from the verified SrCu2SnS4 version
(gap shading 0.7811 eV, window +/-1.4 eV) -> `results/seebeck_vs_mu.png/.csv`.
Cross-checks: trace-vs-condtens diag average 1.72e-5; dope-vs-scan S at 300 K
p 1e20 cm^-3: 331.5 vs 331.6 uV/K. Honest flag: the charge-neutrality
interpolation residual at E_F is +0.211 e/uc (vs +0.005/+0.018 for the other
two) because the valence DOS is high and steep at the VBM (flat bands), so
N(mu) rises sharply within one mu-grid step; the dope-based check confirms the
S curves are unaffected. Curated copy in
`third step result (three-material first pass)/READY_TO_ATTACH/`.

---

## 2026-09-13 — one allowed BFGS polish failed; lineage is terminal

The force-consistency diagnostic in the fresh Nibi lineage
`/scratch/yuhansun/phono3py-runs/20260911-continuation-cf0b1d1/Rb2Cu2SnS4`
completed and passed its narrow release gate.  Primary job `21732222` and
collector `21732223` both completed `0:0`.  The duplicate-force RMS difference
was `1.9245008973e-09 Ry/bohr`; increasing ecutrho from 800 to 1000 Ry changed
the force vector by `3.5007935608e-07 Ry/bohr` RMS and `1.01e-06 Ry/bohr` at
the largest component.  This established fixed-geometry repeatability only;
it did not accept a structure.

Exactly one reviewed small-trust-radius BFGS polish was then submitted.  Its
primary job `21848175` is authoritatively `FAILED/2:0`; collector
`21848176` completed `0:0` and preserved the failure.  QE completed four SCF
cycles and printed `JOB DONE`, but also explicitly reported
`bfgs failed ... convergence not achieved`.  Total force decreased from
`6.6e-05` to `5.4e-05 Ry/bohr`, while the final maximum force component was
`1.37e-05 Ry/bohr`, still above the BFGS `1e-05 Ry/bohr` threshold.  Two
successive history resets followed sub-threshold natural steps of about
`2e-05 bohr`; no pristine SCF, execution manifest, relax gate, final unitcell,
or accepted structure was produced.  The collector receipt is incomplete by
design and has SHA-256
`d5b4e87c8c69dddb5f1ba484d0a6d2f2dc618be6ec55f8d3e7b8d4611f4d2c83`.

Independent scientific review therefore marked this unique polish as a
terminal **BLOCK**.  Low residual force and a zero QE process exit code do not
override failed BFGS convergence.  Do not add a second polish attempt to this
RUN_DIR, loosen thresholds after the fact, accept its last geometry, or release
preflight/force work from it.  A genuinely different relaxation protocol may
be designed and reviewed as a new lineage, but no such method is currently
approved for execution.

The same review exposed a provenance replay defect: diagnostic finalization
currently assumes that `slurm_attempts/collect/` contains only its own
collector, so replay after the later relax collector can fail for the wrong
reason.  Repair and independently review that code before using the diagnostic
lineage as evidence for any future method.  This is a software/evidence fix,
not authorization for another calculation.

---

## 2026-09-14 — replay-validator repair completed locally; remote lineage replay remains required

The diagnostic replay-validator defect has been repaired and locally validated.
The validator now binds the approved historical workflow snapshot `cf0b1d1`
through its full hash set, while treating the current config and policy as the
authority.  It requires a single historical checkout root, validates nested
collectors against their exact schema, rejects globally duplicated Slurm IDs,
and supports cross-checkout relocation.  Local tests and fresh reviews passed.

This is a software/provenance repair only.  The final commit has not yet been
used for a read-only replay of the real Nibi lineage, so it must not be claimed
as final remote lineage validation.  The terminal scientific block is unchanged:
`21848175` remains `FAILED/2:0`, `21848176` remains the completed collector of
that failed attempt, no structure is accepted, and no preflight, pilot, or
production force work is released.  The next permitted evidence action is the
final-commit read-only replay; a different relaxation method would still need a
new lineage and prior scientific review.

---

## 2026-09-14 — final-commit Nibi replay passed without changing the run

Exact clean checkout `824cbcf0c91bd8b4f9abcd8c53266dcecd2f3cc7` passed all
333 campaign tests in the Nibi phono3py environment.  The repaired validator
then read-only replayed the real diagnostic lineage and returned `PASS` while
retaining `structure_accepted=false` and `preflight_unlocked=false`.

The lineage contained 963 files both before and after the replay.  SHA-256
values for the final diagnostic gate, diagnostic provenance, polish lineage,
and run manifest were unchanged; no Slurm job was submitted.  This establishes
that the original diagnostic evidence can be replayed after the later failed
relax collector.  It does not change the BFGS failure, accept a structure, or
release any preflight, pilot, or production force work.

---

## 2026-09-14 — dedicated FIRE recovery reviewed plan, execute hard-locked

A separate, fail-closed `reviewed_fire_recovery` policy and `fire_recovery.py`
were added for a future reviewed FIRE-only recovery. It is explicitly not a
generalization of the failed BFGS polish. Preparation requires a new,
non-nested RUN_DIR and byte-identical copies of the old real lineage's
`polish_reference.in`, `one_reset_attempt/reference_unitcell.in`, and
`one_reset_run/recovery_reference.in`; it rejects `polish_seed.in`, failed
terminal geometry, symlinks, and source mismatch. The frozen reference remains
a seed rather than an accepted structure.

The planned pilot is 8 FIRE steps / 6300 s on 32 ranks for 2 h, and full is
100 FIRE steps / 39600 s on the same frozen seed for 12 h (384 core-hours).
QE 7.3.1 must print both `FIRE: convergence achieved in` and `End of FIRE
minimization`; `JOB DONE` alone remains invalid. The implementation rejects
BFGS trust controls and specifies the independent pristine gate, but it is
not an execution chain: public and internal `submit.py` execution paths and
the direct FIRE `run`/`finalize` CLI all hard-fail before `sbatch`. A manually
submitted FIRE wrapper exits only after its Slurm allocation starts, but before
any QE launch, scratch creation, or attempt creation. It keeps
`preflight_unlocked=false`; independent replay/review and any count-only
preflight release remain unimplemented, so cannot unlock force or production.

No source lineage was prepared, no new Slurm job was submitted, no QE calculation
was launched, and no scientific result was produced. Local validation passed
353 tests (one optional spglib test skipped), configuration validation,
Python compilation, shell syntax checks, and `git diff --check`. Production
budget and selections remain null/blocked.

---

## 2026-09-14 — clean Nibi replay prepared the plan-only FIRE lineage

Exact commit `aab9290a66cc63058584c04ad39a091ff5d13284` was checked out
cleanly at `/scratch/yuhansun/codex-verify-aab9290`.  The Nibi phono3py
environment passed all 353 tests, both material configurations validated, and
the checkout stayed clean.

The first evidence command stopped under `set -e` before preparation because
it requested the wrong historical provenance filename
`gate.provenance.json`; inspection showed the real file is `provenance.json`.
The intended new RUN_DIR was still absent and the queue was empty.  With the
corrected, inspected path, exact historical replay prepared
`/scratch/yuhansun/phono3py-runs/20260914-rb-fire-plan-aab9290/Rb2Cu2SnS4`.
The immutable receipt has SHA-256
`f1f4baabe1c4dee3da804eb60e14ba4cc8c23d7a33cf4914a2bcfe9a9b449e74`;
`fire_seed.in` retains the frozen reference SHA-256
`b2f919f7af04a0fd93400e2e5cd021bb489947e245e3d834694167bf2ded714f`.

The prepared lineage contains eight files, no symlinks, and no attempt or
submission files.  Its pilot plan is explicitly non-runnable:
`execution_released=false`, `primary_command_template=null`, and
`collector=false`.  The old run still contains 963 files, and all eight
rechecked gate/provenance/lineage/manifest/output/context hashes were identical
before and after.  `squeue` returned zero rows both times.  No `sbatch`, QE,
FIRE step, structure acceptance, or downstream release occurred.

---

## 2026-09-14 — bounded FIRE pilot chain implemented locally; pending review, no job

The plan-only FIRE design was advanced to a fail-closed implementation for one
eight-step pilot. Preparation now emits a new versioned lineage and a separate
immutable execution-release receipt that binds the exact Git commit, full and
canonical configuration hashes, FIRE policy, workflow file hashes, frozen
seed, one-attempt limit, 32-rank/two-hour allocation, and `afterany` collector.
The old `aab9290` plan-only RUN_DIR cannot execute after this workflow/schema
change; a fresh lineage is mandatory.

The pilot wrapper validates compute-node context, QE 7.3.1, actual scheduler
account/partition/node/rank/CPU/memory/time allocation, configuration, commit,
workflow, lineage, release receipt, unused attempt slot, and absent scratch
before `p3_begin_attempt`. It then generates and reparses the exact 100/800-Ry,
4x7x7 fixed-occupation FIRE input (`conv_thr=1e-10`, `etot_conv_thr=1e-8`,
`forc_conv_thr=1e-5`, 300 electronic steps, `mixing_beta=0.3`, `dt=10`, the
reviewed FIRE parameters, `nstep=8`, and `max_seconds=6300`) and runs it from
fresh scratch.

The generic collector now accepts `fire-pilot` with extended scheduler fields
and preserves exact primary/collector submission records, wrapper context, raw
QE input/output/stderr/process evidence, exit status, and `sacct` rows. It does
not interpret the science or finalize anything. `FAILED`, `TIMEOUT`, and
nonzero exits remain collectible but cannot pass the later gate.

A separate read-only replay rebuilds the result from raw evidence, requiring
eight complete 18-atom main force blocks with healthy SCF cycles and no fatal,
NaN, signal, or OOM marker, unchanged cell and atom order, a final maximum
force component below the initial value and at most `1e-4 Ry/bohr`, cumulative
shift at most `0.02 A`, and Ibam No. 72 at `1e-6 A`. It also replays exact
request/result/context/hashes, terminal `COMPLETED/0:0` scheduler state,
resources, and globally unique job IDs. `finalize-pilot` may write only an
immutable pilot gate/provenance pair with `full_review_eligible`; structure
acceptance, preflight, full FIRE, force, and production always remain false.

The short pilot is a trend test, not a normal FIRE convergence test. Its design
does not require the two full-run convergence strings. Any future full FIRE
finalization would require both `FIRE: convergence achieved in` and `End of
FIRE minimization`; `JOB DONE`, a step/time limit, or abnormal termination
would be insufficient. Full execution/finalization is not implemented or
released, and the production budget/selection remain unchanged and blocked.

Local implementation validation is pending the final focused/full test and
syntax/diff checks. No remote connection, Slurm submission, QE calculation,
new runtime lineage, structure acceptance, or scientific result occurred.

### Local validation completion

After the implementation entry above was written, the final local checks
completed: all 358 tests passed with one optional-spglib skip; focused FIRE,
submission, collector, campaign, relax-recovery, and polish-recovery tests
also passed; both Rb2Cu2SnS4 and SrZrS3 configurations validated; Python
compilation, all Slurm/cluster shell syntax checks, and `git diff --check`
passed. This is software validation only. It does not replace independent code
review or remote exact-commit validation, and no scientific job was run.

### Fresh-review hardening before any execution

Fresh local review then identified authorization, uniqueness, collection, raw
parser, pseudopotential, and crash-order gaps. They were fixed before any
remote action. The trusted old lineage now has one code-owned atomic claim;
only one new FIRE RUN_DIR can consume it, and an interrupted claim fails
closed. The old plan-only RUN_DIR is not a claim and remains unusable under
the new workflow hashes.

Every importable submission entry now executes the Nibi-login, exact-config,
and file-lock gates. The FIRE primary is submitted with `--hold`; only after
the exact `afterany` collector is accepted are immutable attachment records
written and `scontrol release` attempted. QE remains unreachable until the
wrapper sees and replays both the attachment and successful release receipt.
Collector failure therefore leaves the primary held, while a short bounded
visibility wait closes the release-receipt filesystem race.

Preparation copies the exact UPF bytes already authenticated by the old polish
lineage into the new immutable `lineage_source/pseudopotentials/` archive.
Lineage, release, runtime launch, generated input, and replay all bind and
rehash those bytes; a changed file under the same basename is rejected.
Replay now reconstructs exact primary and collector commands, schemas,
dependencies, hashes, attachment, release, and summary. It requires the last
selected `Program PWSCF` run to be QE 7.3.1 and its unique final-coordinate
block to follow the eighth complete force step. Existing malformed provenance
fails hard; scheduler failure, nonzero exit, startup-before-attempt, and
writer-order interruption remain replayable negative gates when every artifact
that does exist is internally exact.

The corrected Rb-focused submission/FIRE/collector suite passed 77 tests;
Python compilation also passed. Full-suite rerun is deferred to the root
integration pass because concurrent Sr-only implementation work is changing
shared files. No SSH, Slurm command, scientific calculation, new runtime
lineage, structure acceptance, preflight/full FIRE, force, or production
release occurred.

The focused integration rerun then added all 46 campaign tests to the same
check: 123 FIRE/submission/collector/campaign tests passed in total.

Replay also covers both unavoidable submitter writer-order windows: a missing
release result after `scontrol` and a missing final submission summary are
explicit incomplete negative gates when all preceding records are exact;
malformed or later-deleted records in an otherwise completed chain remain
hard integrity failures. The online wrapper still requires the release receipt
and summary-independent collector attachment before QE.

---

## 2026-09-14 — bounded pilot completed; full first-pass FIRE continuation running

Nibi pilot primary `21867371` and collector `21867372` completed `0:0`.
Eight complete force/SCF steps reduced the maximum component from
`2.2291e-4` to `1.5722e-4 Ry/bohr` with only `5.8725440e-4 A` cumulative
coordinate shift; Ibam No. 72 was retained at `1e-6 A`. The pilot established
a healthy improving trend but did not pass its `1e-4 Ry/bohr` endpoint
threshold. It did not accept a structure or release phonon production.

For time-bounded first-pass delivery, a separate full FIRE continuation was
prepared from the pilot terminal coordinates with unchanged 100/800-Ry,
4x7x7, fixed occupations, `conv_thr=1e-10`, and FIRE parameters, but
`nstep=100` and `max_seconds=39600`. Input SHA-256 is
`ef034dd76e6ec108fca7668c4315ca48139885114f1d743aada35c6433b12f11`.
The first submission `21887921` failed in three seconds before QE because the
runner used the login submission directory; its empty scientific outputs are
preserved. Corrected job `21888372` is running on 32 MPI ranks from
`/scratch/yuhansun/phono3py-runs/20260914-rb-fire-full-firstpass/Rb2Cu2SnS4`.
QE 7.3.1 startup and one OpenMP thread per rank were observed with empty
stderr. Normal FIRE convergence and a later independent pristine SCF are still
required before accepting the structure.

---

## 2026-09-15 — full FIRE and pristine gates passed; cost-bounded force production running

All dates below are local record dates; Nibi scheduler timestamps are
2026-09-14 EDT. The corrected full-FIRE job `21888372` is authoritatively
`COMPLETED/0:0` in 02:24:36 on 32 ranks. The strict audit independently
confirmed both normal-convergence markers (`FIRE: convergence achieved in 26
steps` and `End of FIRE minimization`) before the unique final-coordinate
block and `JOB DONE`. The terminal 18-atom geometry retained its cell and atom
order, had maximum force component `9.21e-6 Ry/bohr` and total force
`3.4e-5 Ry/bohr`, shifted by at most `0.00185893 A` from the frozen seed, and
remained Ibam No. 72 at `1e-6 A`. Input/output/audit SHA-256 values are
`ef034dd76e6ec108fca7668c4315ca48139885114f1d743aada35c6433b12f11`,
`63e501635c67a11d5f43bb0f275f06e7d08cf4f26994ca12a81436fc7bf3e5d5`,
and `ba4dc11d63d6d759a6ad15244f7ee8fc61f250a62418ac49f8c85a5e4d314383`.

Independent pristine fixed-geometry job `21924016` then completed `0:0` in
00:33:07 on 32 ranks at 100/800 Ry, 4x7x7, `conv_thr=1e-10 Ry`, fixed
occupations, fresh atomic starts, and the exact FIRE terminal cell/coordinates.
Its strict audit passed with maximum force component `8.78e-6 Ry/bohr`, RMS
force `4.4178e-6 Ry/bohr`, total force `3.2e-5 Ry/bohr`, unchanged atom order,
and Ibam No. 72 at `1e-6 A`. Input/output/audit SHA-256 values are
`13741fdee760df7c191132b2465d63692f0c6cc441ef7c17d26f8880c443c0de`,
`1da3bb00c956a909587687cad54e0402d3359f6afdb764cb752eb6819a2900f3`,
and `b3c307f5d8be9102f06f6a67dcbe0a9516ce03b7e11c861631cf57e29cd08c05`.

Compute-node count-only preflight job `21926309` completed `0:0` with
phono3py 4.4.0. Using explicit QE-interface atomic units, 0.03 A displacement
was passed as 0.05669178 bohr and the pair cutoffs were converted from A to
bohr. Candidate counts were M72/3.70 A = 679, M72/4.25 A = 1343,
M72/5.00 A = 1811, and M108/4.25 A = 1343 displaced supercells. Only
M72/3.70 A met the declared 1000-supercell cap. Its 72-atom cell lengths are
10.987, 11.804, and 13.897 A, leaving about 1.793 A between the 3.70-A cutoff
and half the shortest cell length. The selected dataset SHA-256 is
`bb69732c8161dfe57d508777fa85209e6103a07c11df120cb0ac3cc01c02beda`.

Seven-task force pilot `21926602` completed entirely `0:0`. The strict audit
passed: duplicate raw-force RMS was `3.26315e-9 Ry/bohr`; the pristine-
subtracted 2x2x2-to-3x3x3 induced-force difference was RMS
`3.97069e-7 Ry/bohr`, maximum `1.20e-6 Ry/bohr`, and relative RMS 0.2477%;
the 80/640-to-100/800-Ry difference was RMS `5.27542e-7 Ry/bohr`, maximum
`1.74e-6 Ry/bohr`, and relative RMS 0.3290%. All were below the predeclared
`1e-5 Ry/bohr` RMS, `5e-5 Ry/bohr` maximum, and 2% relative gates. Pristine
maximum components were `4.067e-5`, `1.001e-5`, and `3.836e-5 Ry/bohr` for
100/800-Ry 2x2x2, 100/800-Ry 3x3x3, and 80/640-Ry 2x2x2 respectively. QE
wrote only its known IEEE underflow/denormal notice to pilot stderr; the audit
records and permits that exact line but still rejects every unknown stderr
line. Pilot audit SHA-256 is
`45cd8562df3ace41ab6ce049a5577c4e4aaadb1894b0f29e1090ab4881dbd272`.

The resulting cost-bounded production choice is M72/3.70 A, 0.03-A
displacements, 100/800 Ry, 2x2x2, `conv_thr=1e-10 Ry`, fixed occupations,
`nosym=.true.`, and `noinv=.true.`. Array `21934047` contains one pristine
plus 679 displaced tasks and runs at most 32 concurrently on Nibi compute
nodes. Its task-map and manifest SHA-256 values are
`6e115d64d38a4e7c4e13ad2bafe8e9ae4803cb3eed82c566ee7a559c4afa1797`
and `9efff593656ab829485b1e5c805a7885536d70f9406adbbbc83b24d41ece9661`.
Dependent job `21934081` uses `afterok:21934047`; it must capture accounting,
strictly audit every output, build FC2/FC3, and only then run explicit non-NAC
RTA conductivity on the material-specific generalized-grid ladder.

This lane remains explicitly **first_pass_unconverged** even if all running
jobs succeed. PBE, RTA, no SOC, no NAC, no isotope/boundary scattering, one
72-atom supercell, one 3.70-A FC3 cutoff, one displacement amplitude, no
4x4x4 force confirmation, and no cutoff/supercell/amplitude convergence do
not support a converged intrinsic conductivity claim. The earlier broad pilot
design in this file was not completed; the present calculation is a bounded
screening result only. Two local audit-development mistakes were also
preserved in the narrative rather than hidden: an initial dynamic-import bug
and an unbounded final-coordinate regex briefly left four exact stale parser
processes, which were terminated before the bounded parser was rerun. Neither
attempt submitted a job or altered scientific output.

### Production infrastructure failure and scoped recovery

Production element `21934047_361` (`task-00361-disp03013`) failed after
00:26:04 on node `c189` with exit `135:0`.  All 32 MPI ranks reported signal
7 (`Bus error: nonexistent physical address`).  Although the truncated QE
output contains a force block, it lacks `JOB DONE` and is rejected under the
strict parser.  The failed attempt is preserved remotely under
`production/task-00361-disp03013/failure-21934047_361/`; its SHA-256 manifest
has digest
`da6db84b5fa574c9029e5567c65c9ab39c594e13e6aaf22629fe4396a3a03f27`.
The original truncated output and stderr digests are
`b63ea37da9407d787b0969cfe25f24df18b6e5d991d7d2e27f45d00eb1726e36`
and
`14ca398e6e68cf05b0fc84c1bb1e86808c018b363f9a0cb64d7242065b9ded22`.

Only that failed element was resubmitted: recovery job `21963653` uses
`array=361` and `afterany:21934047`.  Replacement postprocess job `21963654`
uses `afterok:21963653`.  The original postprocess `21934081` remains
untouched and cannot satisfy its `afterok:21934047` dependency after the
recorded failure.  This is a node-failure recovery, not acceptance of the
truncated force or a whole-array rerun.  Production and recovery remain
incomplete at this record point.

---

## 2026-09-20 — task 462 infrastructure failure archived; narrow recovery submitted

A bounded live Nibi audit confirmed that original production element
`21934047_462` (`disp03843`) had failed before scientific execution during QE
module start-up. Its task directory still contained only the hash-matching
`scf.in`; no `scf.out`, `scf.err`, exit-code, start, finish, or temporary
record was present. The task-map SHA-256 remained
`6e115d64d38a4e7c4e13ad2bafe8e9ae4803cb3eed82c566ee7a559c4afa1797`,
and the task input SHA-256 remained
`cccbe682b5f7b6fba229721a4839c390094d3dd0acaca4d18f28298712a33bbb`.
The current `cluster.env` loaded Quantum ESPRESSO 7.3.1 successfully before
submission.

Two new timestamped, read-only evidence archives were created without
overwriting prior records: one for original force failure `21934047_462`, and
one for failed strict postprocess `21963654`. Each contains source-path and
SHA-256 manifests that passed `sha256sum -c`. Only array element 462 was then
submitted as recovery job `22312416`; dependent postprocess `22312417` uses
`afterok:22312416` and re-audits the complete original production set before
any FC2/FC3 or transport work. One post-submission scheduler check confirmed
`22312416` pending for priority and `22312417` pending on its dependency.
There was no repeated polling, full-array rerun, concurrency increase, or
cancellation of historical postprocess `21934081`.

**Scientific boundary:** this milestone confirms only provenance, submission,
and dependency wiring. It does not establish a valid task-462 force, a passing
whole-production audit, FC2/FC3, phonon stability, q-mesh convergence, or
kappa_L. The lane remains `first_pass_unconverged` even if the recovery chain
later passes.
