---
name: phase-id
description: Read this when you have survey data for a region and need to say what phase it is. A decision tree from measured observables to a phase label - long-range order, composite order, critical, symmetry-protected topological, trivial, or honestly unidentified - with the positive evidence each label requires and the trap at each step. Stage 3 of the study.
---

# Stage 3: naming the phase in a region

You have data for a region of the parameter box and you need to say what it is. This is where
studies go wrong most often, and almost always in the same direction: a label gets attached on
evidence that was consistent with it rather than evidence that established it.

Keep one thing in mind throughout. **A phase label is a statement about an infinite system, and
you are working with chains of thirty or sixty sites.** So the question at every step is never
"what does the data show" but "what does the data show that would still be true at a thousand
sites". Those are different questions, and most of the traps below are cases where the answer
changes between them.

## The map

```
D0   a field pushing on a conserved quantity?     yes → map magnetisation first
D1   two spins correlated at long distance?       yes → D1a, which order       no → D2
D2   anything larger than a spin pair ordered?    yes → name it, verify it     no → D3
D3'  any couplings or fields random?              yes → go to `disorder`
D3   is the region gapless?                       yes → extract c              no → D4
D4   gapped with nothing ordering: protected by a symmetry, or just simple?
D5   nothing fits → say so, and say what would settle it
```

Work down the list. Most regions exit at D1 or D3.

---

## D0. Does the model have a magnetic field along a conserved direction?

**The question.** Stage 0a worked out whether the total spin along `z` is conserved, and whether
`H` contains a field pushing on it. If both are true, read on. If not, skip to D1.

**Why it comes before everything else.** When a field pushes on a conserved quantity, how much
magnetisation the ground state carries changes as you turn the field up. That behaviour is not a
clue about the phases. It is the phases. Mapping it first splits the region up for you and makes
every later step easier.

**How to read the magnetisation curve.** Plot the magnetisation per site against the field.

- A flat stretch, usually at a simple fraction of the maximum, is a plateau. Turning the field up
  a little does nothing, which means it costs a finite energy to add one more unit of
  magnetisation: the region is gapped, and it is a phase in its own right.
- A vertical jump is a first-order transition. Take it to `transitions`, step E1.
- The field at which the curve reaches its maximum is a phase boundary. Above it every spin is
  simply pointing along the field, which is an exact product state.
  Send it to D4, label it, and do not spend survey points in there.
- A curve that just rises smoothly has no plateau. Carry on down the tree.
- Look at the *step height* of the finite-size staircase, in units of the elementary change of
  magnetisation. If the minimising `M` advances two at a time, and keeps doing so as `N` grows,
  magnons are binding in pairs. The region is then a candidate multipolar (spin-nematic) state,
  whose order is carried by a two-site pair operator rather than by a single spin. Flag it here and
  measure the pair correlator against the longitudinal channel at D1a and D3 (`observables` lists
  the operator). A skip that grows with `N` is a first-order jump instead.

**The trap.** Every magnetisation curve looks like a staircase at small sizes, because on `N`
sites the magnetisation can only take the values `0, 1/N, 2/N, …`. Those steps are an artefact of
counting, not physics. A real plateau keeps its width in field as `N` grows. A counting step gets
narrower and narrower, shrinking roughly like `1/N`. Run two sizes before believing any plateau.

**Which plateaus are even allowed.** For a translation-invariant chain there is a counting rule that
says a plateau at magnetisation `m` per site can only occur if `n(S − m)` is a whole number, where
`S` is the spin per site and `n` is the number of sites in the repeating unit of the ground state.
Two uses. It tells you which fractions to look for rather than scanning blindly. And when you find
a plateau at some `m`, it tells you the smallest `n` that can support it. So if that `n` is bigger
than one, the ground state must have enlarged the unit cell, and you should be able to see that
directly as a modulation in the bond pattern. A plateau whose required periodicity you cannot find
in the data is not yet understood.

As above, this needs translation invariance and it describes the infinite system. A disordered chain
has no unit cell and the rule says nothing.

---

## D1. Does this region have long-range order?

**The question.** Take two spins infinitely far apart. Are they still correlated?

**How to measure it.** The survey measured several different correlation functions: spin along `z`,
spin in the plane, and so on. Each one is a *channel*, and each gets tested separately, because a
model can order in one and not the others.

For each channel, compute the order parameter `m²` that `observables` defines (the normalised one,
which is the whole point) at three or more sizes, and extrapolate to `1/L → 0`. Canonical key
`m2_<channel>`. Measure the one-point profile of the same channel alongside it. `observables`
explains how a non-zero profile enters `S(q)`, when it is the order and when it is contamination.

**How to read it.** Three outcomes:

- it settles on a finite constant, so this channel is ordered: go to D1a
- it goes to zero, so this channel is not ordered: try the next channel, and if every two-point
  channel gives zero, go to D2
- it does neither and the points scatter.

The third case is a real outcome, not a failure. It means you cannot answer the
question yet, and the honest move is to add a size or raise the bond dimension before going
further. A guess here does not stay local: every later step in this tree takes D1 as settled.

**The trap.** A raw structure-factor peak grows with system size in a critical region too, just more
slowly than the system does. So "the peak got taller when I went bigger" is not evidence of order,
and this is where critical regions get mislabelled. The normalisation in `observables`' definition
is what separates the two cases: use the quantity it defines and do not re-normalise it here.

### D1a. Which order, exactly?

Four things name it, and all of them come from data you already have.

**Where the peak sits** gives the ordering wavevector, and the first thing to settle is whether it
is commensurate. Commensurate means `q*` is a simple rational multiple of `2π` per lattice spacing,
so the pattern closes after a whole number of cells: `q* = 0` is uniform order in that channel (a
ferromagnet, in the spin channel), `π` is period two and the two-sublattice antiferromagnet, `2π/3`
is period three, `π/2` is period four. Incommensurate means no simple fraction fits, so the
modulation never closes against the lattice. Note what that does not say. A peak away from `0` and
`π` is not incommensurate by that fact alone, and treating it as such is how an order of period
three or four gets written down as a spiral.

A finite chain cannot tell a rational value from a nearby irrational one, so the call takes two
steps, and the first one is not a measurement.

**Enumerate the periods before you read any peak.** Write down the small integers `n` and the
wavevectors `2πk/n` they carry, and keep that list beside the measurement. A period you never wrote
down is one you will not recognise. The counting rule in D0 filters that list rather than generating
it: a repeating unit of `n` sites needs `n(S − m)` to be a whole number, which at zero field is
`nS`, so half-integer spin excludes the odd `n` and integer spin excludes nothing. Read it as a
bound on what is possible, never as a prediction of what occurs. And if the symmetry audit found
the group larger at some special point of the parameter space than it is generically, that is a
fact about the model and not only a validation result. Work out what the larger group allows a
local object to be and how many sites that takes, and carry the answer onto your list before you
read any peak. A symmetry that only ever appears in a validation table has told you nothing.

**Then compare, and then follow.** Check the fitted `q*` against the fractions on your list, within
your own resolution. Commensurate order locks: `q*` sits on a fraction and stays there while the
parameters move and while `N` grows. An incommensurate `q*` drifts continuously with the
parameters. Neither reading is available from a single point, and `Before you leave Stage 3` asks
you to record which one you found.

**State your resolution as a number**, because locking is a claim about a distance. It is the larger
of the `q` grid spacing and the intrinsic peak width, which is of order `2π/N` and is almost always
the larger of the two. If `q*` sits within `δ` of a fraction, the two are indistinguishable on any
chain shorter than the beat length `2π/δ`, and saying exactly that is the result. A plateau in `q*`
resolved at a precision finer than `2π/N` is a statement about your grid rather than about the
state.

Read `q*` from a dense grid and fit the peak position between grid points: a coarse grid of `N+1`
points cannot resolve an incommensurate wavevector, and will snap it to the nearest commensurate
value, turning a spiral into a fake Néel phase.

On anything wider than a chain `q*` is a vector. Judge each component against the underlying lattice
using physical positions rather than site indices, and do not require the components to agree.

**Which component peaks** gives the ordering axis. Whether that is worth measuring has a test, and
the test is not whether the model looks anisotropic: ask whether any symmetry of `H` maps one spin
component onto another. A rotation by a quarter turn about `z` is the usual one. If it survives,
the `x` and `y` correlators are equal by symmetry and resolving them tells you nothing. If no such
map exists, they can differ, and then two neighbouring regions can order at the same `q*` along
different axes: the scalar correlator sums the components and is blind to the boundary between
them.

**Whether the order is possible here at all.** Suppose the channel that appears ordered transforms
under a *continuous* symmetry of `H` (a rotation about an axis, or the full SU(2), as recorded in
the Stage 0a table) and the order parameter does not commute with `H`. Then a chain, a ladder or a
fixed-width cylinder with short-range couplings cannot hold true long-range order in that channel.
Quantum fluctuations forbid it in one dimension. What happens instead is a slow, log-corrected
power-law decay (the isotropic spin-½ chain goes as `√(ln r)/r`), and that decay makes a linear fit
of `m²` in `1/L` return a small positive intercept. Such an intercept is a failed extrapolation, not
order. Refit with the slow form and classify the region through D3. There are two exceptions, and
each has to be stated if it is invoked: an order parameter that commutes with `H` (the
ferromagnet), and power-law long-range couplings, which can stabilise such order. Check the declared
interaction range in `plan.md`.

**Which symmetry it breaks** gives you a prediction you can then check, and this is the step that
turns a plausible label into an established one. If the order breaks a symmetry with a finite
number of equivalent choices (two sublattices to pick between, two ways to dimerise), then the
infinite system has that many degenerate ground states, and at finite `L` the corresponding
energies must approach each other as the system grows. Measure them, **on the right boundary
conditions.** With open ends the test is valid only when a symmetry that survives in the finite
open system (a global spin flip, or inversion about the chain centre) maps the candidate ground
states onto each other, as it does for an Ising antiferromagnet or a chiral state. Then the
splitting closes exponentially with `L`, and two lowest states that stay firmly apart at every size
refute the claim. When the broken symmetry is translation itself, as for a dimer pattern or any
order that enlarges the unit cell, the open ends already break it explicitly and *select one
pattern*. The partner is then lifted by an O(1) amount, or replaced by an edge multiplet, at every
size, and its absence refutes nothing. Count that degeneracy on a periodic ring at small size
instead (`ed-validation`, after the gate), where the partners sit at distinct momenta and the
splitting is exponential.

Record all four: channel, `q*`, component, and the verified degeneracy together with the boundary
conditions it was counted on.

---

## D2. Is something bigger than a pair of spins ordered?

**The question.** No pair of spins is correlated at long range. But a phase can still be ordered
in something you cannot see by looking at two spins at a time: for instance a chain where every
second bond is strong and every other bond is weak. Every individual spin correlation there dies
off, and yet the pattern of bond strengths repeats forever. So: is anything like that going on?

**Which operator to try.** Do not guess, and do not work through a fixed list. Look at the
symmetry table in `plan.md`, find the symmetries that are still unbroken now that D1 has come back
empty, and for each one write down the operator whose pattern would reveal it breaking.

In practice that is a short list:

| Still unbroken | Operator to measure | If it orders, the phase is |
|---|---|---|
| translation | the bond operator `B_i = S_i · S_{i+1}`: look for a repeating pattern in `⟨B_i⟩` along the chain | bond order, or a valence-bond solid |
| time reversal | the scalar chirality `χ_i = S_i · (S_{i+1} × S_{i+2})` | a chiral phase |
| inversion (parity), with time reversal intact | the vector chirality `κ^z_i = (S_i × S_{i+1})^z = (S^-_i S^+_{i+1} − S^+_i S^-_{i+1})/2i`, even under time reversal and odd under bond inversion. Its correlator is a four-point object (`itensor-dmrg` has the pattern) | a vector-chiral phase |
| spin rotation, even though no single spin direction ordered | the quadrupole operator (see below) | spin-nematic |
| spin rotation about the field axis, in a field where magnons bind in pairs (D0) | the pair operator `P_i = S^+_i S^+_{i+1}`, correlated as `⟨P_i P^†_j⟩` and compared with the longitudinal `S^z` channel | a multipolar (spin-nematic) state, usually quasi-ordered (see D3) |

The quadrupole needs a word of warning. For `S ≥ 1` it is an on-site object,
`Q^{ab}_i = S^a_i S^b_i + S^b_i S^a_i - \frac{2}{3}\delta^{ab}S(S+1)`. For `S = 1/2` that
expression collapses to a constant and tells you nothing, so nematic order there has to be built
from two neighbouring spins instead. Measuring the on-site version on a spin-half chain returns a
flat line, which is easy to misread as "no nematic order" when in fact you asked a question with
no content.

**How to measure it.** Once you have the operator, everything is exactly as in D1. Build its
correlation function, form the order parameter exactly as `observables` defines it, extrapolate to
infinite size, and require a finite limit. Then verify the ground-state degeneracy the broken symmetry
implies, the same way D1a does. Because the symmetry broken here is usually translation, count it
on a periodic ring. A chain that dimerises has two ways to do it and the ring shows both, at
`k = 0` and `k = π`, with an exponentially small splitting. An open chain selects one of them and
shows a unique ground state, so the absence of a near-degenerate partner there is not evidence
against the order (D1a).

**The trap, and it belongs to open chains specifically.** The two ends of an open chain start off
an alternating strong-weak-strong pattern in the bonds, which fades as you move inwards but never
quite reaches zero at any finite length. So if you measure the strong-weak difference directly,
you get a non-zero answer even in a perfectly uniform phase where nothing is ordered at all.
Looking only at the middle third of the chain reduces the contamination without removing it.

Only a value that survives extrapolation to infinite length counts as order. The estimator to
extrapolate is the bond structure factor at the wavevector of the pattern you are testing, built
from the full bond-bond correlator exactly as `observables` defines it. Take those wavevectors from
the period list in D1a rather than assuming the alternation. `q = π` is the period-two case and the
one the rest of this section is written around, but a bond pattern of any other period peaks
elsewhere and contributes nothing at `π`, so reading only `π` reports "no bond order" for every
period but one. The uniform part of `⟨B_i⟩` sits at `q = 0`, so it contributes nothing at any
`q ≠ 0` and changing which period you test does not bring it back.
The end-induced alternation enters as a disconnected piece that vanishes as `1/L²` when the bulk is
uniform and gapped, and more slowly near criticality. In a genuinely dimerised open chain the
boundary *selects* the pattern, so the alternation it shows in the middle *is* the order and must
not be subtracted away. Report the disconnected and connected parts separately (`observables`
explains the decomposition) and let the extrapolation decide.

---

## D3′. Is the Hamiltonian the same everywhere along the system?

**The question.** Do the couplings and fields take the same value on every site and bond? Stage 0a
recorded this. They might fail to in two ways: drawn from a distribution, or varying
deterministically (a modulated or incommensurate field, for instance). Both matter here.

**Why it interrupts here.** D3 is about to measure how the entanglement grows with block size,
find that it grows like a logarithm, and read a central charge off the slope. That last move
assumes a uniform critical system, and neither kind of non-uniformity gives you one for free.

A strongly disordered critical chain really does show logarithmic entanglement growth, so the
measurement succeeds and the fit looks fine. But the slope is not a central charge. In a clean
critical chain it is fixed by the underlying field theory and names the universality class. A
disordered critical point is governed by a fixed point of a different kind, with no such field
theory behind it. The ground state there is built from singlet pairs formed between spins at all
separations (the strongest bonds first, then weaker ones across longer distances), which is a
different object entirely, even though the entropy grows the same way.

What comes out is an *effective* coefficient, and `disorder` explains how to report it. It is worth
having: it is universal, and its value identifies the phase.

What makes this worth interrupting for is that the wrong answer looks right. You get a number of
a believable size, sitting between the values you would recognise, with a good fit. Nothing
downstream can tell that it is meaningless, because every check that exists asks whether the fit
was good, and it was.

**Deterministic non-uniformity needs a different check.** With a modulated or incommensurate
potential there is no ensemble, so the disorder statistics do not apply, but a new possibility
does: the states may be localised rather than extended, in which case the region is not critical
at all and the entropy will saturate once the block exceeds the localisation length. Sizes below
that length look logarithmic. Before quoting anything, confirm the growth is still going at your
largest block, and look at whether a low-energy state is spread across the system or confined to
part of it.

**How to read it.** Drawn from a distribution: stop here and go to `disorder`, and come back only
with its answer. Deterministically non-uniform: run the localisation check above before
continuing. Uniform: carry straight on to D3.

---

## D3. Is this region critical?

**The question.** Is the region gapless, with correlations decaying as a power law rather than
exponentially?

**How to measure it.** Two independent signatures, and they should agree.

The entanglement entropy of a block grows logarithmically with block size in a critical region and
saturates in a gapped one. Fitting that growth gives the central charge: `scaling` owns the fit,
including the boundary-condition-dependent coefficient that is the usual way of getting it wrong.

Independently, correlations decay as a power law rather than exponentially. Fit `C(r)` in the
bulk, using pairs symmetric about the centre at fixed separation and excluding short distances
and the outer quarter of the chain at each end, and check.

**Before reading either of them, check they are converged in bond dimension.** This is the one place
in the tree where two independent measurements can be wrong together. A matrix-product state at
finite bond dimension caps how much entanglement it can carry and forces correlations to decay
exponentially beyond some length. So in a genuinely critical region, at bond dimensions that are
too small, the entropy flattens *and* the correlations look exponential, and the two agree on
"gapped". The energy will look perfectly converged throughout. `scaling` says what to check and how.

**How to read it.** Agreement between the two, once both are converged, with a decent fit and enough
sizes, is a critical region. Report `c` and the decay exponents, and use the exponents to say
*which* gapless phase it is. Measure the decay of every symmetry-allowed channel. The
slowest-decaying one is the dominant quasi-order and names the region (spin-density-wave-like,
dimer-like, pair- or nematic-like). In a `c = 1` region one number controls them all, the Luttinger
parameter `K`. In the standard zero-field convention the staggered transverse exponent is `1/(2K)`
and the staggered longitudinal one is `2K`, so the two multiply to one. At the SU(2) point
`K = 1/2` and both exponents are 1. At the `XX` point `K = 1` and they are ½ and 2. In a field the
longitudinal quasi-order moves to `2k_F` with the same `K`. Fitting two channels therefore
over-determines `K`. Use that as a consistency check, and report `K`. Disagreement is a signal,
not a nuisance: the usual cause is that you are near a boundary rather than inside a phase, and the block
entropy is
picking up the transition.

**The trap.** A vanishing gap is not sufficient evidence of criticality, and this arises
in two distinct ways.

If the region breaks a discrete symmetry, the lowest excited state in the same symmetry sector is
the degenerate partner of the ground state, and their splitting vanishes exponentially in `L`.
The region is gapped and degenerate, and it looks gapless if you measure only that splitting.
Cross-check against `m²` from D1: long-range order plus a vanishing same-sector splitting means
degeneracy, not criticality.

If you are running open boundaries, the lowest excitations may live on the ends rather than in
the bulk. A phase with protected edge modes has a splitting that vanishes exponentially in `L`
while its bulk gap stays wide open. Before concluding gapless, check where the excitation
actually is: measure its spatial profile, or pin the ends and see whether the small splitting
survives. If it does not, you were measuring the boundary.

---

## D4. Gapped, with nothing ordering: which kind is it?

You are here because nothing orders and the entanglement saturates. Two possibilities, and they
need different evidence.

**A constraint to apply first, because it can rule the answer out for free.** There is a theorem
about chains that says: if the model is translation invariant, has a continuous symmetry such as
rotations about an axis, and carries a half-odd-integer spin in each repeating unit, then the
ground state cannot be all three of unique, gapped and symmetric. It has to be gapless instead, or
degenerate with translation broken.

Check the three conditions against `plan.md` before going further. If they hold, then "gapped,
symmetric, unique" is not available to you, and a calculation that seems to show it is telling you
something else: most often that translation is being broken by an ordering you have not measured
yet, which sends you back to D2. If any condition fails (the couplings are random or modulated so
there is no translation symmetry, or every unit carries integer spin, or nothing continuous is
conserved), the theorem is silent and this paragraph does not apply. It also constrains the infinite
system: an open chain can carry states at its ends that evade the counting, which the edge-multiplet
paragraph below returns to.

**The two possibilities are locally indistinguishable, so both need the same measurement.** A
trivial gapped phase (a polarised region above saturation, a large-field paramagnet, a
decoupled-dimer state) and a symmetry-protected topological phase both show short-range
correlations, no order in any local channel, and often a ground state close to a product state.
"Looks like a product state" is therefore a hypothesis about either of them, never evidence for the
trivial label. The only thing that separates them is the structure of the entanglement spectrum,
and it costs nothing, because the entropy already required the same decomposition. So the trivial
label is reached when the measurement below comes back without protected structure. It is not
reached by recognition, and not by moving on. Trivial phases are real phases and they occupy large
parts of most phase diagrams. They still get their evidence.

**A symmetry-protected topological phase** is a gapped state with no order you can see locally,
which nonetheless cannot be smoothly turned into a product state unless you break a particular
symmetry along the way. Claiming one requires evidence *for* it, not just the failure of everything
else. There are two things to measure, and they are read together.

**The edge multiplet, which is nearly free.** Run the region with open ends and look at the lowest
few states. A phase of this kind carries excitations bound to the ends, so those states form a small
cluster whose splitting shrinks exponentially as the chain grows, while the bulk gap stays wide
open. The size of the cluster tells you what the edges carry. This is the same near-degeneracy that
is a nuisance when measuring the gap. Here it is the evidence, and it also tells you how to take the
next measurement.

**The entanglement spectrum is the one to trust, taken under three conditions.**

*Where to cut.* At a bulk cut on a unit-cell boundary, as declared in `plan.md`, and at the same
cut for every region you compare. On a multi-site unit cell the degeneracy structure depends on
where the cut sits within the cell. Cutting *through* a rung of a trivial rung-singlet state severs
a singlet and shows two exactly equal Schmidt values, which says nothing about the phase. So
degeneracy at an intra-cell cut is not evidence, and comparisons across regions are meaningful only
at one fixed cut.

*With the edge modes polarised.* With open ends, the block on one side of the cut contains a
physical edge. In a protected phase the edge modes at the two ends are entangled with each other
across the cut (in the symmetric sector they form a singlet), and that multiplies the bulk
structure by an extra factor whose weights converge only slowly with size. At a length of a few
correlation lengths the largest level can then look non-degenerate and the phase can be misread as
trivial. Read the spectrum with the edge cluster from the previous step polarised: run in the
sector where it is maximally polarised, or add a small field on the end sites. In a trivial phase
this changes nothing. In a protected phase it removes the edge factor and leaves the bulk structure
alone. Prefer the sector route when a charge is conserved. Where none is, the end field is safe even
though it breaks the protecting symmetry locally: it acts only at the ends, far from the cut, and
the protected structure at a bulk cut is set by the symmetry of the bulk, which an end field does
not touch. Dropping the field and losing the polarisation is the worse trade.

*Judged on the converged part, by trend.* Protected degeneracies are exact up to corrections
exponentially small in size, and they tighten as `L` grows. A real non-degeneracy persists.
Truncation splits the tail of the spectrum artificially, so the structure must also be stable as
`χ` is raised. Never use a fixed tolerance.

Under those conditions the reading is sharp. In a protected phase every level, the largest
included, sits in a degenerate multiplet of the protecting symmetry, all the way down, not just
the top two, which is the weaker version people often stop at. The multiplicity is fixed by that
symmetry (two in the familiar cases, and it need not be), so report what you observe. A single,
clearly resolved level anywhere in the converged spectrum, typically the largest, is a level the
symmetry does not protect, and it rules the protected label out with respect to that symmetry. That
is the positive evidence for "trivial". Where quantum numbers are on, store the charge labels with
the Schmidt values (`observables`), so multiplets are counted rather than guessed. The degeneracy
holds as long as the protecting symmetry is present and lifts once it is broken, which is why
naming the symmetry (below) is part of the claim rather than decoration. Two gapped regions whose
spectra differ in this structure, at the same cut and under the same protocol, cannot be the same
phase while that symmetry holds. So this is also the measurement that keeps two gapped regions from
being merged under one label (see the end of this stage).

**A string order parameter is worth measuring, but on its own it decides nothing.** It correlates
two spins through the whole stretch between them, and in the textbook case it stays finite while
ordinary correlations die. Two caveats stop it being a test. It is also finite in a conventionally
ordered antiferromagnet, so a non-zero value does not by itself distinguish anything. And it is
tied to one particular protecting symmetry, so a phase protected by a different one (inversion,
say) has none at all. A zero is therefore not evidence of absence.

Then name the symmetry doing the protecting, from the A2 table. This is not bookkeeping: the phase
exists only relative to a symmetry, and if nothing in `H` enforces it the label means nothing.

**One thing this system deliberately does not attempt.** There is a stronger kind of topological
phase, one that does not lean on any symmetry, and in one dimension it simply does not exist:
gapped states with no local order are either symmetry-protected or trivial, and that is the
complete list. It takes two dimensions or more, and the evidence for it is different in kind:
ground-state degeneracies that depend on the shape of the lattice rather than on any local
measurement. None of that is within reach here. If you think you are seeing it, write that in the
note and stop, rather than reaching for a diagnostic this setup cannot compute.

---

## D5. Unidentified

**This is a legitimate exit, and using it correctly is a mark of a good study rather than a
failed one.**

What is not legitimate is classification by exclusion: concluding "it must be topological"
because the other boxes came up empty. Absence of evidence for four labels is not evidence for a
fifth, and a label reached this way has no supporting measurement behind it at all.

One pattern in the data turns this exit into a lead rather than a dead end. An exact degeneracy
that persists across parameters and sizes, in the ground state, in the low spectrum, or in the
entanglement spectrum at the fixed cut, and that no symmetry in the Stage 0a table accounts for, is
evidence of a symmetry that table is missing, or of a fine-tuned point. Go back to `model-setup` A2
and test further candidates before writing the region off. A missing row there is the usual reason
nothing fit.

So when nothing fits, write down what you know and what is missing, specifically:

- which channels you measured and what each returned
- which signatures disagree with each other, if any do
- the specific measurement that would settle it, and its status after the three steps below.

A settling measurement is work before it is a sentence. Before a region is written up as
unidentified, take that measurement through three steps in order and record the outcome in
`RUN_SUMMARY.md`:

1. Look for it in your own stored outputs. A survey stores more than the analysis reads, and the
   number is often already on disk.
2. If it is not there, add it to `write_todos` and attempt it now, whenever it needs only a
   re-analysis of stored data or a run at sizes and settings this run has already completed
   successfully. One attempt. A timeout or a failure to converge is itself the result, recorded
   with its measured cost, and you move to step 3.
3. Only when both come back no, defer it, naming the specific cost or the missing method.

A deferral that skipped the first two steps is not a result. On a continuation, settings that
appear only in inherited data are evidence about the previous investigator's run, not about what
this one can afford.

"This region is gapped, has no order in the spin or bond channels up to `L = 64`, and shows no
string order. Distinguishing an SPT phase from a trivial one needs the entanglement spectrum at
larger sizes than we reached" is a useful contribution. "Possibly topological" is not.

---

## Before you leave Stage 3

Every region in the parameter box has a label, and every label carries:

- the measurement that established it, with its extrapolation
- the symmetry broken, or the invariant that is non-trivial, or an explicit statement that
  neither applies
- the predicted ground-state degeneracy, and the check that confirmed it
- for a region labelled unidentified, the missing measurement named.

**Then compare the regions with each other. The labels alone do not make a phase diagram.** Write
down, for each region, the discrete facts that define its phase: the set of broken symmetries,
gapped or gapless with `c` if gapless, the entanglement-spectrum structure at the declared cut
under the D4 protocol, the ground-state degeneracy, the plateau value if any, and whether `q*` is
locked to a commensurate value or floats (judged from its trend across the region and across sizes
rather than at one point). Then check three things. Across every *continuous* boundary at least one
of those facts changes, and the change is the one `transitions` named for that boundary. A
first-order line is exempt, because it can separate two regions of the same phase and end at a
critical point inside it. That is worth noting, not a contradiction. Any two regions that carry the
same label are either joined by a sampled path along which none of those facts changed and no
boundary was found, or are marked "identified by matching invariants, connectivity not
established". One phase may legitimately occupy two disconnected lobes of the box. And a boundary
or a feature (a fidelity dip, an entropy peak, a level crossing) *between* two regions that carry
the same label is an open contradiction. Either one of those facts distinguishes them after all, in
which case go and measure it, usually the entanglement spectrum, or the feature is recorded
explicitly as unexplained. It may not be dropped. Continuous variation of any quantity (the size of
an order parameter, the value of a floating `q*`, the entropy) is never evidence that two regions
are different phases.

Regions with no data point inside them do not get labels. They get marked unexplored, and
`transitions` decides whether they are worth the budget.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. extra channels routinely worth measuring, house thresholds for "clean extrapolation" -->
