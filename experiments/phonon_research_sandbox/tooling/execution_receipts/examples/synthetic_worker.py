#!/usr/bin/env python3
"""SYNTHETIC test process: copy stdin to stdout or fail on request."""

import argparse
import hashlib
import sys


parser = argparse.ArgumentParser()
parser.add_argument("--exit-code", type=int, default=0)
args = parser.parse_args()
payload = sys.stdin.buffer.read()
sys.stdout.write(f"SYNTHETIC input_sha256={hashlib.sha256(payload).hexdigest()} bytes={len(payload)}\n")
sys.stderr.write("SYNTHETIC worker only; no QE or scientific calculation was run.\n")
raise SystemExit(args.exit_code)
