# Shared-script rules for Claude

These scripts prepare or validate multiple candidate workspaces. Keep them
material-agnostic: material-specific constants belong in each candidate
directory. Do not overwrite trusted CIFs or completed raw outputs. Generated QE
inputs should remain auditable and must record the pseudopotential filenames,
cutoffs, k mesh, occupations, and source structure.

When changing a generator, test it on a disposable path before applying it to a
completed material.
