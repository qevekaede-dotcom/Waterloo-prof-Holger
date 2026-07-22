# Work log: three-material first-pass report package

Append-only. Newest entry at the bottom.

---

## 2026-07-03 — package assembled

**Context.** All three first-pass workflows are complete (SrCu2SnS4 earlier;
SrZrS3 and Rb2Cu2SnS4 finished 2026-07-02/03 - see their WORKLOGs). Roy's
30 June email had greenlit proceeding to the other crystals, so this package
reports the full three-material comparison. The DOS+Seebeck reply in
`second step result (DOS and Seebeck)/` is unchanged.

**What was assembled.**
- Copied the three relaxed CIFs into `READY_TO_ATTACH/`.
- Built `three_material_transport_best_power_factor.csv` by prefixing each
  material's `results/transport_best_power_factor.csv` with a material column
  (14 rows each, 42 data rows).
- Wrote `three_material_comparison.csv` (machine-readable) and
  `three_material_comparison.md` (readable) from the three
  `results/workflow_summary.md` files and the material READMEs (database gaps
  and predicted zT).
- Drafted `EMAIL_DRAFT.md` in the first-person student voice, echoing the
  house-rule caveats (PF/tau not absolute; zT_e electronic-only upper bound;
  no SOC; best-on-grid; per-material convergence). Left one `[Yuhan: ...]`
  placeholder for the experimental-vs-computational answer.

**Numbers, all traced to source [calculated unless noted]:**
- gaps 0.3445 / 0.6096 / 0.7811 eV (workflow_summary.md files);
  listed gaps 0.4032 / 0.5512 / 0.8641 eV [database] (material README.md);
- cutoffs 90/720, 50/400, 90/720 Ry; NSCF 12x12x6(100)/20x10x6(264)/8x14x14(788);
- volume drift +0.48 / +0.63 / +0.93%;
- favored carrier by zT_e: p / n / p.

**Not sent.** `READY_TO_ATTACH/` is staged; freeze on send.

**Update (same day).** The user supplied their answer to Roy's
experimental-vs-computational question (leans computational; open to wet-lab
because a calculation is not complete without experimental validation; has time
through the final year to learn properly). Transcribed into the email in the
existing modest first-person tone, replacing the `[Yuhan: ...]` placeholder.
The same paragraph was added to the DOS/Seebeck draft. No placeholders remain in
either draft; neither has been sent. If the two emails are sent separately, keep
the paragraph in only one to avoid repeating it to Roy.

---

## 2026-07-03 — figures added; single combined email; verified label fix

**1. Verification fix.** An adversarial fact-check of the package confirmed
every number but caught one mislabeled row: "zT_e at best-PF/tau point" was
actually the highest sampled zT_e (e.g. SrCu2SnS4's 1.898 sits at 800 K/p/5e20,
not at its largest-PF point, where zT_e = 1.356). Renamed the row to "Highest
sampled zT_e, at its own (T, carrier, density)" in both comparison files;
numbers unchanged.

**2. Seebeck figures for the two new materials.** `plot_seebeck.py` cloned
from the verified SrCu2SnS4 version into each material's `boltztrap2/`
(prefix, gap shading 0.6096 / 0.7811 eV, plot window widened to the larger
gaps). Outputs -> each material's `results/seebeck_vs_mu.png/.csv`. Built-in
cross-checks passed: trace-vs-condtens diagonal average 1.7e-5; dope-vs-scan
agreement 0.1 uV/K (SrZrS3 n 1e20: -91.1 vs -91.2; Rb2Cu2SnS4 p 1e20: 331.5 vs
331.6). One honest flag: Rb2Cu2SnS4's charge-neutrality interpolation residual
at E_F is +0.211 e/uc (vs +0.005 SrZrS3, +0.018 SrCu2SnS4) because its valence
DOS is high and steep at the VBM (flat bands), so N(mu) rises sharply within
one mu-grid step; the dope-based check shows the S curves are unaffected.

**3. Three-material transport figure.**
`thermo_candidates/scripts/plot_three_material_transport.py` (new,
material-agnostic) -> `results/three_material_transport_comparison.png`:
left panel best sampled PF/tau vs T (log scale, labeled per-tau/not absolute),
right panel electronic-only zT_e at those points (labeled upper bound, no
kappa_L). Both panels carry the shared-grid and no-SOC caveats in the titles.

**4. Send plan switched to one combined email with two folders** (user's
decision): Folder 1 = DOS+Seebeck package attachments, Folder 2 = this
package's 11 files (tables + 3 figures + 2 Seebeck CSVs + 3 CIFs).
`EMAIL_DRAFT.md` here rewritten as the combined reply (covers DOS comparison,
SrCu2SnS4 Seebeck, three-material report, and the experimental-vs-computational
answer once); the second-step draft is marked SUPERSEDED, never sent.
`ATTACHMENTS.md` updated to the two-folder plan.

---

## 2026-07-03 — second verification round: gap-claim error caught and fixed

A three-lens adversarial verification (figures/data, package consistency,
email/house-rules) was run on the staged send.

**Critical catch, fixed everywhere:** the email, the attached comparison, and
this README claimed all three calculated gaps sit *below* the listed database
gaps "as PBE expects". FALSE for SrZrS3: calculated 0.6096 eV > listed
0.5512 eV. Also the justification was flawed - PBE's underestimation applies
vs *experiment*, while the listed gaps are themselves DFT-derived database
values. All three files rewritten to: ordering matches (0.3445 < 0.6096 <
0.7811 vs 0.4032 < 0.5512 < 0.8641 eV); two sit below and SrZrS3 slightly
above; read the ordering, not the offsets; PBE still expected to underestimate
the true experimental gaps. Working copy in `results/` resynced. A repo-wide
grep confirms no residual "all below" claim.

**Also fixed:** README stale "six files" -> eleven + results/ line now
mentions the figure; email's SrZrS3 carrier-disagreement sentence qualified
(disagreement holds at >= 500 K; both metrics pick n-type at 300-400 K);
email's Folder-2 description now mentions the combined transport CSV and the
three CIFs; reproducibility README notes SrCu2SnS4's deeper convergence-CSV
paths; second-step README now marks its draft SUPERSEDED.

**Left unchanged (reviewer nit, declined):** the "p-type side (S > 0)"
corner annotations on the Seebeck figures - at low T the hole-doped side has
narrow S<0 wiggles, but the annotation is the conventional reading, the data
is plotted as-is, and the SrCu2SnS4 figure Roy already has uses the same
convention; changing it now would break format consistency.

**Verdict after fixes:** figures/data lens passed as-is; all critical issues
from the other two lenses resolved. Staged and ready for the user to send.

**Rigor self-review.** Every number in the package traces to a QE/BoltzTraP2
derived file cited in reproducibility/README.txt; units carried in all
column headers; [calculated]/[database] tags applied; no PF/tau-as-absolute,
no zT_e-as-final-zT, no-SOC and best-on-grid caveats present; per-material
convergence preserved. No dates in the email body or attachment filenames.

---

## 2026-07-03 — sent; Roy's reply; both READY_TO_ATTACH folders frozen

**1. Sent.** The user sent the combined email from Outlook (reply in the
"Update on my first SrCu2SnS4 calculation" thread) with `folder1.zip`
(4 files) and `folder2.zip` (11 files). Before sending, both zips were
byte-verified against the two `READY_TO_ATTACH/` folders and the Outlook
draft was checked on screen (recipient, both attachments, corrected gap
wording, no internal Note pasted). The temporary top-level zips were removed
after sending; both packages' `READY_TO_ATTACH/` folders are now frozen.

**2. Roy's reply.** "This is all great work! You've picked up this stuff
really quickly." Computational focus approved with no wet-lab obligation.
New task: try **phono3py** for phonon work — the professor recommended it,
Roy never got it to run: "give it a go, and let me know if / how you get it
working!"

**3. Meaning.** phono3py computes anharmonic (third-order) interatomic force
constants and phonon-phonon scattering, i.e. the **lattice thermal
conductivity kappa_L** — exactly the ingredient every zT_e caveat in the
sent packages says is missing. The phonon workflow becomes the fourth task;
its records will live under `thermo_candidates/<material>/` with a new
step-result package when there is something to send.
