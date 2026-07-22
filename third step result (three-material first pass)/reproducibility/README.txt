How to regenerate the three-material comparison

The comparison is assembled from each material's completed first-pass records
in thermo_candidates/<material>/. Nothing here re-runs QE or BoltzTraP2.

Per-material sources (all under thermo_candidates/<material>/):
  results/workflow_summary.md              DFT setup, gap, best-PF table
  results/transport_best_power_factor.csv  best-PF/tau point per T and carrier
  results/transport_full.csv               all 98 sampled conditions
  structures/<material>.relaxed.cif        relaxed structure
  qe/convergence/cutoff_results.csv        cutoff test
    (SrCu2SnS4's sits deeper: qe/convergence/cutoff/cutoff_results.csv)
  qe/convergence/kpoint_results.csv        k-point test
    (SrCu2SnS4's: qe/convergence/kpoints/kpoint_results.csv)
  WORKLOG.md                               step-by-step lab notebook

The combined transport CSV in READY_TO_ATTACH was built by prefixing each
material's transport_best_power_factor.csv rows with a material column.

Figures (run from the workspace root, thermo-bt2 env sourced):
  # per-material Seebeck-vs-mu, centered on E_F (also copied into
  # READY_TO_ATTACH as <material>_Seebeck_vs_mu.png/.csv):
  ( cd thermo_candidates/SrZrS3     && python boltztrap2/plot_seebeck.py )
  ( cd thermo_candidates/Rb2Cu2SnS4 && python boltztrap2/plot_seebeck.py )
  # three-material PF/tau + zT_e comparison figure:
  python thermo_candidates/scripts/plot_three_material_transport.py \
    "third step result (three-material first pass)/results/three_material_transport_comparison.png"
Each plot_seebeck.py prints three cross-checks (trace-vs-condtens tensor
average, charge neutrality at E_F, dope-vs-scan S agreement).

Reference values (all [calculated] unless noted):
  QE-PBE gaps:  SrCu2SnS4 0.3445 | SrZrS3 0.6096 | Rb2Cu2SnS4 0.7811 eV
  listed gaps [database]:  0.4032 | 0.5512 | 0.8641 eV
  cutoffs:  90/720 | 50/400 | 90/720 Ry
  dense NSCF:  12x12x6 (100) | 20x10x6 (264) | 8x14x14 (788 irr. k)
  favored carrier (zT_e):  p | n | p

Deeper background: ../../WORKFLOW_EXPLAINED.md (concepts) and ../../learning/
(tools, code, data, and the full comparison methodology in
learning/05_comparing_materials.md).
