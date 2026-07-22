How to reproduce the SrCu2SnS4 DOS comparison

Prerequisite: the SrCu2SnS4 dense NSCF must already exist at
  thermo_candidates/SrCu2SnS4/qe/tmp/final/SrCu2SnS4.save/
(it does; it was not re-run for this task).

Software:
  Quantum ESPRESSO dos.x (same build as the first-pass pw.x)
  BoltzTraP2 (thermo-bt2 conda env)

Steps (run from thermo_candidates/SrCu2SnS4/):
  source "$HOME/scientific-tools/env/thermo-bt2.sh"

  # 1. QE DOS on the existing NSCF eigenvalues (Gaussian, 0.005 Ry = 0.068 eV)
  dos.x -in qe/dos/SrCu2SnS4.dos.in > qe/dos/SrCu2SnS4.dos.out

  # 2. BoltzTraP2 DOS + overlay + agreement metrics -> results/
  python boltztrap2/dos_compare.py

  # 3. Seebeck vs chemical potential, centered on E_F -> results/
  python boltztrap2/plot_seebeck.py

Files in this folder:
  SrCu2SnS4.dos.in   QE dos.x input actually used
  SrCu2SnS4.dos.out  QE dos.x run log (JOB DONE, EFermi 7.189 eV)
  dos_compare.py     analysis script (copy of boltztrap2/dos_compare.py)
  plot_seebeck.py    Seebeck script (copy of boltztrap2/plot_seebeck.py)

Reference values to check against:
  E_F (= VBM)            7.1887 eV
  indirect PBE gap       0.3445 eV
  electrons below E_F    210.0 (QE dos.x) / 124.0 (BoltzTraP2, semicore dropped)
  near-gap agreement     Pearson r 0.9943, relative L2 6.6% (|E-E_F| < 5 eV)
