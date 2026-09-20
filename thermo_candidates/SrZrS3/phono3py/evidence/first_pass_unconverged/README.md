# SrZrS3 first-pass postprocessing: rejected diagnostic

## Disposition

This time-bounded calculation is labelled **`first_pass_unconverged`**. It is
not an accepted lattice thermal conductivity result. Force collection and
full FC2/FC3 construction passed the stated structural and file-integrity
checks, but the first explicit no-NAC q mesh failed the harmonic-frequency
gate. No denser mesh was run.

The decisive result was a minimum sampled frequency of
`-1.0716026422440281 THz` at reduced q point `[0.0, 0.4, 0.0]`, zero-based band
0. Twelve sampled modes were below the `-0.1 THz` rejection threshold. This
can reflect a real instability or deficiencies in the time-bounded force,
supercell, cutoff, or structure choices; this calculation cannot distinguish
those possibilities.

## Remote source and jobs

- Host: Nibi (`nibi.alliancecan.ca`), compute nodes only.
- Run root:
  `/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3`
- Production force array: Slurm `21888373`; all 788 rows independently
  accounted as `COMPLETED|0:0`.
- Final postprocess job: Slurm `21925850`, node `c500`, 16 CPUs, 60 GB
  requested, `FAILED|2:0`, elapsed `00:01:29`. This nonzero exit is the
  intentional fail-closed frequency gate, after the mesh command returned 0.
- Final immutable attempt:
  `/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3/postprocess/20260914T183000Z-firstpass-postprocess`

All postprocess attempts remain immutable under the same `postprocess/`
parent. The exact job-to-attempt mapping is:

| Slurm job | Attempt directory | Stop reason |
| --- | --- | --- |
| 21924767 | `20260914T174000Z-firstpass-postprocess` | mechanical wrapper-version query |
| 21924822 | `20260914T174200Z-firstpass-postprocess` | YAML presentation-order assumption |
| 21924947 | `20260914T174400Z-firstpass-postprocess` | total-versus-included-ID assumption |
| 21925015 | `20260914T174600Z-firstpass-postprocess` | bohr/angstrom comparison assumption |
| 21925300 | `20260914T175200Z-firstpass-postprocess` | preferred pristine-force gate failed |
| 21925488 | `20260914T180400Z-firstpass-postprocess` | checker omitted phono3py drift removal/quantization |
| 21925660 | `20260914T181500Z-firstpass-postprocess` | checker expected the wrong FC2 HDF5 key |
| 21925850 | `20260914T183000Z-firstpass-postprocess` | scientific frequency-integrity failure |

The exact final submission command is recorded by Slurm as:

```text
/opt/software/slurm/bin/sbatch --parsable --account=def-kleinke_cpu --chdir=/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3 --output=/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3/slurm-postprocess-%j.out --error=/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3/slurm-postprocess-%j.err --export=ALL,P3_RUN_DIR=/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3,P3_SCRIPT_DIR=/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3/postprocess_tools,P3_ATTEMPT_ID=20260914T183000Z-firstpass-postprocess,P3_AUDIT_SCRIPT_SHA256=3ef27483499080cdc97e40a98f9290c1099061ab71012fc50f1685d1767521e0,P3_POSTPROCESS_SCRIPT_SHA256=e11c13d45c8c39a313f27ed6889421502c7df515e6f1a3d8d909bf5e6c2664c9 /scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3/postprocess_tools/run_firstpass_postprocess.sbatch
```

The exact 787-output `phono3py-init --qe --cf3 ... --cfz ...` argv is retained
in remote `work/commands.jsonl` rather than duplicated here. Its ordered paths
are bound to the audited included-YAML ID list. The transport invocation was:

```text
/home/yuhansun/venvs/p3/bin/phono3py --mesh 12 5 3 --br --ts 300 600 900 --nonac --full-fc --fc-calc symfc phono3py_disp.yaml
```

It ran in the final attempt's `work/` directory from
`2026-09-14T18:07:49Z` to `18:08:06Z` and returned 0.

## Force and mapping audit

The audit resolved all 4,025 YAML displacement IDs: 787 included files and
3,238 excluded zero-force blocks, plus task 0 as pristine. It verified all 788
input, output, stderr, exit-code, and identity records; strict last complete QE
force blocks; `JOB DONE`; output atom types; input/output hashes; and exact
task-to-YAML mapping. The 40-atom order is 8 Sr, 8 Zr, then 24 S. Fractional
positions matched exactly, and the largest cell difference after converting
the YAML bohr cell to input angstrom was `3.552713678800501e-15 angstrom`.

The pristine force failed the preferred gate: maximum component
`9.342e-5 Ry/bohr` versus `5e-5 Ry/bohr` configured. A separately recorded,
explicit time-bounded exception allowed continuation below a `1e-4 Ry/bohr`
ceiling while requiring strict per-atom pristine subtraction and the final
`first_pass_unconverged` label. The configured threshold was not altered.

The archived six-task pilot showed distinguishable incremental signals:

- single minus pristine RMS: `8.972577095381375e-4 Ry/bohr`, propagated
  duplicate noise `8.010409893812267e-9 Ry/bohr`;
- double minus single RMS: `9.036242481771668e-4 Ry/bohr`, propagated
  duplicate noise `8.563488385790836e-9 Ry/bohr`.

Before FC fitting, `FORCES_FC3` was independently checked against phono3py's
per-output translational-drift removal, strict per-atom pristine subtraction,
and 10-decimal serialization. Every component agreed within
`2e-10 Ry/bohr`, a bound covering two 10-decimal write quantizations plus
floating-point roundoff and tighter than `1e-9 Ry/bohr`.

FC2 used the documented `force_constants` dataset and had shape
`(40,40,3,3)`; FC3 used `fc3` and had shape `(40,40,40,3,3,3)`. Both arrays
were finite. The measured maximum acoustic-sum residuals were
`2.944866572818228e-14 eV angstrom^-2` for FC2 and
`5.790923296444817e-13 eV angstrom^-3` for FC3; the tested permutation
residual was exactly zero for both. These are integrity diagnostics, not
force-constant convergence evidence. The first transport file was finite,
with mesh `(12,5,3)`, 42 irreducible q points, weights summing to 180, three
temperatures, a `(3,6)` kappa tensor, and `(42,60)` frequencies.

## Rejected numerical diagnostic

[`kappa_m1253_rejected_diagnostic.csv`](kappa_m1253_rejected_diagnostic.csv)
transcribes the finite HDF5 tensor. Components use phono3py order
`xx,yy,zz,yz,xz,xy` and units `W m^-1 K^-1`. These values are not a valid
kappa_L result because the same file fails the frequency gate; they must not
be used for zT.

## Scope limits

This is PBE, single-mode RTA, no explicit SOC, explicit `--nonac`, and no
isotope or boundary scattering. Born effective charges and dielectric data
were not available. The 2x1x1 40-atom supercell, 3.5541348625-angstrom pair
cutoff, 80/640-Ry plane-wave cutoffs, 3x3x3 force k mesh, force thresholds,
and lone 12x5x3 q mesh are time-bounded first-pass choices, not converged
defaults. No q-mesh convergence claim, harmonic-stability claim, accepted
kappa_L, or final thermoelectric zT follows from this record.

See [`remote_artifact_sha256.txt`](remote_artifact_sha256.txt) and
[`force_audit_summary.json`](force_audit_summary.json) for compact provenance.
