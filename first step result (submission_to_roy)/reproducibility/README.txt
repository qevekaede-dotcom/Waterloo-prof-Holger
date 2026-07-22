My SrCu2SnS4 calculation files

Structure source:
  Materials Project mp-16988; experimentally observed; ICSD-356

Software:
  Quantum ESPRESSO pw.x 7.5 development build
  BoltzTraP2 26.3.1

Settings I used after the convergence tests:
  ecutwfc / ecutrho: 90 / 720 Ry
  vc-relax k mesh: 4x4x2
  final SCF k mesh: 5x5x3
  dense NSCF k mesh: 12x12x6
  NSCF bands: 140 total; 105 occupied

Files I included:
  QE relax, SCF, and NSCF input files
  cutoff and k-point convergence CSV files
  my calculation notes in Markdown

I left out the raw wavefunctions, charge density, and temporary folders because
they are too large for email. I still have the original logs locally.
