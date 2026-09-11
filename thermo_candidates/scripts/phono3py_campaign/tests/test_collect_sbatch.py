from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


COLLECT_SCRIPT = Path(__file__).resolve().parents[1] / "slurm" / "collect.sbatch"


class CollectorSlurmScriptTests(unittest.TestCase):
    def test_collector_uses_the_trusted_sacct_path_not_inherited_path(self) -> None:
        text = COLLECT_SCRIPT.read_text()
        self.assertIn('[[ -x "$P3_SACCT" ]]', text)
        self.assertIn('LC_ALL=C "$P3_SACCT"', text)
        self.assertNotIn("command -v sacct", text)

    def test_accounting_poll_preserves_queries_and_waits_for_terminal_array(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        run_dir = root / "run"
        bundle = run_dir / "force" / "bundle"
        bundle.mkdir(parents=True)
        task_map = bundle / "task_map.tsv"
        task_map.write_text(
            "task_id\tdisplacement_id\trole\tinput_path\tinput_sha256\n"
            "0\t0\tpristine\t/input-0\t" + "0" * 64 + "\n"
            "1\t1\tdisplacement\t/input-1\t" + "1" * 64 + "\n"
        )
        manifest = bundle / "force_manifest.json"
        manifest.write_text("{}\n")

        slurm_dir = root / "slurm"
        slurm_dir.mkdir()
        (slurm_dir / "cluster.env").write_text(
            """
p3_require_compute_node() { :; }
p3_require_context() { :; }
p3_die() { printf 'ERROR: %s\\n' "$*" >&2; exit 2; }
p3_require_file() { [[ -f "$2" ]] || p3_die "$1 does not exist: $2"; }
p3_begin_attempt() {
    P3_ATTEMPT_DIR="$RUN_DIR/slurm_attempts/$1/$ATTEMPT_ID"
    mkdir -p "$P3_ATTEMPT_DIR"
    export P3_ATTEMPT_DIR
}
p3_activate_python() { :; }
p3_run_cli() { printf '%s\\n' "$@" > "$P3_ATTEMPT_DIR/cli_args.txt"; }
P3_SACCT="${FAKE_SACCT:?}"
"""
        )
        fake_bin = root / "bin"
        fake_bin.mkdir()
        counter = root / "sacct-counter.txt"
        sacct = fake_bin / "sacct"
        sacct.write_text(
            """#!/bin/bash
count=0
[[ ! -f "$FAKE_SACCT_COUNTER" ]] || count="$(<"$FAKE_SACCT_COUNTER")"
count=$((count + 1))
printf '%s\\n' "$count" > "$FAKE_SACCT_COUNTER"
printf '%s\\n' '900_0|901|COMPLETED|0:0|120|32|'
printf '%s\\n' '900_0.batch|901.batch|COMPLETED|0:0|120|32|128M'
if [[ "$count" -eq 1 ]]; then
    printf '%s\\n' '900_1|902|RUNNING|0:0|20|32|'
else
    printf '%s\\n' '900_1|902|FAILED|1:0|80|32|'
    printf '%s\\n' '900_1.batch|902.batch|FAILED|1:0|80|32|96M'
fi
"""
        )
        sacct.chmod(0o755)
        sleep = fake_bin / "sleep"
        sleep.write_text("#!/bin/bash\nexit 0\n")
        sleep.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": str(fake_bin) + os.pathsep + env["PATH"],
                "P3_SLURM_DIR": str(slurm_dir.resolve()),
                "RUN_DIR": str(run_dir.resolve()),
                "ATTEMPT_ID": "collector-1",
                "PRIMARY_STAGE": "force",
                "PRIMARY_ATTEMPT_ID": "force-primary-1",
                "PRIMARY_JOB_ID": "900",
                "TASK_MAP": str(task_map.resolve()),
                "FORCE_MANIFEST": str(manifest.resolve()),
                "PRIMARY_TASK_MAP_SHA256": "a" * 64,
                "PRIMARY_FORCE_MANIFEST_SHA256": "b" * 64,
                "SLURM_JOB_ID": "999",
                "FAKE_SACCT_COUNTER": str(counter),
                "FAKE_SACCT": str(sacct),
            }
        )
        completed = subprocess.run(
            ["bash", str(COLLECT_SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        attempt = run_dir / "slurm_attempts" / "collect" / "collector-1"
        self.assertEqual((attempt / "primary_sacct_query_count.txt").read_text(), "2\n")
        self.assertTrue((attempt / "primary_sacct-query-01.psv").is_file())
        self.assertTrue((attempt / "primary_sacct-query-02.psv").is_file())
        canonical = (attempt / "primary_sacct.psv").read_text()
        self.assertIn("900_1|902|FAILED|1:0|80|32|", canonical)
        arguments = (attempt / "cli_args.txt").read_text().splitlines()
        self.assertEqual(arguments[0], "collect")
        self.assertIn("--primary-attempt-id", arguments)
        self.assertIn("force-primary-1", arguments)
        self.assertIn("--expect-force-manifest-sha", arguments)
        self.assertIn("b" * 64, arguments)


if __name__ == "__main__":
    unittest.main()
