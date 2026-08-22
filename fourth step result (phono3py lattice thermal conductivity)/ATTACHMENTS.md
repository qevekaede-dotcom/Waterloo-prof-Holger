# Attachments for the phono3py email

Send plan: one email, one attachment folder (or four attached files).
Everything to send lives in `READY_TO_ATTACH/`:

1. `HOW_WE_GOT_PHONO3PY_WORKING.md` — the write-up Roy asked for: working
   recipe, all seven traps with symptoms and fixes, process rules,
   validation. (Markdown; export to PDF only if Roy prefers — do not add
   a PDF to the repo.)
2. `SrCu2SnS4_kappa_L_first_pass.csv` — kappa_L tensor vs T, 300-900 K,
   units in every header [calculated].
3. `SrCu2SnS4_kappa_L_vs_T.png` — the figure (in-plane, c-axis, average;
   settings annotated on the plot).
4. `SrCu2SnS4_kappa_L_summary.md` — machine-written settings + checks
   summary from the stage-2 postprocess (solver, minimum phonon
   frequency, mesh).

Do not attach: FORCES_FC3, HDF5 files, raw scf outputs, slurm logs (all
archived in the repo; the write-up links the repo for anyone who wants
them).
