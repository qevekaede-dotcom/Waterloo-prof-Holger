# BoltzTraP2: Rb2Cu2SnS4

Use this folder after the dense QE NSCF calculation is complete.

Expected QE source:

```text
../qe/tmp/Rb2Cu2SnS4.save/data-file-schema.xml
```

Run template:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
bash boltztrap2/run_bt2.sh
```

The current commands are starter commands. Recheck interpolation multiplier,
temperature range, and doping range after inspecting the band structure.

