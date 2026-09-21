# English slide notes and sources

## 1. Thermoelectric sulfides

I have completed the three electronic first passes and tested the phonon workflow. The present milestone is a traceable research record and a focused plan for the remaining scientific questions. None of the three materials currently has an accepted lattice thermal conductivity under our current criteria. This update uses saved repository evidence, not a current cluster check.

Sources: `experiments/phonon_research_sandbox/CURRENT_STATE.md`

## 2. Electronic workflow completed

Each material used its own convergence workflow before the electronic transport first pass. This existing SrCu2SnS4 plot compares the Quantum ESPRESSO density of states with the BoltzTraP2 interpolation. It supports a workflow comparison but does not by itself establish convergence of every transport property. The calculations use PBE without explicit spin–orbit coupling.

Sources: `thermo_candidates/SrCu2SnS4/results/dos_qe_vs_boltztrap2.png`, `thermo_candidates/SrCu2SnS4/results/workflow_summary.md`, `thermo_candidates/SrZrS3/results/workflow_summary.md`, `thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md`

## 3. Electronic screening at 300 K

The bars are the best power-factor-over-relaxation-time values selected independently for each carrier sign on the sampled 300 K grid. Rb2Cu2SnS4 has the largest p-type value among these first passes. This does not establish the best final thermoelectric material, because relaxation time and accepted lattice thermal conductivity remain missing. SrZrS3 carrier preference depends on the metric and temperature, so I do not assign one universal doping preference.

Sources: `thermo_candidates/SrCu2SnS4/results/transport_best_power_factor.csv`, `thermo_candidates/SrZrS3/results/transport_best_power_factor.csv`, `thermo_candidates/Rb2Cu2SnS4/results/transport_best_power_factor.csv`

## 4. Phonon evidence and acceptance

The table separates artifact creation from scientific acceptance. SrCu2SnS4 preserves a historical campaign with known problems, while its corrected workflow remains preparation only. SrZrS3 produced force constants but failed a sampled-frequency gate. Rb2Cu2SnS4 has a saved artifact audit with limited integrity checks, but all tested mesh transitions fail the convergence rule. For the latter two, this update reads the saved audit records rather than revalidating the remote HDF5 files.

Sources: `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json`, `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`, `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `fourth step result (phono3py lattice thermal conductivity)/README.md`

## 5. SrCu2SnS4: a separate corrected campaign

The historical Quantum ESPRESSO interface interpreted the pair cutoff in bohr. The value four therefore meant about 2.12 angstrom, and the included pair groups were onsite only. The new preparation explicitly converts four angstrom to about 7.5589 bohr and requests uniform force settings. These software corrections do not demonstrate a converged force dataset. The old raw outputs and sent attachments remain unchanged.

Sources: `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml`, `fourth step result (phono3py lattice thermal conductivity)/README.md`

## 6. SrCu2SnS4 v2: minimal proposed pilot

I propose beginning with a healthy independent pristine calculation and a small set of repeated single and pair displacement controls. The detailed plan defines how to distinguish numerical noise from incremental force signal and when to stop. Amplitude and force-setting sensitivity should inform any larger production campaign. The exact displacement count and cost require real generation and measured timing. No new campaign has been submitted.

Sources: `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `experiments/phonon_research_sandbox/plans/`

## 7. SrZrS3: imaginary-mode origin is unresolved

The saved first-pass audit reports a minimum frequency of minus 1.0716 terahertz at the stated q point. Twelve sampled modes are below minus 0.1 terahertz. The pristine residual force exceeded the preferred threshold, and a historical exception allowed a diagnostic continuation. Residual forces, force convergence and finite-range effects deserve targeted controls before a physical instability interpretation. Eigenvectors and structural response would help distinguish competing explanations. Simply removing imaginary modes would not validate thermal conductivity.

Sources: `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json`, `experiments/phonon_research_sandbox/plans/`

## 8. Rb2Cu2SnS4: direction-dependent mesh response

This figure replots the conventional Cartesian tensor components recorded in the September 20 audit. The horizontal axis is the phono3py q-mesh density length, not a real-space cutoff or a supercell size. The zz component changes substantially across the ladder, while yy is comparatively less sensitive. All values are rejected first-pass diagnostics. I have neither fitted an asymptote nor estimated a supposedly converged thermal conductivity.

Sources: `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`

## 9. Rb2Cu2SnS4: the final step still fails

I recalculated these changes using the same denominator as the implemented gate: the denser mesh result. At 300 kelvin, the average changes by about 4.266 percent and the largest diagonal by about 10.192 percent. Both fail. The same conclusion holds at 600 and 900 kelvin, and no earlier transition passes. A denser mesh could reuse the force constants only for the same underlying force model with retained provenance. It would still not establish supercell, cutoff or amplitude convergence.

Sources: `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`, `thermo_candidates/Rb2Cu2SnS4/phono3py/run_postprocess_firstpass.py`

## 10. Proposed next research choices

These are alternatives for discussion, not a decision made on behalf of Roy. For SrCu2SnS4, the benefit is a clean corrected baseline. For SrZrS3, the key benefit is understanding a failure mechanism. For Rb2Cu2SnS4, existing force data may support a bounded convergence study, but provenance and force-model limitations must remain explicit. I will estimate resource use from actual task counts and measured timing before asking to expand any route.

Sources: `experiments/phonon_research_sandbox/plans/`, `experiments/phonon_research_sandbox/CURRENT_STATE.md`

## 11. Discussion with Roy

I have sent the revised status update and am awaiting guidance on the next priority. I would appreciate guidance on whether to prioritize the corrected SrCu2SnS4 baseline, diagnose SrZrS3, or continue a bounded Rb2Cu2SnS4 convergence study. The accompanying plans and local evidence dashboard make these options reviewable. No new cluster calculation or email was initiated during this preparation round.

Sources: `experiments/phonon_research_sandbox/CURRENT_STATE.md`
