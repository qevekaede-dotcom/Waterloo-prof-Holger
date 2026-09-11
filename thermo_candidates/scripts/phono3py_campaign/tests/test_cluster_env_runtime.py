from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


CAMPAIGN_DIR = Path(__file__).resolve().parents[1]
CLUSTER_ENV = CAMPAIGN_DIR / "slurm/cluster.env"
MODULE_INIT_LINE = (
    'export P3_MODULE_INIT="/cvmfs/soft.computecanada.ca/config/profile/bash.sh"'
)
ACCOUNT_HOME_BLOCK = """\
P3_ACCOUNT_UID="$(command -p id -u)"
P3_PASSWD_RECORD="$(command -p getent passwd "$P3_ACCOUNT_UID")"
IFS=: read -r _ _ _ _ _ P3_ACCOUNT_HOME _ <<< "$P3_PASSWD_RECORD"
[[ "$P3_ACCOUNT_HOME" == /* && "$P3_ACCOUNT_HOME" != "/" ]] \\
    || { printf 'ERROR: cannot derive a safe scheduler-account home\\n' >&2; exit 2; }
"""


class ClusterEnvModuleInitTests(unittest.TestCase):
    def _run_with_profile(self, profile_text: str, invocation: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            account_home = root / "account-home"
            account_home.mkdir()
            qe_executable = fake_bin / "pw.x"
            qe_executable.write_text("#!/usr/bin/env bash\nexit 0\n")
            qe_executable.chmod(0o755)
            srun = fake_bin / "srun"
            srun.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "[[ \"${SLURM_EXPORT_ENV:-}\" == \"ALL\" ]]\n"
                "command -v \"$1\" >/dev/null\n"
                "exec \"$@\"\n"
            )
            srun.chmod(0o755)
            venv_bin = account_home / "venvs/p3/bin"
            venv_bin.mkdir(parents=True)
            activation = venv_bin / "activate"
            activation.write_text(f'PATH="{venv_bin}:$PATH"\nexport PATH\n')
            python = venv_bin / "python"
            python.write_text("#!/usr/bin/env bash\nexit 0\n")
            python.chmod(0o755)

            profile = root / "profile.sh"
            profile.write_text(profile_text)
            runtime_copy = root / "cluster.env"
            runtime = CLUSTER_ENV.read_text().replace(
                    MODULE_INIT_LINE,
                    f'export P3_MODULE_INIT="{profile}"',
                    1,
                )
            runtime = runtime.replace(
                ACCOUNT_HOME_BLOCK,
                "\n".join(
                    (
                        'P3_ACCOUNT_UID="test-uid"',
                        'P3_PASSWD_RECORD="test:x:test-uid:test-uid::' + str(account_home) + ':/bin/bash"',
                        'P3_ACCOUNT_HOME="' + str(account_home) + '"',
                        '[[ "$P3_ACCOUNT_HOME" == /* && "$P3_ACCOUNT_HOME" != "/" ]] || exit 2',
                        "",
                    )
                ),
            )
            runtime_copy.write_text(runtime)
            self.assertNotEqual(runtime, CLUSTER_ENV.read_text())
            env = os.environ | {
                "P3_TEST_FAKE_BIN": str(fake_bin),
                "SLURM_EXPORT_ENV": "CAMPAIGN_CONFIG,RUN_DIR",
            }
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -euo pipefail\n"
                    "export SLURM_CPUS_PER_TASK=1\n"
                    f"source {runtime_copy!s}\n"
                    f"{invocation}\n",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

    def test_module_profile_can_read_unset_optional_variable_under_nounset(self) -> None:
        completed = self._run_with_profile(
            """\
if [[ "$SKIP_CC_CVMFS" == "1" ]]; then
    :
fi
PATH="$P3_TEST_FAKE_BIN:$PATH"
module() { return 0; }
""",
            'p3_load_qe\n[[ "$-" == *u* ]]\n[[ "$SLURM_EXPORT_ENV" == "ALL" ]]',
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_runtime_overrides_restricted_sbatch_export_for_srun_steps(self) -> None:
        completed = self._run_with_profile(
            "PATH=\"$P3_TEST_FAKE_BIN:$PATH\"\nmodule() { return 0; }\n",
            'p3_load_qe\np3_activate_python\n'
            '[[ "$SLURM_EXPORT_ENV" == "ALL" ]]\n'
            '[[ "$(declare -p SLURM_EXPORT_ENV)" == '
            "'declare -rx SLURM_EXPORT_ENV=\"ALL\"' ]]\n"
            '[[ "$(command -v pw.x)" == "$P3_TEST_FAKE_BIN/pw.x" ]]\n'
            'srun pw.x',
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_runtime_still_fails_closed_when_module_lacks_qe(self) -> None:
        completed = self._run_with_profile(
            "PATH=\"/usr/bin:/bin\"\nmodule() { return 0; }\n",
            "p3_load_qe",
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn("QE executable not found after module load", completed.stderr)

    def test_shell_options_are_restored_when_module_profile_fails(self) -> None:
        completed = self._run_with_profile(
            "false\n",
            'set +e\nif p3_load_qe; then exit 1; fi\n[[ "$-" == *u* ]]',
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Alliance module initialization failed", completed.stderr)

if __name__ == "__main__":
    unittest.main()
