# Work log: second step (DOS comparison and Seebeck graph, SrCu2SnS4)

A step-by-step record of how this result was produced, including the attempts
that failed and what fixed them. Newest task at the bottom.

---

## 2026-07-02 — DOS calculation and comparison

**Goal.** Roy's 30 June email asked: "Have you also performed a DOS calculation
with QE? If so, please compare the results to the BoltzTraP2 DOS and see how they
compare."

**1. Understood the workspace.** Read `README_START_HERE.md`, the per-material
CLAUDE.md files, and the SrCu2SnS4 QE/BoltzTraP2 scripts. Confirmed the first
pass for SrCu2SnS4 is complete and its dense NSCF (`12x12x6`, 100 irreducible
k-points, 140 bands) is stored in `qe/tmp/final/SrCu2SnS4.save/`.

**2. Key decision — do not re-run the NSCF.** The NSCF log shows it took ~1h29m
wall. The DOS only needs those eigenvalues, which are already on disk, so I
reused them. This also makes the comparison fair: QE `dos.x` and BoltzTraP2 then
use the *same* bands.

**3. Checked tools.** `pw.x`, `dos.x`, `projwfc.x` present under
`~/scientific-tools/apps/qe`. BoltzTraP2 imports inside the `thermo-bt2` conda
env. Recorded SHA-256 of the three protected raw files
(`data-file-schema.xml`, `charge-density.dat`, `SrCu2SnS4.bt2`) so I could prove
they were untouched afterward.

**4. Band-edge facts (from QE).** highest occupied = 7.1887 eV, lowest
unoccupied = 7.5332 eV -> indirect PBE gap 0.3445 eV. `fermi_energy` in the XML
= 0.264180 Ha = 7.1887 eV (= VBM for this fixed-occupation insulator).

**5. QE DOS.** Wrote `qe/dos/SrCu2SnS4.dos.in` (outdir -> existing
`tmp/final`, Gaussian `ngauss=0, degauss=0.005 Ry = 0.068 eV`, Emin/Emax
-30..15 eV). Ran `dos.x`: `JOB DONE`, EFermi 7.189 eV. Sanity check: integrated
DOS reaches 210.0 electrons exactly at the VBM, and drops to ~0 across the gap.
(The `IEEE_OVERFLOW` note is harmless — it comes from the tiny e^-83 tails.)

**6. BoltzTraP2 DOS — three failures before it ran.**
  - a. `getBTPbands(...)` returned more values than expected; `BTPDOS` needs
       `vvband` as a positional arg. Fixed by inspecting the signatures and
       unpacking by index.
  - b. On macOS BoltzTraP2 uses `spawn` multiprocessing, which re-imports the
       script and crashed without a `if __name__ == "__main__":` guard. Added it.
  - c. NumPy 2 removed `np.trapz` (now `np.trapezoid`). Switched to a
       version-safe lookup.
  Once running: integral to E_F = 124.0 electrons, i.e. BoltzTraP2's loader keeps
  62 occupied bands and drops the deep semicore; its band window is only
  E_F +/- ~5.6 eV.

**7. Comparison.** Referenced both DOS to E_F. To compare on equal footing I
Gaussian-broadened the BoltzTraP2 DOS to the same 0.068 eV. Result within
`|E-E_F| < 5 eV`: relative L2 difference 6.6%, Pearson r = 0.9943. Plot shows the
native BoltzTraP2 curve is spikier (5x denser interpolated k-mesh) but overlays
QE once broadened; both reproduce the gap. Curves separate only at the window
edges where BoltzTraP2 has dropped semicore bands.

**8. Verification.** Re-checked the three SHA-256 hashes: all OK, and `dos.x`
created no new files under `tmp/final`. Raw records intact.

**9. Outputs.** Raw QE DOS -> `qe/dos/`; script -> `boltztrap2/dos_compare.py`;
derived plot/CSV/summary -> `results/`; this curated package -> the present
folder.

**Not done.** The Seebeck-coefficient-vs-Fermi-energy graph Roy also asked for.

**Limitations recorded.** QE-PBE gap (underestimated vs experiment), no explicit
SOC, Gaussian smearing rather than tetrahedra, single `12x12x6` grid; comparison
is only meaningful near E_F.

---

## 2026-07-02 — Seebeck graph centered on E_F; reply package staged

**Goal.** The second deliverable in Roy's email: "a graph of the Seebeck
Coefficient, centered on the Fermi Energy."

**1. No new runs needed.** The `btp2 integrate` step of the first pass already
produced a chemical-potential scan (`boltztrap2/SrCu2SnS4.trace`: 763 mu points
x 7 temperatures, 300-900 K). Reused it read-only.

**2. Understood the file conventions before plotting.**
  - The `.trace` S column is a scalar; verified against the full tensors in
    `SrCu2SnS4.condtens` that it equals the diagonal average
    (S_xx+S_yy+S_zz)/3 to 1.2e-5 relative.
  - The N column of the integrate trace is *relative* to the neutral cell
    (positive = electrons removed). First assumed it was the absolute count
    (124); the neutrality check printed 0.018 e/uc and exposed the wrong
    assumption; fixed the check text so the record is unambiguous.
  - Cross-checked the scan against the doped run: at 300 K, p-type 1e20 cm^-3,
    mu-scan interpolation gives 157.4 uV/K vs 157.2 uV/K in the dope trace —
    the same number already sent to Roy in the Excel package.

**3. Plot.** `boltztrap2/plot_seebeck.py` -> `results/seebeck_vs_mu.png/.csv`.
x = mu - E_F (E_F = 7.1887 eV = VBM), gap [0, 0.3445] eV shaded, 7 isotherms.
Classic bipolar S(mu): +644 / -548 uV/K in-gap extrema at 300 K, peaks
shrinking with T. Under CRTA tau cancels in S, so these are absolute calculated
values (PBE, no SOC, orientational average) — noted in `results/seebeck_vs_mu.md`.

**4. Package.** Renamed this folder from "(DOS comparison)" to
"(DOS and Seebeck)" since both deliverables of the same email now live here.
Added `EMAIL_DRAFT.md` (one bracketed placeholder left for Yuhan's
experimental-vs-computational answer — that decision is not mine to make),
`ATTACHMENTS.md`, and `READY_TO_ATTACH/` with four date-free attachments
(DOS png+csv, Seebeck png+csv). READY_TO_ATTACH is staged, not sent.

**5. Verification.** Protected raw files re-checked against the recorded
SHA-256 hashes after the Seebeck work: unchanged (plot_seebeck.py only reads).

---

## 2026-07-03 — sent as Folder 1 of the combined email; frozen

The combined email (authoritative draft in
`third step result (three-material first pass)/EMAIL_DRAFT.md`) was sent with
this package's `READY_TO_ATTACH/` as Folder 1 (`folder1.zip`, byte-verified
against the folder before sending). Roy replied approving the work.
`READY_TO_ATTACH/` is now frozen as the record of what was sent.
