# Second step: DOS comparison and Seebeck graph (SrCu2SnS4)

This folder is the tidy result package answering Roy's follow-up email after the
first submission. It mirrors the layout of
`first step result (submission_to_roy)/`.

Roy asked for two deliverables; both are complete:

1. **DOS**: run a DOS with QE and compare it to the BoltzTraP2 DOS.
2. **Seebeck**: a graph of the Seebeck coefficient centered on the Fermi energy.

He also gave the go-ahead to proceed to the other crystals' convergence; that
work runs in the material workspaces under `thermo_candidates/` and will get its
own step-result package when there is something to send.

## What is here

```text
README.md          - this file
WORKLOG.md         - step-by-step log of how each result was produced
EMAIL_DRAFT.md     - SUPERSEDED, kept for the record: the send plan changed to
                     one combined email whose authoritative draft lives in
                     "../third step result (three-material first pass)/";
                     this package's READY_TO_ATTACH/ is Folder 1 of that email
ATTACHMENTS.md     - what to attach
READY_TO_ATTACH/   - staged attachments (frozen only after actually sent)
results/           - curated deliverables
  dos_qe_vs_boltztrap2.png / .csv  - DOS overlay and data
  dos_comparison.md                - DOS method, agreement metrics, limitations
  seebeck_vs_mu.png / .csv         - S(mu) at 300-900 K, centered on E_F
  seebeck_vs_mu.md                 - Seebeck method, checks, limitations
reproducibility/   - exact inputs and scripts to regenerate everything
  SrCu2SnS4.dos.in / .dos.out      - QE dos.x input and run log
  dos_compare.py                   - DOS comparison script
  plot_seebeck.py                  - Seebeck plot script (3 cross-checks)
  README.txt                       - how to reproduce, reference values
```

## Authoritative records

This folder holds curated copies for presentation. The authoritative records
stay in `thermo_candidates/SrCu2SnS4/` (`qe/dos/`, `boltztrap2/`, `results/`)
and were not modified.

## One-line results

- QE `dos.x` and BoltzTraP2 give the same DOS near E_F (Pearson r = 0.9943
  within +/-5 eV after matching the 0.068 eV broadening); both show the same
  0.3445 eV QE-PBE indirect gap.
- The Seebeck scan is bipolar around the gap with 300 K in-gap extrema of
  +644 / -548 uV/K, tau-independent under CRTA, and reproduces the doped-grid
  value 157.2 uV/K (p-type 1e20 cm^-3, 300 K) already sent to Roy.
