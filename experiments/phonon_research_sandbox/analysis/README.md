# Offline phonon evidence dashboard

`../dashboard/index.html` is a Chinese-first offline reading layer for the saved
phonon evidence of SrCu2SnS4, SrZrS3, and Rb2Cu2SnS4. It deliberately separates
scheduler status, saved-artifact integrity, and scientific acceptance.

## Rebuild

From the repository root:

```bash
python3 experiments/phonon_research_sandbox/analysis/build_dashboard_data.py
```

The script reads only the two saved Rb JSON audit/synthesis records and writes:

- `results/rb_qmesh_ladder_all_tensors.csv`: five q-mesh levels, three
  temperatures, all six tensor components plus trace/3, prior value, retained
  denominator, and applicable consecutive relative change.
- `results/dashboard_data.json`: embedded dashboard data and source/output
  hashes.

No remote connection, HDF5 mutation, scheduler query, or calculation occurs.
The HDF5 audit is evidence of a bounded saved-artifact integrity check; it is
not evidence that force constants are scientifically valid or that kappa_L is
accepted. Off-diagonal terms are numerical near-zero values; their relative
changes are intentionally marked not applicable.
