#!/usr/bin/env python3
"""Run the BoltzTraP2 CLI with NumPy 2 compatibility."""

import numpy as np


if not hasattr(np, "trapz"):
    np.trapz = np.trapezoid

from BoltzTraP2 import bandlib  # noqa: E402
from BoltzTraP2.interface import btp2_main  # noqa: E402


_smoothen_dos = bandlib.smoothen_DOS_direct


def _smoothen_positive_dos(*args, **kwargs):
    # BoltzTraP2 26.3.1 divides by the negative FD-derivative normalization.
    return -_smoothen_dos(*args, **kwargs)


bandlib.smoothen_DOS_direct = _smoothen_positive_dos


if __name__ == "__main__":
    btp2_main()
