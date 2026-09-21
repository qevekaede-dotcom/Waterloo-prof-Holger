# Waterloo phonon research update

[Download/open the English PPTX](output/Waterloo_Phonon_Research_Update.pptx)

[Read the bilingual English/Chinese speaking script](SPEAKER_SCRIPT_EN_ZH.md)

11 slides, intended for an approximately 10-minute progress discussion with Holger and Roy. Every slide and embedded speaker note is English. Chinese is confined to the separate speaking script. The deck contains three native editable charts and two native editable tables, plus an existing project DOS figure.

The presentation reports electronic first passes, known limitations of the phonon evidence, and proposed research choices. It is not a claim of accepted lattice thermal conductivity and was not sent to anyone. Saved audit JSON is a historical evidence source, not a new remote HDF5 or live cluster check.

## Reproduce

Run from the repository root:

```sh
python3 experiments/phonon_research_sandbox/presentation/reproducibility/extract_deck_data.py
```

`reproducibility/deck_data.json` retains source-file SHA-256 values and unrounded extracted data. Chart values are rounded to 10 significant digits only when authoring the presentation, within Excel precision, and visible bar labels use two decimals. Scientific source files are unchanged. Rb consecutive changes use the **current, denser** mesh as denominator.

The JavaScript builder uses the supplied `@oai/artifact-tool` presentation runtime. Resolve runtime paths with Codex workspace dependencies, then set `RESEARCH_ROOT`, `PRESENTATIONS_SKILL`, `RUNTIME_PYTHON`, and `RUNTIME_NODE_MODULES` to the actual paths. Copy `reproducibility/build_deck.mjs` into `.build/`, link `.build/node_modules` to the runtime package directory, and execute the copied file with the runtime Node executable. `FINAL_NAME` selects a new output filename for revisions; the finalizer intentionally refuses to overwrite an existing final artifact. `.build/` and temporary chart snapshots are excluded from Git.

Package/layout/font checks, source-linked numeric checks and rendered slide inspection are recorded in the parent validation report. Native PowerPoint application behavior has not been tested; the file has been reimported and rendered through the artifact runtime. Chart workbooks contain authored data snapshots, not formulas or links to external research files.
