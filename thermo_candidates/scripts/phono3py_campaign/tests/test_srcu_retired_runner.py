"""Safety gates for every archived SrCu2SnS4 execution entrypoint."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
CANONICAL = REPO / "thermo_candidates/SrCu2SnS4/phono3py/scripts/run_campaign.sh"
PACKAGE = REPO / "fourth step result (phono3py lattice thermal conductivity)/reproducibility"
SHELL_ENTRYPOINTS = (
    CANONICAL,
    PACKAGE / "run_campaign.sh",
    PACKAGE / "fetch_home.sh",
    PACKAGE / "slurm/collect_evidence.sh",
    PACKAGE / "slurm/submit_all.sh",
    PACKAGE / "slurm/stage0_checks.sbatch",
    PACKAGE / "slurm/stage1_array.sbatch",
    PACKAGE / "slurm/stage2_post.sbatch",
)
PYTHON_ENTRYPOINTS = (PACKAGE / "prepare_inputs.py", PACKAGE / "postprocess.py")
WRITE_OR_COMPUTE = re.compile(
    r"(?m)^(?!\s*#).*?(?:\bmkdir\b|\bsbatch\b|\bmpirun\b|\bsrun\b|\bpw\.x\b|"
    r"\brsync\b|\bgit (?:add|commit|push)\b|\bbash\s+scripts/|"
    r"(?:>>?|\d>>?)\s*[^&]).*$"
)


class SrCuRetiredRunnerTests(unittest.TestCase):
    def test_shell_entrypoints_guard_before_any_write_submission_or_qe(self) -> None:
        for path in SHELL_ENTRYPOINTS:
            with self.subTest(path=path):
                text = path.read_text()
                guard = re.search(r'(?m)^echo "\[retired\].*"\nexit 1$', text)
                self.assertIsNotNone(guard)
                assert guard is not None
                dangerous = WRITE_OR_COMPUTE.search(text, guard.end())
                self.assertIsNotNone(dangerous)
                assert dangerous is not None
                self.assertGreater(dangerous.start(), guard.end())

    def test_python_entrypoints_exit_as_the_first_main_action(self) -> None:
        for path in PYTHON_ENTRYPOINTS:
            with self.subTest(path=path):
                tree = ast.parse(path.read_text())
                main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                            and node.name == "main")
                self.assertIsInstance(main.body[0], ast.Expr)
                call = main.body[0].value
                self.assertIsInstance(call, ast.Call)
                self.assertIsInstance(call.func, ast.Attribute)
                self.assertEqual((call.func.value.id, call.func.attr), ("sys", "exit"))

    def test_primary_guards_execute_without_cluster_or_qe_environment(self) -> None:
        for path in SHELL_ENTRYPOINTS:
            with self.subTest(path=path):
                result = subprocess.run(["bash", str(path)], cwd=REPO,
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("[retired]", result.stdout + result.stderr)
        for path in PYTHON_ENTRYPOINTS:
            with self.subTest(path=path):
                result = subprocess.run([sys.executable, str(path)], cwd=REPO,
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("[retired]", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
