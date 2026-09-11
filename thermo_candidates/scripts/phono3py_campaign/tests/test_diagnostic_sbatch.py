from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


CAMPAIGN_DIR = Path(__file__).resolve().parents[1]
DIAGNOSTIC = CAMPAIGN_DIR / "slurm/diagnostic.sbatch"
PREFLIGHT = CAMPAIGN_DIR / "slurm/preflight.sbatch"
CLUSTER_ENV = CAMPAIGN_DIR / "slurm/cluster.env"


class SlurmStageContractTests(unittest.TestCase):
    def test_diagnostic_is_one_shot_runtime_only_and_has_no_implicit_resources(self) -> None:
        text = DIAGNOSTIC.read_text()
        for forbidden in (
            "#SBATCH --partition=",
            "#SBATCH --nodes=",
            "#SBATCH --ntasks=",
            "#SBATCH --cpus-per-task=",
            "#SBATCH --mem",
            "#SBATCH --time=",
            "finalize-diagnostic",
            "release-polish",
            "collect.sbatch",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('[[ ! -e "$RUN_DIR/run_manifest.json" ]]', text)
        self.assertIn("P3_DIAGNOSTIC_RESOURCE_SHA256", text)
        self.assertIn("P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES", text)
        self.assertIn("p3_begin_attempt diagnostic", text)
        self.assertIn("polish_recovery.py\" run-diagnostic", text)
        self.assertIn('--attempt-id "$ATTEMPT_ID"', text)
        self.assertLess(
            text.index("p3_begin_attempt diagnostic"),
            text.index("polish_recovery.py\" run-diagnostic"),
        )

    def test_diagnostic_atomically_consumes_dispatch_before_setup(self) -> None:
        text = DIAGNOSTIC.read_text()
        claim = text.index('diagnostic_claim="$RUN_DIR/diagnostic/dispatch_claim"')
        begin = text.index("p3_begin_attempt diagnostic")
        load_qe = text.index("p3_load_qe")
        run = text.index("polish_recovery.py\" run-diagnostic")
        self.assertLess(claim, begin)
        self.assertLess(begin, load_qe)
        self.assertLess(load_qe, run)
        self.assertIn('mkdir "$diagnostic_claim"', text)

    def test_preflight_forwards_ids_and_signature_and_context_records_them(self) -> None:
        preflight = PREFLIGHT.read_text()
        context = CLUSTER_ENV.read_text()
        self.assertIn("P3_PREFLIGHT_CANDIDATE_IDS", preflight)
        self.assertIn("P3_PREFLIGHT_CANDIDATE_SHA256", preflight)
        self.assertIn('candidate_args+=(--candidate-id "$candidate_id")', preflight)
        self.assertIn("--expect-candidate-subset-sha", preflight)
        self.assertIn('p3_run_cli preflight "${candidate_args[@]}"', preflight)
        self.assertIn("preflight_candidate_ids", context)
        self.assertIn("preflight_candidate_subset_sha256", context)

    def test_cluster_runtime_is_versioned_and_not_caller_overridable(self) -> None:
        text = CLUSTER_ENV.read_text()
        self.assertIn("unset BASH_ENV ENV CDPATH GLOBIGNORE PYTHONHOME PYTHONPATH", text)
        self.assertIn('CAMPAIGN_CLI="$P3_CAMPAIGN_DIR/campaign.py"', text)
        self.assertIn('export STDENV_MODULE="StdEnv/2023"', text)
        self.assertIn('export QE_MODULE="quantumespresso/7.3.1"', text)
        self.assertIn('export P3_SACCT="/opt/software/slurm/bin/sacct"', text)
        self.assertIn('export QE_EXECUTABLE="pw.x"', text)
        self.assertIn('export QE_MPI_LAUNCHER="srun"', text)
        self.assertIn('export QE_NK="1"', text)
        self.assertIn('export P3_VENV="$P3_ACCOUNT_HOME/venvs/p3"', text)
        self.assertIn(
            'export P3_PSEUDO_DIR="$P3_ACCOUNT_HOME/pseudos/SSSP-1.3.0-PBE-precision"',
            text,
        )
        self.assertIn("p3_account_uid", text)
        self.assertIn("p3_account_home", text)
        for forbidden in (
            "${CAMPAIGN_CLI:-",
            "${STDENV_MODULE:-",
            "${QE_MODULE:-",
            "${P3_SACCT:-",
            "${P3_VENV:-",
            "${P3_PSEUDO_DIR:-",
            "${QE_EXECUTABLE:-",
            "${QE_MPI_LAUNCHER:-",
            "${QE_NK:-",
            "${OMP_NUM_THREADS:-",
        ):
            self.assertNotIn(forbidden, text)

    def test_modified_shell_files_parse(self) -> None:
        completed = subprocess.run(
            ["bash", "-n", str(DIAGNOSTIC), str(PREFLIGHT), str(CLUSTER_ENV)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
