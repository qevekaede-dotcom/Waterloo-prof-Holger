# Candidate-workspace rules for Claude

Each material directory uses the same responsibilities:

- `structures/`: source and relaxed CIF files;
- `qe/`: QE inputs, convergence work, scripts, and restart data;
- `boltztrap2/`: interpolation files, transport tensors, and helper scripts;
- `logs/`: retained run logs;
- `results/`: processed CSV tables and human-readable summaries;
- `notes/`: provenance and material-selection notes;
- `candidate.yml`: screening metadata.

The authoritative completed example is `SrCu2SnS4`, but its numerical cutoffs,
k meshes, and band count are not defaults for the other compounds. For each new
material, run cutoff convergence, k-point convergence, relaxation, final SCF,
dense NSCF, and then BoltzTraP2.

Do not move raw outputs into `results/`, and do not calculate final `zT` without
an explicit relaxation-time model and lattice thermal conductivity.
