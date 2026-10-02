---
name: observables
description: Read this before the Stage 1 survey, and again whenever a region refuses to classify. Covers how to decide what to measure for a Hamiltonian you have not seen before, the definition of the order parameter that later phases extrapolate, and - most importantly - what each measurement is structurally blind to. Most wrong phase diagrams come from measuring something that could not have seen the answer.
---

# What to measure, and what each measurement cannot see

Two jobs. First, decide what to measure for *this* Hamiltonian rather than copying a list. Second,
know what each quantity is blind to, because a measurement that cannot see the answer returns a
clean, converged, meaningless number and nothing downstream will flag it.

## Map

| Quantity | What it settles | Blind to |
|---|---|---|
| structure factor `S(q)` | ordering wavevector, and the order parameter as its peak | incommensurate `q*` on a coarse grid, or anything at all without translation invariance |
| correlator `C(r)`, by component | which axis ordered, and power law versus exponential | the axis, if you measure only the scalar `S_i · S_j` |
| entanglement entropy `S(ℓ)`, and the Schmidt values behind it | gapless versus gapped, and the central charge. From the Schmidt spectrum at a unit-cell-boundary cut, protected versus trivial gapped (`phase-id` D4) | which *ordered* state is present. The cut is along the site ordering, not through space |
| gap | gapped versus gapless | whether the state you found is the physical excitation, a degenerate partner, or an edge mode |
| ground-state energy `E(λ)` and its derivatives | first-order versus continuous character of a boundary (`transitions` E1) | boundaries where only the *kind* of order changes. The energy is smooth there |
| fidelity `\|⟨ψ(λ)\|ψ(λ+δλ)⟩\|` between neighbouring points | that the state changed character, with no order parameter assumed | infinite-order transitions, where it shows no clean feature. It is also zero across a sector change, for trivial reasons |
| local expectation `⟨O_i⟩` | almost nothing, in a symmetric finite system | it is zero by symmetry (see the last section) |

---

## Choosing what to measure

The temptation is to reach for the standard battery (spin structure factor, dimer order, maybe
chirality) and hope the answer is in there. On a model you have seen before that works. On a new
one it fails silently, because you find only the order you thought to look for.

**The rule.** List the symmetries of `H` from the Stage 0a table. For each symmetry that could
break, the order parameter is an operator that transforms non-trivially under the full symmetry
group but is invariant under the subgroup you expect to survive. Measure how its correlations
decay.

That single rule generates the whole standard battery, which is why you do not need the battery:

| Symmetry that breaks | Operator it hands you | The phase people call it |
|---|---|---|
| spin rotation | the spin itself, resolved by component | magnetic order |
| translation | a bond operator, or any local energy density | dimer, valence-bond solid, density wave |
| time reversal | a chirality, `S_i · (S_j × S_k)` | chiral order |
| inversion (parity), with time reversal intact | the vector chirality `(S_i × S_{i+1})^z` | vector-chiral order |
| spin rotation, with spin flip surviving | a quadrupole (two-site at `S = ½`) | spin-nematic |
| spin rotation about the field axis, where magnons bind in pairs (`phase-id` D0) | the pair operator `S^+_i S^+_{i+1}` | multipolar / spin-nematic, usually quasi-ordered |

A model whose symmetry is not on that list gets the same treatment: write down the operator that
distinguishes the symmetric state from the one you suspect, and correlate it. That is the whole
method, and it is why this section is a rule and not a longer table.

**What this assumes.** That Stage 0a produced an honest symmetry table. If a symmetry was missed
there, no amount of measuring recovers it: you will measure a complete set of channels for the
wrong group. A region that refuses to classify in Stage 3 is more often a missing row in that
table than a missing observable here.

**And that you check which operators exist at this spin length.** The rule hands you an operator.
Whether that operator is non-trivial depends on `S`. The clearest case is the quadrupole, which is
a genuine on-site object for `S ≥ 1` and collapses to a constant at `S = ½`, where nematic order
has to be built from two neighbouring sites instead. Measuring the on-site version on a spin-half
chain returns a flat line, which reads as "no order in this channel" when in fact the question had
no content. Before measuring a channel, confirm the operator is not identically zero or constant in
the local Hilbert space you actually have.

---

## Running the survey

**Sketch the box with exact diagonalisation before spending DMRG on it.** For spin-½, and for any
model whose local dimensions allow `N ≈ 10–16`, sweep the parameter box at a small size first. Per
point, record the ground state's sector and quantum numbers, the low-lying spectrum with its labels,
the gap, the correlators at the accessible momenta, and the fidelity to the neighbouring point.
That fidelity is trivial with exact vectors when the ground state is unique. Where it is (nearly)
degenerate, compare subspaces or skip the point. Seconds per point buys the sector map across the
whole box (which feeds the Stage 0a sector policy and catches a sector that changes in the middle
of a scan, not only at its ends), level crossings that flag candidate first-order lines, fidelity
dips that flag candidate boundaries of any kind, and a DMRG grid designed from evidence rather than
guessed. The same data later feeds level spectroscopy (`transitions` E3) and degeneracy counting.

**The sketch steers. It never labels.** No phase label, boundary position, or "nothing here"
conclusion may rest on `N ≤ 16` alone. Infinite-order transitions are invisible there,
incommensurate wavevectors snap to the coarse momentum grid, narrow phases fall between resolvable
features, and the finite-size gap is of order `1/N` everywhere. Every feature and every apparent
absence is provisional until the DMRG finite-size analysis. The sector map in particular is
re-verified at production sizes wherever it decides a `conserve_qns` choice. The sketch loses value
as the spin length grows (`S = 1` reaches `N ≈ 10`). It is then optional. The DMRG survey is not.

**Then the DMRG survey.** A coarse scan at small size and moderate bond dimension, measuring the
full cheap battery at every point (energy, mid-chain entropy, every symmetry-allowed two-point
channel, the one-point profiles, the Schmidt values at the designated cuts, the fidelity to the
neighbouring point), each array stored with the scalar companions fixed in `plan.md`, and refining
near *any* feature in *any* curve, with the sketch's flags as the first targets. Re-scan finer between two nearby features. Two boundaries closer than the grid
spacing look like one, and that is how narrow intermediate phases, a chiral or nematic sliver
between two large phases, get missed.

---

## The order parameter

**The definition, which is fixed here and used unchanged everywhere else.** For a channel with
correlator `C_ij` and `N` sites at positions `r_i`:

$$ S(q) = \frac{1}{N^{2}} \sum_{ij} C_{ij} e^{i q (r_i - r_j)} , \qquad m^{2} = S(q^{*}) $$

with `q*` the peak. Long-range order means `m²` extrapolates to a finite constant as the system
grows. Nothing else counts: not a large `S(q*)`, not a growing one.

**Two things about that normalisation are deliberate.** The `1/N²` means `m²` is `S(q*)` itself,
with no further division: there is no intermediate object to divide by `N` twice or not at all,
which is a mistake that costs a factor of `N` in either direction and is invisible once made. And
the positions `r_i` are the *physical* ones. On a chain they are just the site index, but on a
ladder or a cylinder the index runs along the path the calculation was laid out on, and a transform
in that index is not `S(q)` for any `q`.

**Why the normalisation carries the whole argument.** If correlations survive to infinite distance,
every pair contributes and the double sum grows like `N²`, so `m²` settles. If they decay as a power
of distance (what a critical region does), the sum grows more slowly and `m²` slides to zero. Both
cases show a raw peak that gets taller with system size. Only the normalised quantity tells them
apart, and reading the raw peak instead is the most common way a critical region gets reported as
ordered.

**What a non-zero one-point function does to it.** Whenever `⟨O_i⟩` is not zero, `S(q)` splits
into two parts, and reading it correctly means knowing which is which:

$$ S_{\mathrm{full}}(q) = \Big|\frac{1}{N}\sum_i \langle O_i\rangle e^{iq r_i}\Big|^{2} + S_{\mathrm{conn}}(q) $$

The first term is the transform of the one-point profile itself. The second, the *connected* part,
built from `⟨O_iO_j⟩ − ⟨O_i⟩⟨O_j⟩`, measures fluctuation correlations around that profile. Neither
is "the right one" in general. The profile *is* the order when the boundary has selected a pattern
(an open dimerised chain) or when the calculation has settled on one symmetry-broken state, which
DMRG at finite bond dimension often does. Subtracting it then reports "disordered" in an ordered
phase. The profile is *contamination* when something explicit produced it: a field, a fixed
sector, the open ends, the Friedel oscillations a field induces. So always measure and store the
profile alongside the correlator, and then:

- at `q* = 0`, never claim spontaneous order from `S(0)` in a channel whose uniform `⟨O⟩` is
  explicitly non-zero (the magnetisation in a field or a fixed sector, the bond average, the
  quadrupole in an anisotropic model). Uniform ferromagnetic order is read from the sector analysis
  (`model-setup` A3, `phase-id` D0), not from here.
- at `q* ≠ 0` the full correlator is the estimator to extrapolate. Do not subtract by default, for
  the reason above.
- where the profile has structure at `q*` (end-induced alternation, Friedel oscillations at
  `2k_F`), report the two parts separately. In a non-ordered phase the profile part vanishes with
  `L`, as `1/L²` when the bulk is gapped and uniform and more slowly near criticality, which is
  where a careless extrapolation gets caught. Small sizes overestimate `m²` there. The
  extrapolation decides, and having both parts on record is what makes a fake peak diagnosable.

**The `q` grid.** The sum is finite and evaluates at any `q` you like, so use a dense grid and fit
the peak position rather than restricting to a coarse set. A grid whose spacing is comparable to the
distance between competing wavevectors will snap an incommensurate `q*` onto a commensurate one, and
turn a spiral into a phantom two-sublattice phase.

**When to work in real space instead.** For a single realisation of a model with random or modulated
couplings, `q` is not a good label and the transform mixes unrelated things. Take `C(r)` at long
distance directly. Note that averaging over disorder realisations restores translation invariance,
so the *averaged* correlator does have a well-defined transform. For random models, look at the
distribution over realisations rather than at a single number. `disorder` covers which statistic to
take and what the distribution tells you.

---

## Correlations, and which component

For anything but a fully isotropic model, correlate each spin component separately. The scalar
`⟨S_i · S_j⟩` is the sum of the three component correlators, so a region ordering along `x` and a
neighbouring region ordering along `y` give the *same* scalar correlator, the same `q*`, and the
same energy. The boundary between them is invisible in that channel, and the two regions get
merged into one phase.

**Whether resolving the components can tell you anything at all is a question with an answer**, and
`phase-id` D1a has it: ask whether a symmetry of `H` maps one component onto another. If one does,
the correlators are equal by symmetry and separating them is wasted effort. Measuring both at one
point settles it in seconds and costs nothing.

One code constraint, which is not the same question: `correlation_matrix(psi,"Sx","Sx")` will not
run with quantum numbers switched on, so those specific measurements need them off. That is a
property of the tool, not of the physics.

---

## Entanglement entropy

Its job is to separate gapless from gapped, and in a gapless region to identify the universality
class through the central charge. It says nothing about *which* order is present, so it never
substitutes for an order parameter.

**Preconditions worth stating.** The coefficient in the logarithmic growth depends on the boundary
conditions, so the choice recorded in Stage 0a has to travel with any quoted central charge.
`scaling` has the forms and the arithmetic. The point here is only that the number is meaningless
without the boundary conditions attached to it.

And the "block" whose entropy you are computing is a contiguous run of sites *in the ordering used
to lay the system out*, not a compact region of space. On a chain those coincide. On a ladder or a
cylinder they do not, and the entropy you measure depends on the path chosen in Stage 0a, which
is why that path is recorded and why entropies from two different paths cannot be compared.

**Keep the Schmidt values, not only the number made from them.** Computing `S` already required
the full Schmidt spectrum, and that spectrum, not the scalar, is what separates a protected gapped
phase from a trivial one (`phase-id` D4). Store the leading values (sixteen or so) at a few
designated bonds, the central unit-cell-boundary cut and its neighbours one cell away, with their
conserved-charge labels when quantum numbers are on, under a canonical key. That is tens of numbers
per point, not the full spectrum at every bond, which would swamp the data files. The same rule
applies to anything else the solve has already paid for, such as bond energies and one-point
profiles, that a later stage may need. Deciding afterwards that one was needed turns a survey into
two surveys.

The mid-chain entropy recorded along a scan is also a free boundary flag. It peaks or kinks at a
transition (`transitions`).

---

## Gaps

Know which gap you measured. The number is often small for reasons that have nothing to do with
the phase being gapless, and there are three distinct ways this happens.

**A degenerate partner.** In a region that breaks a discrete symmetry, the lowest excited state in
the same symmetry sector is the partner of the ground state, so their splitting vanishes
exponentially with `L`. The phase is gapped, and the measurement says gapless. Cross-check the
order parameter: long-range order together with a vanishing same-sector splitting means degenerate,
not critical.

**An edge mode.** Under open boundaries some phases carry excitations localised at the ends whose
energy is exponentially small while the bulk gap stays wide open. Before concluding gapless, look
at where the excitation actually lives: measure its spatial profile, or pin the ends and see
whether the small splitting survives.

**The wrong sector.** If the model conserves a charge, the physically interesting gap is often the
cost of changing that charge, which means comparing ground states in two different sectors rather
than two states within one.

---

## Local expectation values, and pinning fields

**Before measuring a one-site expectation value, ask whether it is zero by symmetry.** The test:
`⟨O⟩` vanishes identically when `H` has a symmetry under which `O` is odd, *and* the state you
computed respects that symmetry. Eigenstates of a symmetric Hamiltonian are symmetry eigenstates,
so an odd operator averages to nothing in them. Whatever small number appears is numerical symmetry
breaking, and it depends on the initial state, the bond dimension and the sweep count rather than
on the physics.

That is why an order parameter for a symmetry-breaking phase comes from correlations, which are
even under the symmetry and survive.

But the test has two halves, and the second one matters as often as the first. `⟨S^z_i⟩` is *not*
zero when a field along `z` is present, because then nothing makes it odd, and `phase-id` D0's
whole magnetisation programme depends on that. Nor is it zero when the run is confined to a sector
with non-zero total spin, where it averages to the magnetisation per site. Nor when the couplings
are random or modulated, so no symmetry relates one site to another. And profiling a one-site
quantity along the chain is the standard way to tell a bulk excitation from one living on an edge.
Apply the test. Do not apply the conclusion.

**Reduce every stored profile to two scalars: a bulk value and an end value.** The bulk value is
the average over the middle third. The end value is the summed excess of the outer few sites over
the bulk value, one number per edge or their sum. The pair costs nothing and answers a question the
bulk average cannot see, which is where the quantity lives. One reading deserves spelling out. A
conserved total pinned at the same quantised value across a wide stretch of field, with a flat bulk
profile and the difference sitting in the end value, is a gapped state holding that quantum at its
ends. It is not a gapless region, whatever the entropy magnitude suggests. The plateau logic of
`phase-id` D0 and the edge-multiplet step of D4 are where such a region goes next.

**Pinning fields are the sanctioned exception, with two rules.** Add a small field that selects one
of the symmetry-related states, and the local expectation becomes meaningful, but only in the
limit `h → 0` taken *after* `L → ∞`. A finite value at finite field proves nothing, because the
field forces one even in a disordered region.

And never quote a pinned energy as the model's ground-state energy. The pinned Hamiltonian is a
different Hamiltonian, and its energy is shifted at order `h · m`, which for a typical pinning
strength is several orders of magnitude above DMRG's own accuracy. Any point whose energy you plan
to report, or compare against an anchor or an exact-diagonalisation check, has to be run at zero
pinning field.

---

## Keys and consistency

Fix the key names in `plan.md` before the survey and use them unchanged in the Julia, the JSON and
the note. The one that bites is saving a structure factor under a key that names a different
correlator from the one it was built from: two different objects then ship under one name, and
the mistake is invisible until someone tries to reproduce the figure.

Record, per channel: the correlator it came from, the `q` grid, the component if resolved, and the
one-point profile it was measured against. Record the leading Schmidt values at the designated cuts
with every run (see above).

**An array is not a finished measurement. Its scalars are.** Every array-valued key in the plan's
observable table gets its scalar companions, named in the same table at the same time: a structure
factor gets `m2_<channel>` (its normalised peak, defined above) and `qstar_<channel>` (the fitted
peak position), a profile gets its bulk value and its end value (the reduction above). The analysis
then reads the scalars, plotted against the scan parameter, and reaches into the arrays only to
check something the scalars flagged. Two reasons. A survey analysed straight from raw arrays tends
to be analysed poorly or not at all, while the same physics read from planned scalars gets used.
And a reduction invented during analysis, after the data has been seen, is where made-up thresholds
creep in. Plan the reductions before the survey, together with the keys.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. channels routinely worth measuring for the systems you study, house key names -->
