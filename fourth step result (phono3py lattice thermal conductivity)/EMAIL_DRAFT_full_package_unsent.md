# NOTE: superseded, never sent

This fuller draft was staged before the interim email existed. The email
actually SENT to Roy is EMAIL_DRAFT.md (interim, frozen attachments). This
file is kept as source material for the final complete-package email
(three materials + full writeup).

---

# Subject

phono3py worked — first lattice thermal conductivity for SrCu2SnS4

# Body

Hi Roy,

Good news on the phonon task: phono3py now runs end to end for us, and I
have a first lattice thermal conductivity for SrCu2SnS4. Since you
mentioned you could not get phono3py to run yourself, I kept a record of
every problem we hit along the way and how each one was solved, and turned
it into a step-by-step write-up — it is attached, and I hope it saves you
and the group the same detours.

The result [calculated]: kappa_L at 300 K comes out at about 0.36 W/(m K)
(0.40 in-plane, 0.30 along the c axis), falling close to 1/T with
temperature to about 0.12 W/(m K) at 900 K; the table, a figure, and the
settings summary are attached. Taken at face value this is a very low
lattice thermal conductivity — good thermoelectric materials are usually
quoted at or below roughly 1 W/(m K) at room temperature — so it is an
encouraging sign for this candidate. The phonon spectrum shows no
imaginary frequencies, so the relaxed structure is dynamically stable at
this level of theory, and the tensor has the symmetry the trigonal space
group requires (kappa_xx = kappa_yy).

I want to be careful about what "first pass" means here. The number comes
from the relaxation-time approximation on 2x2x1 supercells, with
third-order force constants truncated at 4.0 A atom pairs, PBE, no
spin-orbit coupling, and no Born-charge (non-analytic) correction yet.
The force calculations used settings validated by explicit
force-convergence tests on the cluster itself (the coarser k-mesh failed
our 5e-5 Ry/bohr criterion and was rejected; the lower cutoffs passed).
I also ran the standard sanity check on the undisplaced supercell: its
residual forces came out at 5.5e-4 Ry/bohr, above the 1e-4 guideline we
had set, so rather than just flagging it I subtracted the measured
residual field from every displaced-cell force before fitting (phono3py's
--cfz option); reassuringly, that changed kappa_L by less than 0.1% at
fixed mesh, so the result is robust against it. The q-mesh for the
thermal-conductivity integration met our 3% convergence criterion at
13x13x6, though only just (2.9% change from the previous mesh, and the
values across the whole mesh ladder span roughly 0.33-0.38), so I would
treat about +/-5% as the honest uncertainty on these numbers. And as
before, this is not a full zT yet — kappa_L fills in one missing piece of
the denominator, but the electronic side still carries its unknown
relaxation time.

About getting it to run: installing phono3py was the easy part; almost
everything that went wrong was in the surrounding machinery, and each
failure looked misleading at first sight. The write-up lists seven traps
with symptoms and fixes, including two I suspect may have stopped your
attempt: phono3py 4.x moved all of its setup commands into a separate
phono3py-init tool (so older instructions make it look broken), and with
QE it silently reads our structure as P1 unless the symmetry tolerance is
loosened, which turns 168 required force calculations into tens of
thousands. The rest were cluster-side: a thread-oversubscription issue
that made QE about ten times slower, the cluster's Python refusing
current phono3py versions, and a QE symmetry bug ("lone vector") that
deterministically kills a specific subset of the displaced cells — each
with its workaround. The whole campaign cost roughly 4,000 CPU-core-hours
on Nibi under the group allocation and now takes about a day end to end.

For the next step I would suggest running the same campaign for SrZrS3
and Rb2Cu2SnS4 (each with its own convergence checks, as before), so all
three candidates can be compared on kappa_L and not just on the
electronic side. Alternatively I could first tighten the SrCu2SnS4 number
itself (larger supercell, Born charges, a finer q-mesh). Happy to go
whichever way you prefer.

Best regards,
Yuhan
