# Subject

phono3py update: it runs, and a first lattice thermal conductivity for SrCu2SnS4

# Note

Interim progress report on the phono3py task — drafted, not yet sent. The
earlier correspondence with Roy lives in the uwaterloo mailbox (not the
personal Gmail), so this draft is meant to be copied there. The single
attachment is staged in `READY_TO_ATTACH/`; freeze that folder once the email
is actually sent, following the earlier packages. The full "how we got it
working" writeup is NOT this email — it comes with the complete package once
all three materials are done.

# Body

Hi Roy,

I wanted to send a progress update on the phono3py task. The short version:
phono3py now runs for us end to end, and I have a first-pass lattice thermal
conductivity for SrCu2SnS4. The other two candidates have not started their
phonon runs yet, and I have been keeping a step-by-step record of everything
that failed along the way, so the full "how we got it working" writeup can
come with the complete package.

Since you mentioned it would not run for you, here are the traps I hit, in
case any of them overlap with what you saw:

- The install itself went smoothly for me (pip wheels, no compiler needed).
  What has changed is the command line: in phono3py 4.x the setup commands
  (displacement generation, force collection) moved into a separate
  `phono3py-init` tool, so the `phono3py -d --dim ...` calls in most older
  tutorials fail with confusing errors, and `--version` does not exist at all.
- Reading a QE cell, the default symmetry tolerance is stricter than
  coordinates rounded to six decimals: my relaxed cell was detected as P1 and
  phono3py asked for 83,088 displaced supercells. With `--tolerance 1e-3` it
  recovers the correct P3_121, which gives 13,848 displacements; a 4.0 A
  displacement pair-distance cutoff then brings it down to 168 force
  calculations.
- On Nibi (this all ran under the group's Alliance allocation — thank you
  and the professor again for sorting out the cluster access): pip installs from the Alliance wheelhouse
  by default, which pins phono3py to an old 3.x that has no `phono3py-init`;
  installing the current 4.x wheels from PyPI needed a small workaround that
  I will document. Separately, the Alliance QE module is an MPI+OpenMP hybrid
  build, and without `OMP_NUM_THREADS=1` every MPI rank spawned its own set
  of OpenMP threads — my first submission oversubscribed its node roughly
  tenfold and produced nothing within its time limit.
- One trap was QE's rather than phono3py's: in each block of paired
  displacements, exactly the one that happens to preserve a symmetry
  operation made pw.x abort at startup with a "lone vector" error from its
  charge-symmetrization setup — 24 of my 168 runs, in a perfectly regular
  pattern. Rerunning just those 24 with `nosym = .true., noinv = .true.`
  fixed it; that switch turns off the k-point reduction and the charge/force
  symmetrization step that was failing, and on a converged mesh the
  unsymmetrized forces agree with the symmetrized ones to within the force
  tolerance we already work to, so the third-order force constants should be
  unaffected at our accuracy. I expect the same thing for the next two
  materials and will patch it from the start.

For the numbers: 2x2x1 supercell (96 atoms), pair cutoff 4.0 A (third-order
force constants beyond the cutoff are set to zero — a documented first-pass
approximation), forces at 60/480 Ry on a 3x3x3 k-mesh (accepted only after a
force-convergence check on the cluster against the 90/720 Ry reference, with
maximum force differences at or below 5e-5 Ry/bohr; the reference
displacement itself kept the 90/720 Ry settings), and phono3py in the
relaxation-time approximation. I increased the q-mesh from 7x7x3 toward
15x15x7 until the room-temperature average changed by less than 3%, which
stopped at 13x13x6 — the last step came in just under the criterion, so the
q-mesh is converged only to that level. There were no imaginary phonon
frequencies on the sampled mesh, so as far as this first-pass setup can see
the relaxed structure is dynamically stable (a larger-supercell check would
firm that up). The calculated lattice thermal conductivity comes out low
(in the attached CSV, kappa_xx = kappa_yy is the in-plane value and
kappa_zz the c-axis value):

| T (K) | kappa in-plane (W m^-1 K^-1) | kappa c-axis (W m^-1 K^-1) | average (W m^-1 K^-1) |
|-------|------------------------------|----------------------------|-----------------------|
| 300   | 0.396                        | 0.300                      | 0.364                 |
| 500   | 0.238                        | 0.180                      | 0.218                 |
| 700   | 0.170                        | 0.128                      | 0.156                 |
| 900   | 0.132                        | 0.100                      | 0.121                 |

The full 300-900 K table is in the attached CSV. It falls roughly as 1/T —
as it should here, since phonon-phonon scattering is the only channel
included in this calculation, so I read that as a consistency check rather
than a validation.

I would not read three significant figures into these values. The part I
can actually quantify is numerical: between successive q-meshes and the
treatment of residual forces, the room-temperature average moves by up to
about 5%. On top of that sit systematic approximations whose bias I cannot
bound yet: the 4.0 A pair cutoff keeps 168 of the 13,848 symmetry-reduced
displacements, the 2x2x1 supercell limits the range of the force constants,
the relaxation-time approximation itself, and no non-analytic correction
yet (I have not computed Born charges). Everything is also still
scalar-relativistic PBE without SOC. So the absolute value could move by
well more than 5%, and the tightened follow-up (the 5.0 A cutoff set is
600 supercells, plus a supercell-size check) is what will tell us by how
much. With those caveats: if a value around 0.35-0.40 W m^-1 K^-1 at room
temperature survives the tightening, that would be quite low compared with
the values I have seen reported for crystalline sulfides, and encouraging
for the final zT — the electronic-only zT values I sent earlier were upper
bounds precisely because this denominator was missing. The remaining
missing piece for a full zT is an electronic relaxation time, so I have not
combined kappa_L with the transport results yet.

Next I plan to run the same campaign for SrZrS3 and Rb2Cu2SnS4 (each with its
own force-convergence checks, as before) and then send the complete package
with the full step-by-step writeup. If you or the professor would rather I
first tighten the SrCu2SnS4 numbers (larger pair cutoff and supercell, Born
charges), I am happy to do that instead — whichever order is more useful.

Best regards,
Yuhan
