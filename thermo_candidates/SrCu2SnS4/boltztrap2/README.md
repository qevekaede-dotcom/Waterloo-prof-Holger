# BoltzTraP2: SrCu2SnS4

Use this folder after the dense QE NSCF calculation is complete.

Expected QE source:

```text
../qe/tmp/final/SrCu2SnS4.save/data-file-schema.xml
```

Run template:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
bash boltztrap2/run_bt2.sh
```

The workflow uses interpolation multiplier 5, temperatures from 300 to 900 K,
and carrier concentrations from `1e19` to `1e21 cm^-3` for both carrier signs.
Positive concentration is p-type (electrons removed); negative concentration
is n-type (electrons added).

Create compact CSV and Markdown summaries with:

```bash
python boltztrap2/summarize_transport.py
```

The reported `zT_e` excludes lattice thermal conductivity and is only an
electronic upper bound. Full zT additionally needs a relaxation time and
lattice thermal conductivity.
