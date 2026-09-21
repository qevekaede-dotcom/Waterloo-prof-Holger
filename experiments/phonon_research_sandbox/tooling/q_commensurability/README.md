# Exact q/supercell commensurability checker

This small standard-library tool answers one lattice-arithmetic question: can a
wave at an exactly specified reduced q-point be periodic in a proposed integer
supercell? It does **not** generate atomic displacements, construct or interpret
eigenvectors, fit force constants, validate an IFC supercell, or establish a
physical instability.

For the SrZrS3 diagnostic minimum reported at `q = (0, 2/5, 0)`, the result is:

- diagonal `1x5x1` is mathematically commensurate;
- diagonal `2x1x1` is not a frozen-mode cell for that q;
- diagonal `3x2x1` and `5x2x1` are also not frozen-mode cells for that q;
- those three incompatible cells can still be legitimate **IFC interpolation
  size tests**, because an FC2 supercell tests real-space interaction range and
  need not itself contain the chosen q wave as a frozen distortion.

The last statement does not say any IFC size is converged or physically
adequate. It only prevents q-periodicity from being used as the wrong rejection
criterion for an IFC interpolation test.

## Convention and derivation

Let the reference direct-lattice basis vectors be columns of `A`. The input
matrix `S` is displayed/serialized row by row, but its **columns** are the three
supercell generators in reference reduced direct coordinates:

```text
A_super = A_reference S
```

Let `q` be a column of reduced reciprocal coordinates in the reciprocal basis
dual to that same `A_reference`. For a supercell translation `T = S n`, the
phase is

```text
exp(2 pi i q^T T) = exp(2 pi i q^T S n).
```

It is one for every integer `n` exactly when

```text
S^T q is integer componentwise.
```

The tool reports those three exact `q_dot_T` values. Its atom multiplier is
`abs(det(S))`, including for an orientation-reversing matrix with negative
determinant.

For `q = (0, 2/5, 0)` and a diagonal `S = diag(1, N, 1)`, the second result is
`2N/5`, so `N` must be divisible by 5. If the reference cell really has 20
atoms and `S` is applied to that verified same direct basis, `1x5x1` has
`20 * abs(det(S)) = 100` atoms. The checked SrZrS3 examples deliberately keep
`reference_basis_verified = false`: the archived q basis and physical atom and
eigenvector mappings have not been established by this utility.

For a non-diagonal matrix, do not read the displayed rows as generators. For
example,

```text
S = [[1, 1, 0],
     [0, 5, 0],
     [0, 0, 1]]
```

has generator columns `(1,0,0)`, `(1,5,0)`, `(0,0,1)` and is commensurate with
`q = (0,2/5,0)`. Transposing this matrix describes a different supercell and
can change the answer.

### Basis-change caveat

The q components and `S` must refer to the same direct/reciprocal basis pair.
If `A_new = A_old C`, then reduced coordinates of the same physical wave obey
`q_new = C^T q_old`. Transform q first, and express the candidate supercell
matrix in the chosen reference direct basis, before using this checker. A label
such as “primitive reciprocal axes” is not enough to prove that two archived
files use the same basis, ordering, orientation, or primitive-cell choice.

## Usage

All q inputs must be exact spellings: integers, explicit fractions such as
`2/5`, or finite decimals such as `0.4`. A finite decimal is interpreted as an
exact base-10 rational and the JSON reports that interpretation (`0.4` becomes
exactly `2/5`). The Python API rejects binary `float` values rather than quietly
turning their stored approximations into fractions. Exponent notation is also
rejected; spell the intended fraction or finite decimal explicitly.

```bash
python3 q_commensurability.py \
  --q 0 2/5 0 \
  --matrix 1 0 0  0 5 0  0 0 1 \
  --purpose frozen-mode \
  --reference-atoms 20
```

The command emits JSON. The report always has
`scope.scientific_acceptance = false`. Verification flags are optional caller
assertions; they are never inferred by the program and do not turn the JSON
into scientific acceptance.

For an IFC-size candidate, state that purpose explicitly:

```bash
python3 q_commensurability.py \
  --q 0 0.4 0 \
  --matrix 3 0 0  0 2 0  0 0 1 \
  --purpose ifc-interpolation
```

Regenerate and test the checked examples with:

```bash
python3 generate_examples.py
python3 -m unittest -v test_q_commensurability.py
```

The generated [SrZrS3 cases](examples/srzrs3_cases.json) include `1x5x1`, the
existing `2x1x1`, the planned `3x2x1` and `5x2x1` IFC tests, and a non-diagonal
example. They are schematic lattice results only; there is no fabricated atomic
motion. The standalone [five-cell phase schematic](examples/q_0_2over5_0_phase.svg)
shows only `exp[2 pi i (2/5)n]` returning to its starting phase at `n = 5`; it
is explicitly not an atomic mode or displacement pattern.

## Sources

Accessed 2026-09-22:

- [Phonopy formulation: commensurate points](https://phonopy.github.io/phonopy/formulation.html#commensurate-points)
  gives the column-vector convention, `A_super = A_primitive P`, and the exact
  condition that `P^T q` have integer components.
- [Phonopy Python API: supercell matrix](https://phonopy.github.io/phonopy/phonopy-module.html#supercell-matrix)
  independently states the supercell-basis transformation convention.
- [Phono3py API: different FC2 and FC3 supercells](https://phonopy.github.io/phono3py/phono3py-api.html#use-of-different-supercell-dimensions-for-2nd-and-3rd-order-fcs)
  documents that the harmonic FC2 supercell may be chosen independently to
  study its longer real-space interaction range.

The local scientific context and unresolved provenance are in
[`../../plans/SrZrS3.md`](../../plans/SrZrS3.md) and
[`../../references/targeted_sources.md`](../../references/targeted_sources.md).
