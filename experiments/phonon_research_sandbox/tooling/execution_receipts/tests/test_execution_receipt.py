from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
TOOL = PACKAGE / "execution_receipt.py"
TRACKED_WORKER = PACKAGE / "examples/synthetic_worker.py"
PYTHON = Path(sys.executable).resolve()


class Fixture:
    def __init__(self, root: Path, worker: Path = TRACKED_WORKER):
        self.root = root
        self.runs = root / "runs"
        self.anchors = root / "anchors"
        self.cwd = root / "cwd"
        for directory in (self.runs, self.anchors, self.cwd):
            directory.mkdir()
        self.input = root / "synthetic.in"
        self.pseudo = root / "synthetic.upf"
        self.input.write_bytes(b"SYNTHETIC INPUT\nline 2\n")
        self.pseudo.write_bytes(b"SYNTHETIC PSEUDO\n")
        self.worker = worker

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def record(self, run_id: str, *, execute: bool = True, exit_code: int = 0,
               env: list[str] | None = None, input_path: Path | None = None,
               pseudo_path: Path | None = None, worker: Path | None = None):
        worker = worker or self.worker
        command = [
            sys.executable, str(TOOL), "record",
            "--run-root", str(self.runs),
            "--anchor-dir", str(self.anchors),
            "--run-id", run_id,
            "--input", str(input_path or self.input),
            "--pseudo", f"Synthetic={pseudo_path or self.pseudo}",
            "--command-file", f"synthetic_worker={worker}",
            "--cwd", str(self.cwd),
        ]
        for item in env or []:
            command += ["--env", item]
        if execute:
            command.append("--execute")
        command += ["--", str(PYTHON), str(worker), "--exit-code", str(exit_code)]
        return subprocess.run(command, text=True, capture_output=True)

    def verify(self, run_id: str, anchor_id: str | None = None):
        anchor_id = anchor_id or run_id
        return subprocess.run([
            sys.executable, str(TOOL), "verify",
            "--run-dir", str(self.runs / run_id),
            "--anchor-file", str(self.anchors / f"{anchor_id}.anchor.json"),
        ], text=True, capture_output=True)


class ExecutionReceiptTests(unittest.TestCase):
    def test_default_is_nonmutating_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            result = fixture.record(run_id, execute=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["mode"], "dry_run")
            self.assertFalse(plan["shell"])
            self.assertIn("recorder-owned bytes", plan["stdin_binding"])
            self.assertFalse((fixture.runs / run_id).exists())
            self.assertFalse((fixture.anchors / f"{run_id}.anchor.json").exists())

    def test_success_binds_stdin_and_verifies_against_external_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            recorded = fixture.record(run_id)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            run_dir = fixture.runs / run_id
            self.assertEqual((run_dir / "stdin.snapshot").read_bytes(), fixture.input.read_bytes())
            expected = hashlib.sha256(fixture.input.read_bytes()).hexdigest()
            self.assertIn(expected, (run_dir / "stdout.bin").read_text())
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            report = json.loads(verified.stdout)
            self.assertEqual(report["status"], "verified_success")
            self.assertTrue(report["integrity_ok"])
            self.assertEqual(report["evidence_scope"], "standalone local protocol evidence only")
            self.assertFalse(report["integrated_with_phono3py_v2"])
            self.assertFalse(report["production_qe_provenance_verified"])
            self.assertFalse(report["scientific_acceptance"])

            copied_anchor = run_dir / "copied.anchor.json"
            shutil.copyfile(fixture.anchors / f"{run_id}.anchor.json", copied_anchor)
            inside = subprocess.run([
                sys.executable, str(TOOL), "verify",
                "--run-dir", str(run_dir), "--anchor-file", str(copied_anchor),
            ], text=True, capture_output=True)
            self.assertEqual(inside.returncode, 2)
            self.assertIn("outside the run directory", inside.stdout)

    def test_existing_run_identity_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            self.assertEqual(fixture.record(run_id).returncode, 0)
            receipt = (fixture.runs / run_id / "receipt.json").read_bytes()
            repeated = fixture.record(run_id)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("cannot be overwritten", repeated.stderr)
            self.assertEqual((fixture.runs / run_id / "receipt.json").read_bytes(), receipt)

    def test_mutable_input_and_pseudo_drift_are_distinguished(self):
        for source in ("input", "pseudo"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp))
                run_id = fixture.new_id()
                self.assertEqual(fixture.record(run_id).returncode, 0)
                target = fixture.input if source == "input" else fixture.pseudo
                target.write_bytes(target.read_bytes() + b"drift\n")
                verified = fixture.verify(run_id)
                self.assertEqual(verified.returncode, 5, verified.stdout + verified.stderr)
                report = json.loads(verified.stdout)
                self.assertEqual(report["status"], "source_drift")
                self.assertIn(source, json.dumps(report))

    def test_nonzero_exit_is_complete_evidence_but_failed_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            recorded = fixture.record(run_id, exit_code=7)
            self.assertEqual(recorded.returncode, 3, recorded.stdout + recorded.stderr)
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 3, verified.stdout + verified.stderr)
            report = json.loads(verified.stdout)
            self.assertTrue(report["integrity_ok"])
            self.assertFalse(report["execution_succeeded"])
            self.assertEqual(report["status"], "verified_nonzero_exit")
            self.assertEqual(report["exit_code"], 7)

    def test_altered_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            self.assertEqual(fixture.record(run_id).returncode, 0)
            with (fixture.runs / run_id / "stdout.bin").open("ab") as stream:
                stream.write(b"altered\n")
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 2)
            self.assertEqual(json.loads(verified.stdout)["status"], "invalid")
            self.assertIn("stdout digest mismatch", verified.stdout)

    def test_swapped_receipt_is_rejected_by_anchor_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            first, second = fixture.new_id(), fixture.new_id()
            self.assertEqual(fixture.record(first).returncode, 0)
            self.assertEqual(fixture.record(second).returncode, 0)
            shutil.copyfile(fixture.runs / second / "receipt.json", fixture.runs / first / "receipt.json")
            verified = fixture.verify(first)
            self.assertEqual(verified.returncode, 2)
            self.assertIn("independent anchor", verified.stdout)

    def test_symlinked_source_and_evidence_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            linked = fixture.root / "linked.in"
            linked.symlink_to(fixture.input)
            rejected = fixture.record(fixture.new_id(), input_path=linked)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("must not be a symlink", rejected.stderr)

            run_id = fixture.new_id()
            self.assertEqual(fixture.record(run_id).returncode, 0)
            stdout = fixture.runs / run_id / "stdout.bin"
            replacement = fixture.root / "replacement.stdout"
            replacement.write_bytes(stdout.read_bytes())
            stdout.unlink()
            stdout.symlink_to(replacement)
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 2)
            self.assertIn("symlink is forbidden", verified.stdout)

    def test_missing_completion_is_reported_as_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            run_dir = fixture.runs / run_id
            run_dir.mkdir()
            (run_dir / "launch.json").write_text(json.dumps({
                "document_type": "execution_launch",
                "schema_version": 1,
                "run_id": run_id,
            }) + "\n")
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 4, verified.stdout + verified.stderr)
            report = json.loads(verified.stdout)
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("completion", report["reason"])

    def test_environment_is_explicitly_allowlisted_and_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            run_id = fixture.new_id()
            accepted = fixture.record(run_id, env=["OMP_NUM_THREADS=2", "LC_ALL=C"])
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            launch = json.loads((fixture.runs / run_id / "launch.json").read_text())
            self.assertEqual(launch["environment"], {"LC_ALL": "C", "OMP_NUM_THREADS": "2"})
            rejected = fixture.record(fixture.new_id(), env=["API_TOKEN=not-recorded"])
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("not allowlisted", rejected.stderr)

    def test_command_file_drift_is_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = root / "worker.py"
            shutil.copyfile(TRACKED_WORKER, worker)
            fixture = Fixture(root, worker=worker)
            run_id = fixture.new_id()
            self.assertEqual(fixture.record(run_id).returncode, 0)
            worker.write_text(worker.read_text() + "\n# changed\n")
            verified = fixture.verify(run_id)
            self.assertEqual(verified.returncode, 5)
            self.assertIn("command_file:synthetic_worker", verified.stdout)


if __name__ == "__main__":
    unittest.main()
