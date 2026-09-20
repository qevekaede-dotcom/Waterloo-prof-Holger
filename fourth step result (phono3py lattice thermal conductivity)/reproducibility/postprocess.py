#!/usr/bin/env python3
"""Retired archival postprocessor for the rejected SrCu2SnS4 campaign.

This preserved package must never construct FC2/FC3, read or overwrite the
historical HDF5 products, or write a new kappa summary. A new calculation
requires the v2 workflow in a new empty RUN_DIR with a run-bound fingerprint.
"""

import sys


def main() -> None:
    sys.exit(
        "[retired] archival/rejected postprocessor: no FC or kappa execution. "
        "Use v2 in a new empty RUN_DIR."
    )


if __name__ == "__main__":
    main()
