#!/usr/bin/env python3
"""Focused regression for phono3py's repeated nat/ntyp fragment comment."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_firstpass_forces import (
    AuditError,
    expected_fc_dataset_name,
    phono3py_drift_subtracted_quantized,
    setting_fingerprint,
)


class SettingFingerprintTest(unittest.TestCase):
    def test_phono3py_comment_does_not_duplicate_namelist_settings(self) -> None:
        text = """&CONTROL
 calculation='scf', tprnfor=.true., tstress=.true., verbosity='high'
/
&SYSTEM
 nat=40, ntyp=3, ecutwfc=80, ecutrho=640, occupations='fixed',
 nspin=1, tot_charge=0, nosym=.true., noinv=.true.
/
&ELECTRONS
 conv_thr=1e-10
/
&IONS
/
&CELL
/
!    ibrav = 0, nat = 40, ntyp = 3
CELL_PARAMETERS angstrom
1 0 0
0 1 0
0 0 1
K_POINTS automatic
3 3 3 0 0 0
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scf.in"
            path.write_text(text)
            settings = setting_fingerprint(path)
        self.assertEqual(settings["nat"], 40)
        self.assertEqual(settings["ntyp"], 3)
        self.assertEqual(settings["kmesh_and_shift"], [3, 3, 3, 0, 0, 0])

    def test_drift_removal_precedes_ten_decimal_quantization(self) -> None:
        displaced = [[1e-9, 6e-11, 0.0], [3e-9, 0.0, 0.0]]
        pristine = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        self.assertEqual(
            phono3py_drift_subtracted_quantized(displaced, pristine),
            [[-1e-9, 0.0, 0.0], [1e-9, -0.0, 0.0]],
        )

    def test_documented_fc_hdf5_dataset_names_only(self) -> None:
        self.assertEqual(expected_fc_dataset_name(2, ["force_constants", "p2s_map"]),
                         "force_constants")
        self.assertEqual(expected_fc_dataset_name(3, ["fc3", "p2s_map"]), "fc3")
        with self.assertRaises(AuditError):
            expected_fc_dataset_name(2, ["fc2", "p2s_map"])


if __name__ == "__main__":
    unittest.main()
