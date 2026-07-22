# BoltzTraP2: SrZrS3

Use this folder after the dense QE NSCF calculation is complete.

Expected QE source:

```text
../qe/tmp/SrZrS3.save/data-file-schema.xml
```

Run template:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
bash boltztrap2/run_bt2.sh
```

The current commands are starter commands. Recheck interpolation multiplier,
temperature range, and doping range after inspecting the band structure.

