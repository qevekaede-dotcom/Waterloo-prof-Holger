#!/usr/bin/env python3
"""Standalone prototype for recording one local, stdin-driven execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ALLOWED_ENV_KEYS = {
    "LANG",
    "LC_ALL",
    "MKL_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
}
SENSITIVE_ENV_FRAGMENT = re.compile(r"TOKEN|SECRET|PASS|PASSWORD|KEY|CREDENTIAL|AUTH", re.I)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


class ReceiptError(ValueError):
    """Fail-closed validation error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptError(message)


def regular_nonsymlink(path: Path, label: str, executable: bool = False) -> Path:
    require(path.is_absolute(), f"{label} must be an absolute path")
    require(not path.is_symlink(), f"{label} must not be a symlink")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise ReceiptError(f"{label} does not exist: {path}") from exc
    require(stat.S_ISREG(mode), f"{label} must be a regular file")
    if executable:
        require(os.access(path, os.X_OK), f"{label} must be executable")
    return path


def real_directory(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} must be an absolute path")
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a real directory")
    return path


def parse_named_files(values: list[str], option: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        require("=" in value, f"{option} values must use NAME=/absolute/path")
        name, raw_path = value.split("=", 1)
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) is not None, f"invalid {option} name: {name!r}")
        require(name not in result, f"duplicate {option} name: {name}")
        result[name] = regular_nonsymlink(Path(raw_path), f"{option} {name}")
    return result


def parse_environment(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        require("=" in value, "--env values must use ALLOWED_NAME=value")
        name, env_value = value.split("=", 1)
        require(name in ALLOWED_ENV_KEYS, f"environment key is not allowlisted: {name}")
        require(SENSITIVE_ENV_FRAGMENT.search(name) is None, f"secret-like environment key is forbidden: {name}")
        require(name not in result, f"duplicate environment key: {name}")
        require("\x00" not in env_value, f"environment value contains NUL: {name}")
        result[name] = env_value
    return result


def validate_run_id(value: str) -> str:
    require(UUID_RE.fullmatch(value) is not None, "--run-id must be a lowercase RFC 4122 version-4 UUID")
    return value


def scope_fields() -> dict[str, Any]:
    return {
        "evidence_scope": "standalone local protocol evidence only",
        "integrated_with_phono3py_v2": False,
        "production_qe_provenance_verified": False,
        "scientific_acceptance": False,
    }


def validate_scope(record: dict[str, Any], label: str) -> None:
    for key, expected in scope_fields().items():
        require(record.get(key) == expected, f"{label} has unsafe or missing scope field: {key}")


def snapshot_sources(input_path: Path, pseudos: dict[str, Path], command_files: dict[str, Path],
                     executable: Path, runner: Path) -> dict[str, Any]:
    return {
        "input": {"path": str(input_path), "sha256": digest_file(input_path)},
        "pseudopotentials": {
            name: {"path": str(path), "sha256": digest_file(path)}
            for name, path in sorted(pseudos.items())
        },
        "command_files": {
            name: {"path": str(path), "sha256": digest_file(path)}
            for name, path in sorted(command_files.items())
        },
        "executable": {"path": str(executable), "sha256": digest_file(executable)},
        "recorder": {"path": str(runner), "sha256": digest_file(runner)},
    }


def current_source_digest(path_text: str) -> tuple[str | None, str | None]:
    path = Path(path_text)
    if path.is_symlink():
        return None, "source became a symlink"
    if not path.is_file():
        return None, "source is missing or not a regular file"
    return digest_file(path), None


def source_drift(prelaunch: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[tuple[str, dict[str, str]]] = [
        ("input", prelaunch["input"]),
        ("executable", prelaunch["executable"]),
        ("recorder", prelaunch["recorder"]),
    ]
    entries.extend((f"pseudopotential:{name}", item) for name, item in prelaunch["pseudopotentials"].items())
    entries.extend((f"command_file:{name}", item) for name, item in prelaunch["command_files"].items())
    drift = []
    for label, item in entries:
        observed, error = current_source_digest(item["path"])
        if error or observed != item["sha256"]:
            drift.append({
                "source": label,
                "expected_sha256": item["sha256"],
                "observed_sha256": observed or "unavailable",
                "reason": error or "digest changed",
            })
    return drift


def build_plan(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    run_root = real_directory(args.run_root, "--run-root")
    anchor_dir = real_directory(args.anchor_dir, "--anchor-dir")
    cwd = real_directory(args.cwd, "--cwd")
    run_id = validate_run_id(args.run_id)
    run_dir = run_root / run_id
    anchor_path = anchor_dir / f"{run_id}.anchor.json"
    require(not run_dir.exists() and not run_dir.is_symlink(), "run directory already exists; evidence cannot be overwritten")
    require(not anchor_path.exists() and not anchor_path.is_symlink(), "anchor already exists; run identity cannot be reused")
    require(anchor_dir != run_dir and run_dir not in anchor_dir.parents,
            "anchor directory must remain outside the run directory")
    input_path = regular_nonsymlink(args.input, "--input")
    executable = regular_nonsymlink(Path(args.command[0]), "command executable", executable=True)
    runner = regular_nonsymlink(Path(__file__).absolute(), "receipt recorder")
    pseudos = parse_named_files(args.pseudo, "--pseudo")
    command_files = parse_named_files(args.command_file, "--command-file")
    environment = parse_environment(args.env)
    input_bytes = input_path.read_bytes()
    sources = snapshot_sources(input_path, pseudos, command_files, executable, runner)
    require(sources["input"]["sha256"] == digest_bytes(input_bytes), "input changed while it was being read")
    plan = {
        "document_type": "execution_receipt_plan",
        "schema_version": SCHEMA_VERSION,
        "mode": "execute" if args.execute else "dry_run",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "anchor_path": str(anchor_path),
        "cwd": str(cwd),
        "argv": args.command,
        "environment": environment,
        "stdin_binding": "recorder-owned bytes from the prelaunch-hashed input are passed to child stdin",
        "sources": sources,
        "shell": False,
        **scope_fields(),
    }
    context = {"run_dir": run_dir, "anchor_path": anchor_path, "cwd": cwd, "environment": environment}
    return plan, context, input_bytes


def execute(args: argparse.Namespace) -> int:
    plan, context, input_bytes = build_plan(args)
    if not args.execute:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    run_dir: Path = context["run_dir"]
    run_dir.mkdir(mode=0o700, exist_ok=False)
    snapshot_path = run_dir / "stdin.snapshot"
    stdout_path = run_dir / "stdout.bin"
    stderr_path = run_dir / "stderr.bin"
    write_exclusive(snapshot_path, input_bytes)
    stdout_stream = stdout_path.open("xb")
    stderr_stream = stderr_path.open("xb")
    start_monotonic = time.monotonic()
    launch = {
        "document_type": "execution_launch",
        "schema_version": SCHEMA_VERSION,
        "run_id": plan["run_id"],
        "started_at_utc": utc_now(),
        "cwd": plan["cwd"],
        "argv": plan["argv"],
        "environment": plan["environment"],
        "shell": False,
        "stdin": {
            "delivery": "subprocess stdin from recorder-owned in-memory bytes",
            "source_path": plan["sources"]["input"]["path"],
            "snapshot_path": "stdin.snapshot",
            "sha256": digest_bytes(input_bytes),
            "size_bytes": len(input_bytes),
        },
        "sources": plan["sources"],
        "outputs": {"stdout": "stdout.bin", "stderr": "stderr.bin"},
        **scope_fields(),
    }
    launch_bytes = canonical_json_bytes(launch)
    write_exclusive(run_dir / "launch.json", launch_bytes)
    try:
        result = subprocess.run(
            plan["argv"],
            input=input_bytes,
            stdout=stdout_stream,
            stderr=stderr_stream,
            cwd=context["cwd"],
            env=context["environment"],
            check=False,
            shell=False,
        )
    except OSError as exc:
        stdout_stream.close()
        stderr_stream.close()
        failure = {
            "document_type": "execution_launch_failure",
            "schema_version": SCHEMA_VERSION,
            "run_id": plan["run_id"],
            "ended_at_utc": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "launch_sha256": digest_bytes(launch_bytes),
        }
        write_exclusive(run_dir / "launch_failure.json", canonical_json_bytes(failure))
        raise ReceiptError(f"process launch failed; partial evidence retained in {run_dir}: {exc}") from exc
    finally:
        if not stdout_stream.closed:
            stdout_stream.close()
        if not stderr_stream.closed:
            stderr_stream.close()

    completion = {
        "document_type": "execution_completion",
        "schema_version": SCHEMA_VERSION,
        "run_id": plan["run_id"],
        "ended_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - start_monotonic, 9),
        "exit_code": result.returncode,
        "launch_sha256": digest_bytes(launch_bytes),
        "stdin_snapshot_sha256": digest_file(snapshot_path),
        "stdout_sha256": digest_file(stdout_path),
        "stderr_sha256": digest_file(stderr_path),
        "source_drift_at_completion": source_drift(plan["sources"]),
        **scope_fields(),
    }
    completion_bytes = canonical_json_bytes(completion)
    write_exclusive(run_dir / "completion.json", completion_bytes)
    receipt = {
        "document_type": "execution_receipt",
        "schema_version": SCHEMA_VERSION,
        "run_id": plan["run_id"],
        "launch_sha256": digest_bytes(launch_bytes),
        "completion_sha256": digest_bytes(completion_bytes),
        "evidence": {
            "launch": "launch.json",
            "completion": "completion.json",
            "stdin_snapshot": "stdin.snapshot",
            "stdout": "stdout.bin",
            "stderr": "stderr.bin",
        },
        **scope_fields(),
    }
    receipt_bytes = canonical_json_bytes(receipt)
    write_exclusive(run_dir / "receipt.json", receipt_bytes)
    anchor = {
        "document_type": "execution_receipt_anchor",
        "schema_version": SCHEMA_VERSION,
        "run_id": plan["run_id"],
        "receipt_sha256": digest_bytes(receipt_bytes),
        **scope_fields(),
    }
    write_exclusive(context["anchor_path"], canonical_json_bytes(anchor))
    output = {
        "run_id": plan["run_id"],
        "run_dir": str(run_dir),
        "anchor_path": str(context["anchor_path"]),
        "receipt_sha256": anchor["receipt_sha256"],
        "exit_code": result.returncode,
        "source_drift_at_completion": completion["source_drift_at_completion"],
        **scope_fields(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if result.returncode == 0 and not completion["source_drift_at_completion"] else 3


def load_json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    regular_nonsymlink(path, label)
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"{label} is not valid JSON") from exc
    require(isinstance(value, dict), f"{label} must contain a JSON object")
    return value, raw


def reject_controlled_symlinks(run_dir: Path) -> None:
    require(run_dir.is_dir() and not run_dir.is_symlink(), "run directory must be a real directory")
    for path in run_dir.rglob("*"):
        require(not path.is_symlink(), f"symlink is forbidden in run evidence: {path}")


def incomplete_report(run_dir: Path, run_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "document_type": "execution_receipt_verification",
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "incomplete",
        "integrity_ok": False,
        "execution_succeeded": False,
        "reason": reason,
        "run_dir": str(run_dir),
        **scope_fields(),
    }


def verify(run_dir: Path, anchor_path: Path) -> tuple[dict[str, Any], int]:
    real_directory(run_dir, "--run-dir")
    reject_controlled_symlinks(run_dir)
    require(anchor_path.is_absolute(), "--anchor-file must be an absolute path")
    require(run_dir not in anchor_path.parents, "independent anchor must be outside the run directory")
    launch_path = run_dir / "launch.json"
    if not launch_path.is_file():
        return incomplete_report(run_dir, None, "launch record is missing"), 4
    launch, launch_bytes = load_json_file(launch_path, "launch record")
    run_id = launch.get("run_id") if isinstance(launch.get("run_id"), str) else None
    if not (run_dir / "completion.json").is_file():
        reason = "completion record is missing"
        if (run_dir / "launch_failure.json").is_file():
            reason = "process launch failed before completion"
        return incomplete_report(run_dir, run_id, reason), 4
    if not (run_dir / "receipt.json").is_file():
        return incomplete_report(run_dir, run_id, "final receipt is missing"), 4

    completion, completion_bytes = load_json_file(run_dir / "completion.json", "completion record")
    receipt, receipt_bytes = load_json_file(run_dir / "receipt.json", "receipt")
    anchor, _ = load_json_file(anchor_path, "independent anchor")
    require(anchor.get("document_type") == "execution_receipt_anchor", "anchor document type mismatch")
    require(anchor.get("schema_version") == SCHEMA_VERSION, "anchor schema version mismatch")
    require(SHA256_RE.fullmatch(str(anchor.get("receipt_sha256", ""))) is not None, "anchor receipt digest is malformed")
    require(digest_bytes(receipt_bytes) == anchor["receipt_sha256"], "receipt digest does not match independent anchor")
    require(receipt.get("document_type") == "execution_receipt", "receipt document type mismatch")
    require(launch.get("document_type") == "execution_launch", "launch document type mismatch")
    require(completion.get("document_type") == "execution_completion", "completion document type mismatch")
    for record, label in ((anchor, "anchor"), (receipt, "receipt"),
                          (launch, "launch"), (completion, "completion")):
        validate_scope(record, label)
    require(receipt.get("schema_version") == launch.get("schema_version") == completion.get("schema_version") == SCHEMA_VERSION,
            "receipt schema version mismatch")
    identities = {anchor.get("run_id"), receipt.get("run_id"), launch.get("run_id"), completion.get("run_id"), run_dir.name}
    require(len(identities) == 1 and None not in identities, "run identity mismatch across evidence")
    require(receipt.get("launch_sha256") == digest_bytes(launch_bytes), "launch record digest mismatch")
    require(receipt.get("completion_sha256") == digest_bytes(completion_bytes), "completion record digest mismatch")
    require(completion.get("launch_sha256") == digest_bytes(launch_bytes), "completion is not bound to launch record")
    canonical_evidence = {
        "launch": "launch.json",
        "completion": "completion.json",
        "stdin_snapshot": "stdin.snapshot",
        "stdout": "stdout.bin",
        "stderr": "stderr.bin",
    }
    require(receipt.get("evidence") == canonical_evidence, "receipt evidence mapping is not canonical")
    stdin_path = run_dir / "stdin.snapshot"
    stdout_path = run_dir / "stdout.bin"
    stderr_path = run_dir / "stderr.bin"
    for path, label in ((stdin_path, "stdin snapshot"), (stdout_path, "stdout"), (stderr_path, "stderr")):
        regular_nonsymlink(path, label)
    require(digest_file(stdin_path) == launch["stdin"]["sha256"] == completion.get("stdin_snapshot_sha256"),
            "stdin snapshot digest mismatch")
    require(stdin_path.stat().st_size == launch["stdin"]["size_bytes"], "stdin snapshot size mismatch")
    require(digest_file(stdout_path) == completion.get("stdout_sha256"), "stdout digest mismatch")
    require(digest_file(stderr_path) == completion.get("stderr_sha256"), "stderr digest mismatch")
    require(launch.get("shell") is False, "shell execution is forbidden")
    require(isinstance(launch.get("argv"), list) and launch["argv"], "recorded argv is missing")
    require(launch["argv"][0] == launch["sources"]["executable"]["path"], "argv executable differs from hashed executable")
    require(launch["stdin"].get("delivery") == "subprocess stdin from recorder-owned in-memory bytes",
            "input delivery relation is not the recorder-owned stdin contract")
    require(launch.get("environment") is not None and set(launch["environment"]).issubset(ALLOWED_ENV_KEYS),
            "recorded environment contains a non-allowlisted key")
    observed_drift = source_drift(launch["sources"])
    recorded_drift = completion.get("source_drift_at_completion")
    require(isinstance(recorded_drift, list), "completion source drift field is malformed")
    require(type(completion.get("exit_code")) is int, "completion exit code must be an integer")
    execution_succeeded = completion.get("exit_code") == 0
    if observed_drift or recorded_drift:
        report = {
            "document_type": "execution_receipt_verification",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "status": "source_drift",
            "integrity_ok": False,
            "execution_succeeded": execution_succeeded,
            "exit_code": completion.get("exit_code"),
            "source_drift_at_completion": recorded_drift,
            "source_drift_now": observed_drift,
            **scope_fields(),
        }
        return report, 5
    status = "verified_success" if execution_succeeded else "verified_nonzero_exit"
    report = {
        "document_type": "execution_receipt_verification",
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": status,
        "integrity_ok": True,
        "execution_succeeded": execution_succeeded,
        "exit_code": completion.get("exit_code"),
        "receipt_sha256": anchor["receipt_sha256"],
        "stdout_sha256": completion["stdout_sha256"],
        "stderr_sha256": completion["stderr_sha256"],
        **scope_fields(),
    }
    return report, 0 if execution_succeeded else 3


def verify_command(args: argparse.Namespace) -> int:
    try:
        report, return_code = verify(args.run_dir, args.anchor_file)
    except (ReceiptError, KeyError, TypeError, OSError) as exc:
        report = {
            "document_type": "execution_receipt_verification",
            "schema_version": SCHEMA_VERSION,
            "status": "invalid",
            "integrity_ok": False,
            "execution_succeeded": False,
            "reason": str(exc),
            **scope_fields(),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="subcommand", required=True)
    record = sub.add_parser("record", help="plan or explicitly execute one stdin-driven command")
    record.add_argument("--run-root", type=Path, required=True)
    record.add_argument("--anchor-dir", type=Path, required=True)
    record.add_argument("--run-id", required=True)
    record.add_argument("--input", type=Path, required=True)
    record.add_argument("--pseudo", action="append", default=[], metavar="NAME=/ABS/PATH")
    record.add_argument("--command-file", action="append", default=[], metavar="NAME=/ABS/PATH")
    record.add_argument("--cwd", type=Path, required=True)
    record.add_argument("--env", action="append", default=[], metavar="ALLOWLISTED_NAME=VALUE")
    record.add_argument("--execute", action="store_true", help="required to create evidence and start the process")
    record.add_argument("command", nargs=argparse.REMAINDER, help="absolute executable and exact arguments after --")
    record.set_defaults(handler=execute)
    check = sub.add_parser("verify", help="verify immutable evidence against an independently retained anchor")
    check.add_argument("--run-dir", type=Path, required=True)
    check.add_argument("--anchor-file", type=Path, required=True)
    check.set_defaults(handler=verify_command)
    return ap


def main() -> int:
    ap = parser()
    args = ap.parse_args()
    if args.subcommand == "record":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        require(bool(args.command), "command is required after --")
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReceiptError, KeyError, TypeError, OSError) as exc:
        raise SystemExit(f"FAIL-CLOSED: {exc}")
