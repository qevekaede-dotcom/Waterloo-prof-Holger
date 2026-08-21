# Evidence: stage1 array fast-failures on Nibi (2026-08-21)

Provenance: verbatim terminal output pasted by the user during the
2026-08-21 interactive session (the raw files on the cluster are overwritten
in place when a displacement is rerun, so this transcript preserves the
failure record; from stage2 onward `scripts/slurm/collect_evidence.sh`
snapshots such state automatically before it can be destroyed).

## Context

- Campaign: SrCu2SnS4 phono3py force campaign, resubmitted 2026-08-21 after
  the OpenMP-oversubscription fix (WORKLOG Session 4).
- stage0 = job 20213855: COMPLETED in 02:56:28 (vs. >10 h stuck on SCF
  iteration 7 before the `OMP_NUM_THREADS=1` fix).
- stage1 = job 20213856 (168-task array): 144/168 COMPLETED at ~39-47 min
  per force calculation; 24 tasks FAILED in 19-27 s each.
- stage2 = job 20215178: PENDING with DependencyNeverSatisfied (by design:
  afterok on an array with failures can never fire). Cancelled and re-chained
  behind the rerun of the 24 failed indices.

## Failed array tasks (sacct -X, non-COMPLETED only)

```
             JobID      State    Elapsed
------------------ ---------- ----------
       20213856_25     FAILED   00:00:20
       20213856_30     FAILED   00:00:20
       20213856_41     FAILED   00:00:24
       20213856_43     FAILED   00:00:22
       20213856_48     FAILED   00:00:19
       20213856_57     FAILED   00:00:19
       20213856_62     FAILED   00:00:25
       20213856_71     FAILED   00:00:19
       20213856_76     FAILED   00:00:20
       20213856_79     FAILED   00:00:20
       20213856_84     FAILED   00:00:22
       20213856_95     FAILED   00:00:22
       20213856_97     FAILED   00:00:20
      20213856_102     FAILED   00:00:27
      20213856_111     FAILED   00:00:19
      20213856_116     FAILED   00:00:20
      20213856_125     FAILED   00:00:20
      20213856_130     FAILED   00:00:20
      20213856_133     FAILED   00:00:20
      20213856_138     FAILED   00:00:19
      20213856_147     FAILED   00:00:19
      20213856_152     FAILED   00:00:20
      20213856_161     FAILED   00:00:20
      20213856_166     FAILED   00:00:20
```

## Unhealthy displacement directories (health-check over scf.out)

disp-00026, disp-00601, disp-01182, disp-01826, disp-02401, disp-02980,
disp-03555, disp-04134, disp-04709, disp-05426, disp-06001, disp-06582,
disp-07226, disp-07801, disp-08380, disp-08955, disp-09534, disp-10109,
disp-10826, disp-11401, disp-11980, disp-12555, disp-13134, disp-13709.

Pattern observations (analysis, not raw data):

- Exactly one failure inside each ~6-displacement pair block, plus one in
  the leading single-displacement block — evenly spaced in displacement-ID
  space. Random node flakes do not select IDs this regularly.
- Every failure died at the same place: immediately after pw.x printed the
  dynamical-RAM estimate (before the first SCF iteration). Memory itself is
  not the cause (25.77 GB estimated vs 64 GB allocated).
- In every case MPI task 14 (sometimes 13-14) of 32 exited with code 1 and
  srun then killed the rest. Failures are spread over many different nodes
  (c67, c76, c108, c161, c206, c216, c226, c271, c277, c289, c310, c312,
  c329, c360, c384, c566, c594, c605, c684, c699) and over ~2.6 h of wall
  time, so a single bad node is ruled out.
- Both the nk=2 attempt and the automatic nk=1 retry failed identically
  (~10 s each; total task time ~20 s).

## Verbatim scf.err of every failed displacement

All scf.out files ended with:

```
     Estimated max dynamical RAM per process >     824.76 MB

     Estimated total dynamical RAM >      25.77 GB
```

```
=== fc_calcs/disp-00026/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20221816.1 ON c108 CANCELLED AT 2026-08-21T01:47:17 ***
srun: error: c108: tasks 0-12,15-31: Killed
srun: Terminating StepId=20221816.1
srun: error: c108: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-00601/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error:  mpi/pmix_v4: _errhandler: c67 [0]: pmixp_client_v2.c:211: Error handler invoked: status = -61, source = [slurm.pmix.20221954.1:21]
srun: error: c67: tasks 0-13,15-31: Killed
srun: Terminating StepId=20221954.1
srun: error: c67: task 14: Exited with exit code 1
=== fc_calcs/disp-01182/ scf.err ===
slurmstepd: error: *** STEP 20224099.1 ON c216 CANCELLED AT 2026-08-21T02:23:44 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c216: tasks 0-13,15-31: Killed
srun: Terminating StepId=20224099.1
srun: error: c216: task 14: Exited with exit code 1
=== fc_calcs/disp-01826/ scf.err ===
slurmstepd: error: *** STEP 20224101.1 ON c226 CANCELLED AT 2026-08-21T02:23:41 ***
slurmstepd: error: *** STEP 20224101.1 ON c226 CANCELLED AT 2026-08-21T02:23:41 ***
srun: error: c226: tasks 0-12,15-31: Killed
srun: Terminating StepId=20224101.1
srun: error: c226: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-02401/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error:  mpi/pmix_v4: _errhandler: c161 [0]: pmixp_client_v2.c:211: Error handler invoked: status = -61, source = [slurm.pmix.20224226.1:14]
srun: error: c161: tasks 0-13,15-31: Killed
srun: Terminating StepId=20224226.1
srun: error: c161: task 14: Exited with exit code 1
=== fc_calcs/disp-02980/ scf.err ===
slurmstepd: error: *** STEP 20224235.1 ON c605 CANCELLED AT 2026-08-21T02:27:14 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c605: tasks 0-13,15-31: Killed
srun: Terminating StepId=20224235.1
srun: error: c605: task 14: Exited with exit code 1
=== fc_calcs/disp-03555/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error:  mpi/pmix_v4: _errhandler: c594 [0]: pmixp_client_v2.c:211: Error handler invoked: status = -61, source = [slurm.pmix.20224362.1:14]
srun: error: c594: tasks 0-12,15-31: Killed
srun: Terminating StepId=20224362.1
srun: error: c594: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-04134/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20224591.1 ON c206 CANCELLED AT 2026-08-21T02:38:10 ***
srun: error: c206: tasks 0-12,15-31: Killed
srun: Terminating StepId=20224591.1
srun: error: c206: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-04709/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: --task-epilog failed status=9
srun: error: c67: tasks 0-12,15-31: Killed
srun: Terminating StepId=20226171.1
srun: error: c67: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-05426/ scf.err ===
slurmstepd: error: *** STEP 20226174.1 ON c277 CANCELLED AT 2026-08-21T03:00:43 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c277: tasks 0-12,15-31: Killed
srun: Terminating StepId=20226174.1
srun: error: c277: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-06001/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20226423.1 ON c289 CANCELLED AT 2026-08-21T03:04:33 ***
srun: error: c289: tasks 0-12,15-31: Killed
srun: Terminating StepId=20226423.1
srun: error: c289: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-06582/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20226571.1 ON c684 CANCELLED AT 2026-08-21T03:08:15 ***
srun: error: c684: tasks 0-13,15-31: Killed
srun: Terminating StepId=20226571.1
srun: error: c684: task 14: Exited with exit code 1
=== fc_calcs/disp-07226/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20226573.1 ON c699 CANCELLED AT 2026-08-21T03:08:12 ***
srun: error: c699: tasks 0-12,15-31: Killed
srun: Terminating StepId=20226573.1
srun: error: c699: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-07801/ scf.err ===
srun: Terminating StepId=20226660.1
slurmstepd: error: *** STEP 20226660.1 ON c566 CANCELLED AT 2026-08-21T03:11:56 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: --task-epilog failed status=9
srun: error: c566: tasks 0-13,15-31: Killed
=== fc_calcs/disp-08380/ scf.err ===
slurmstepd: error: *** STEP 20227321.1 ON c384 CANCELLED AT 2026-08-21T03:34:13 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c384: tasks 0-13,15-31: Killed
srun: Terminating StepId=20227321.1
srun: error: c384: task 14: Exited with exit code 1
=== fc_calcs/disp-08955/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error:  mpi/pmix_v4: _errhandler: c329 [0]: pmixp_client_v2.c:211: Error handler invoked: status = -61, source = [slurm.pmix.20227560.1:16]
srun: error: c329: tasks 0-13,15-31: Killed
srun: Terminating StepId=20227560.1
srun: error: c329: task 14: Exited with exit code 1
=== fc_calcs/disp-09534/ scf.err ===
slurmstepd: error: *** STEP 20227817.1 ON c67 CANCELLED AT 2026-08-21T03:48:43 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c67: tasks 0-13,15-31: Killed
srun: Terminating StepId=20227817.1
srun: error: c67: task 14: Exited with exit code 1
=== fc_calcs/disp-10109/ scf.err ===
slurmstepd: error: *** STEP 20227822.1 ON c277 CANCELLED AT 2026-08-21T03:48:43 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c277: tasks 0-13,15-31: Killed
srun: Terminating StepId=20227822.1
srun: error: c277: task 14: Exited with exit code 1
=== fc_calcs/disp-10826/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: --task-epilog failed status=9
srun: error: c312: tasks 0-13,15-31: Killed
srun: Terminating StepId=20227825.1
srun: error: c312: task 14: Exited with exit code 1
=== fc_calcs/disp-11401/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20227929.1 ON c271 CANCELLED AT 2026-08-21T03:52:19 ***
srun: error: c271: tasks 0-12,15-31: Killed
srun: Terminating StepId=20227929.1
srun: error: c271: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-11980/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20228103.1 ON c360 CANCELLED AT 2026-08-21T03:59:28 ***
srun: error: c360: tasks 0-12,15-31: Killed
srun: Terminating StepId=20228103.1
srun: error: c360: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-12555/ scf.err ===
slurmstepd: error: *** STEP 20228653.1 ON c76 CANCELLED AT 2026-08-21T04:20:58 ***
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
srun: error: c76: tasks 0-13,15-31: Killed
srun: Terminating StepId=20228653.1
srun: error: c76: task 14: Exited with exit code 1
=== fc_calcs/disp-13134/ scf.err ===
srun: Job step aborted: Waiting up to 62 seconds for job step to finish.
slurmstepd: error: *** STEP 20228771.1 ON c310 CANCELLED AT 2026-08-21T04:24:34 ***
srun: error: c310: tasks 0-12,15-31: Killed
srun: Terminating StepId=20228771.1
srun: error: c310: tasks 13-14: Exited with exit code 1
=== fc_calcs/disp-13709/ scf.err ===
slurmstepd: error: --task-epilog failed status=9
slurmstepd: error:  mpi/pmix_v4: _errhandler: c310 [0]: pmixp_client_v2.c:211: Error handler invoked: status = -61, source = [slurm.pmix.20228932.1:14]
srun: error: c310: tasks 0-12,15-31: Killed
srun: Terminating StepId=20228932.1
srun: error: c310: tasks 13-14: Exited with exit code 1
```

## Earlier failures from the same campaign (key verbatim lines)

First submission, stage0 job 19030260 (2026-08-03, TIMEOUT after 10 h —
OpenMP oversubscription; full analysis in WORKLOG Session 4):

```
     Parallel version (MPI & OpenMP), running on     352 processor cores
     total energy              =   -9077.20077332 Ry
     estimated scf accuracy    <        0.01272505 Ry

     iteration #  7     ecut=    90.00 Ry     beta= 0.30
slurmstepd: error: *** JOB 19030260 ON c544 CANCELLED AT 2026-08-04T02:57:14 DUE TO TIME LIMIT ***
```

Stage-2 venv install attempts (2026-08-20 evening ET):

```
    ERROR: Use build.verbose instead of cmake.verbose for scikit-build-core >= 0.10
ERROR: Failed to build 'phono3py' when getting requirements to build wheel
../scipy/meson.build:285:9: ERROR: Dependency "OpenBLAS" not found (tried pkg-config and cmake)
error: metadata-generation-failed
```

Resolution for both: WORKLOG Session 4 and DRAC_SETUP.md section 3.
