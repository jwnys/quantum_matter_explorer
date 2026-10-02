---
name: model-setup
description: Read this first, before writing any Hamiltonian code, for any model. Turns a written spec into a Hamiltonian you can trust - which operator algebra the spec uses and how it maps onto the library's operators, what the model conserves, which symmetry sector the ground state lives in, boundary conditions, the system sizes to run, and the analytic anchors that will later prove the code is right. Stage 0a of the study.
---

# Stage 0a: from the spec to a Hamiltonian you can trust

Nothing here costs compute. All of it is cheaper than discovering, after days of compute, that
the phase diagram being mapped belongs to a model nobody asked about.

Five questions, in order. Each one has an answer that goes into `plan.md`, because Stage 0b will
check the code against these decisions and the write-up will report them.

| | Question | Why it comes first |
|---|---|---|
| **A1** | What operators does the spec actually mean? | Get this wrong and every energy is off by a fixed factor, and every field is off by a different one |
| **A2** | What does `H` conserve? | Decides which observables can see anything, and which sector you must work in |
| **A3** | Which symmetry sector does the ground state live in? | The standard DMRG recipe locks this, silently, and a wrong lock never announces itself |
| **A4** | What geometry, boundaries, and sizes? | Boundaries change the formulas you will fit later. Sizes change what you can see at all |
| **A5** | What will prove the code is right? | Stage 0b needs anchors, and one of them has to be sensitive to A1 |

---

## A1. What operators does the spec actually mean?

**The question.** A paper writes `X_i X_{i+1}` or `S^x_i S^x_{i+1}` or `σ^x_i σ^x_{i+1}`, and
these are not the same operator. The library gives you one of them. Which one does the spec mean?

**Why it matters more than it looks.** Spin and Pauli operators differ by a factor of two,
`S^a = σ^a/2`, so a two-site term differs by four and a one-site term by two. That is not a
uniform rescaling of `H`: it changes the *ratio* of a field to a coupling, which is exactly the
axis of most phase diagrams. Code a transverse-field Ising chain with spin operators when the
spec meant Pauli, and the critical field lands at `h = 0.5` instead of `h = 1`. Everything else
about the study is fine. The number is simply wrong, by a clean factor of two, and nothing
downstream will tell you.

**How to answer it.** Find what the spec says the operator eigenvalues are, and write the
conversion explicitly:

| The spec writes | Meaning | In ITensor `"S=1/2"` operators |
|---|---|---|
| `X_i`, `Y_i`, `Z_i`, or `σ^a_i` | Pauli, eigenvalues `±1` | `2 S^a_i` |
| `S^a_i` with `S = 1/2` | spin, eigenvalues `±1/2` | `S^a_i` directly |
| `S^±_i` | raising and lowering | `S^+_i`, `S^-_i` directly |
| `n_i`, `b_i` | hard-core boson | `n_i = S^z_i + 1/2`, `b_i = S^-_i`, `b^†_i = S^+_i` |

**That table is spin-½ only, and the first row is the reason.** Pauli matrices exist for a two-state
site. There is no `σ` for a spin-1 site, so `σ = 2S` has nothing to say there. At higher spin the
ambiguities are different ones (whether a single-site anisotropy is written `(S^z)²` or with the
trace removed, whether an exchange has been normalised by `S(S+1)` to make the classical limit
tidy) and the method is the same even though the table is not: find what the spec says the
eigenvalues are, and write the conversion down.

So a spec reading

$$ H = -\sum_i X_i X_{i+1} - h \sum_i Z_i $$

becomes, in the library's operators,

$$ H = -4\sum_i S^x_i S^x_{i+1} - 2h \sum_i S^z_i $$

Write both lines into `plan.md`. Not the reasoning: the two equations, side by side. A reader
should be able to check the factors in five seconds without reconstructing your thinking.

Watch for specs that hedge, like "`S^a_i` are spin-1/2 Pauli operators". That phrase is
self-contradictory and appears often. The eigenvalues decide: if the spec anywhere quotes a
result, a limit, or a critical value, work out which convention reproduces it.

**The trap.** You cannot catch this with the exact-diagonalisation cross-check in Stage 0b. That
check works by coding the model twice, independently, and comparing, which catches a
*misreading*, because two readings rarely go wrong the same way. A convention error is not a
misreading. Both codings make it, both agree beautifully, and the check passes. This is why A5
insists on an anchor whose value depends on the normalisation.

**Also record the spin length.** `S = 1/2` is the common case but not the only one, and it sets
the site type (`siteinds("S=1", N)`), the local Hilbert space dimension, and how far
exact diagonalisation can reach in Stage 0b.

---

## A2. What does `H` conserve?

**The question.** A symmetry of `H` is an operation you can perform on the whole system (rotate
every spin, shift the chain by one site, flip every spin over) that leaves the energy unchanged.
Which of those does this model have?

This is the most useful thing to know before computing anything, because almost every phase is
defined by a symmetry that the ground state stops respecting. If you did not write down that the
symmetry was there, you will not think to check whether it broke, and you will miss the phase.

**How to answer it: compute it, do not reason about it.** Reading a Hamiltonian and deciding by eye
which symmetries survive is exactly the kind of thing that is easy, quick, and wrong. Every
candidate here is a commutator, and a commutator at eight sites costs you a second.

For each operation, build it explicitly as a matrix on the full Hilbert space:

- a spin rotation, or a flip, is a product of the same single-site unitary on every site
- a translation or an inversion is a permutation of the sites
- time reversal is complex conjugation composed with a π rotation about `y`, and being antiunitary
  it needs the conjugated form of the test below: compare `U H* U†` against `H`, not `U H U†`.

Then build `H` densely at two small sizes (four and six sites is plenty, and keep the local
dimension in mind, since a dense matrix grows as its power) and report
`‖U H U† − H‖` for each candidate. Use your own dense code rather than the DMRG path: you are
testing the Hamiltonian here, not the solver. Put the numbers in `plan.md`, one line per candidate
with the operation written out. Something that survives at both sizes is a symmetry. Something
that does not, is not.

Candidates always worth testing: rotations about each axis, both continuous and by π, the full
SU(2), the lattice translations and inversions the geometry you chose in A4 allows, and time
reversal. A continuous rotation about an axis `a` is tested through its generator. The condition
`‖[H, Σ_i S^a_i]‖ = 0` is equivalent to invariance under every rotation angle, and the full SU(2)
means all three generators. A discrete operation (a π rotation, a flip, a translation, an
inversion) is tested as the explicit unitary. Add whatever else the structure of the spec
suggests. If a candidate is awkward to write as a matrix (an unusual lattice symmetry, say), record
that you could not test it and say what you checked instead.

Two reasons this is worth the minute it costs, rather than being decided by inspection. It is exact,
and the failure mode of inspection is silent: you conclude a symmetry is absent, never look for its
breaking, and lose the phase that breaking produces. And it gives the physics critic a number it can
re-derive, which no amount of prose reasoning does.

**One distinction the calculation will not make for you.** Record the symmetry of the *Hamiltonian*
(the pattern of couplings), not of the finite piece you happen to run. Open ends break translation
explicitly near the boundary, which is why local order parameters measured near an edge are
contaminated, and `phase-id` D2 handles that where it belongs. If you record the boundary here you
switch off the structure factor and the whole bond-order branch for every open chain you run, which
is most of them. Test translation on a periodic system of the same couplings, or reason about the
bulk pattern and say that is what you did.

Put the result in `plan.md` as a table. Four later steps read it: `observables` uses it to decide
what to measure, A3 below uses it to pick the sector, `phase-id` uses it to predict how many
degenerate ground states each ordered phase should have, and `reporting` uses it to name them.

**The trap: deciding by adjective instead of by calculation.** The reasoning that goes "this model
is anisotropic, therefore rotations about `z` are not a symmetry, therefore I must switch off
quantum numbers and measure each spin component separately" sounds fine and is wrong for a whole
family of models.

Take a model where `S^z_i S^z_j` has a different coefficient from `S^x_i S^x_j + S^y_i S^y_j`.
That is anisotropic by any reasonable use of the word. But rotating every spin about the `z` axis
still leaves it alone, because the `z z` term does not involve the rotated components at all and
the in-plane part is rotationally symmetric within the plane. So `S^z_tot` is conserved after all.
The same holds for a single-site term like `D(S^z)^2`, and for a Dzyaloshinskii-Moriya vector
pointing along `z`.

Getting this wrong costs you twice. You switch off quantum numbers and lose a large factor of
speed for nothing. And you go looking for a difference between the `x` and `y` correlations that
cannot exist, since the symmetry you failed to notice guarantees they are equal.

So do the calculation. Ask whether the operation leaves `H` unchanged. Never ask what the model
is called or how it is described.

**One further source of candidates, which matters most when the model is unfamiliar.** An exact
degeneracy that persists across parameters and sizes, in the ground state, in the low spectrum,
or in the entanglement spectrum, and that no symmetry in this table explains, is evidence of a
symmetry the table is missing (or, less often, of a fine-tuned point). Treat it as an instruction
to come back here and test further candidates (a spin rotation combined with a translation, a
rotation on one sublattice only, a duality) before any phase label is attached downstream.
`phase-id` sends you back for exactly this reason.

---

## A3. Which group of states does the ground state live in?

**The question.** Suppose A2 found that the total spin along `z` is conserved. Then every state
has a definite value of it, and no amount of time evolution or energy minimisation moves between
values: the states split into separate groups, one per value, and these groups are called
sectors. DMRG searches inside a single sector and never leaves it. So: which sector holds the
ground state?

**Why this is the most dangerous step in Stage 0a.** The standard opening move:

```julia
sites = siteinds("S=1/2", N; conserve_qns=true)
psi0  = random_mps(sites, ["Up","Dn"][((1:N).%2).+1])
```

builds an initial state with `S^z_tot = 0`, and DMRG conserves that for the entire run. If the
true ground state has non-zero magnetisation, you will never see it. There is no error, no
warning, and no convergence problem. You get a perfectly converged ground state of the wrong
sector, at every parameter point, and the phase diagram that follows is the phase diagram of a
constraint you imposed by accident.

**How to answer it.** Three cases, and A2 already told you which one you are in.

*The total spin along `z` is not conserved.* Set `conserve_qns=false`. There is no sector to
choose, and as a bonus the `x` and `y` correlations can now differ from each other, which you
will want later.

*It is conserved, and nothing in `H` favours one value over another.* No magnetic field along `z`,
no chemical potential: just exchange. Then `conserve_qns=true` gives you a large speed-up, once
you know which sector to ask for.

Do not assume the answer carries across the scan. A conserved charge with nothing conjugate to it
can still change its ground-state value as a coupling varies, so check at both ends of every scan
axis and not only at one point.

Do not guess which sector. Run the plausible ones at a small size and compare the energies. Or,
cheaper and complete, read the sector off the full-space diagonalisation of Stage 0b, which returns
the global ground state and therefore its magnetisation directly. A ferromagnetic ground state at
maximal `|M|` is exactly what a short list of "plausible" sectors misses, and the full space cannot
miss it. Either way it costs seconds and it is the only thing that settles it. Guessing has a
specific failure mode: you get a perfectly converged state, at every parameter point, of a
constraint you imposed by accident, and nothing downstream looks wrong.

**Work out which sector values exist before choosing between them.** They run from `−S_max` to
`+S_max` in whole steps, where `S_max` is the sum of the spin lengths over all sites. Depending on
that sum the values are integers or half-integers. So on a chain whose spins sum to a half-integer
there is no zero sector at all, and an instruction to "run at zero" is not merely wrong there but
meaningless. Any model with more than one kind of site deserves the enumeration rather than the
habit. If a spin-flip symmetry survives, one sign is enough.

*It is conserved, and `H` contains a magnetic field along `z`.* The field pays the system to have
more spin pointing up, so the best value comes from a competition with the exchange and it moves
along the field axis. There is no single right sector, but there is a shortcut, and it is worth
taking.

**The field does not change `H` inside a sector.** Writing `H = H₀ − h M`, the total `M` is fixed
within a sector, so `E(M, h) = E₀(M) − h M` exactly. One scan over `M` at zero field therefore gives
you every field at once: at each `h`, the ground state is whichever `M` minimises `E₀(M) − h M`. On
a small test this replaced sixty-three runs with nine, and it is exact rather than approximate:
confirm it once against a direct field scan at small size, then use it.

What falls out of that single scan is the whole magnetisation curve, which is not a diagnostic you
use to find the physics. It *is* part of the physics. Flat stretches, where one `M` wins over a
range of field, are phases held flat by a gap. Jumps where the minimising `M` skips a number of
values that grows with `N` are first-order transitions. A skip by a fixed small step (two at a
time, say) that persists as `N` grows is something else, magnons binding into pairs, and
`phase-id` D0 says what to do with it. The field at which it reaches its maximum is a phase
boundary you would otherwise have to go looking for. You were going to need all of this anyway.

**Record the policy in `plan.md`, and hand it to Stage 0b.** Exact diagonalisation works in the
full Hilbert space and returns the global ground state. If your DMRG point sits in a fixed
sector, the two disagree, and that disagreement is about the sector, not about the Hamiltonian.
Stage 0b will misdiagnose it as a coding error unless you told it what you did.

---

## A4. Geometry, boundaries, and sizes

**Boundaries.** Use open boundaries for DMRG unless there is a specific reason not to. Periodic
boundaries force the matrix-product state to carry correlations the long way around the ring,
which costs roughly `χ → χ²` for the same accuracy. If the spec says periodic, that is a
deviation worth making, not one worth making silently: say in `plan.md` that you are running open
chains and why, and note it in the write-up. If you genuinely need periodic results (level
spectroscopy in `transitions` is the usual reason), take them at small sizes only.

Whatever you choose, carry it forward. Several formulas you will fit in `scaling` have
boundary-dependent coefficients, the entanglement scaling most of all, so the choice you make now
has to travel with every number that comes out of them. `scaling` owns those fits and states the
coefficients.

**Sizes.** Decide the list of system sizes before you start, and choose sizes that can actually
hold the patterns you expect to find. A pattern that repeats every two sites needs an even length. A
pattern that repeats every four needs a length divisible by four. When you do not yet know which
patterns to expect, which is the normal situation with an unfamiliar model, do not let this
enumeration stop at period two. Choose lengths divisible by every small period you cannot yet
exclude. With nothing known, that means divisible by 2, 3 and 4 at once: lengths such as 24, 36
and 48 hold any pattern of period 2, 3, 4 or 6, while 20 or 32 make period-3 order structurally
undetectable at any bond dimension. The divisible lengths cost nothing extra. Where the periodicity you expect
is not a whole number of sites (a spiral at some incommensurate angle), no length holds it exactly,
and how much that matters depends on the boundary conditions in ways that are not obvious. Run two
sizes and look, rather than reasoning about it.

If your list mixes sizes that fit the pattern with sizes that do not, the extrapolation comes out
scattered. That scatter looks exactly like poor convergence, and the natural response is to spend
compute raising the bond dimension, which will not help at all because nothing was unconverged.
Choose the sizes once, use the same ones everywhere, and write them down.

**Geometry beyond a chain.** DMRG works along a line. To run it on a ladder or a narrow cylinder,
you number the sites one after another along some path that snakes through the lattice, and the
calculation then treats that numbering as a chain. Which path you choose is a real decision: it
determines which neighbours end up far apart in the numbering, and therefore how much
entanglement the state has to carry. Write the path into `plan.md` and keep it fixed for the
whole study, because results from two different paths are not comparable.

If the model is genuinely two-dimensional, this system is out of its depth, and the honest move
is to say so rather than to quietly solve a chain instead. Reduce it deliberately, write the
reduction into `plan.md` with the reason, and label the study a reduced model in the title and
abstract of the note. A reduction that is stated is a legitimate approximation. The same
reduction unstated is a wrong answer.

---

## A5. What will prove the code is right?

**The question.** Stage 0b has to establish that the Julia in front of you implements the model in
the spec. What can it check against?

**How to answer it.** Look for parameter values where the answer is known without a computation.
Three kinds are almost always available:

- **A polarised limit.** Send a field to infinity, or a coupling to zero, and the ground state
  becomes a product state whose energy you can write down by hand.
- **A decoupling limit.** Set a coupling to zero so the system falls apart into pieces you can
  solve separately: single sites, isolated pairs, two independent chains.
- **A special exactly solvable point**, if the model has one.

**At least one anchor must be sensitive to the operator convention from A1.** This is the whole
reason the anchors exist rather than relying on the stage-B cross-check alone. A polarised limit
does the job naturally: with a field written in Pauli operators the energy per site approaches
`-h`, and with the same field written in spin operators it approaches `-h/2`. If your code
reproduces the wrong one, A1 is wrong, and you have found it for the price of a single cheap run.

**A frequent error.** Reference values quoted in the literature are
almost always thermodynamic-limit values, and you are running finite systems. The Heisenberg
chain has `e_∞ = 1/4 - ln 2 = -0.4431`, and a short open chain does not give that number: it has
`N-1` bonds instead of `N` and two ends that behave differently from the bulk, so it comes out
several percent away at the sizes you smoke-test with.

Two ways this goes wrong, in opposite directions. You compare your `L = 16` number to `-0.4431`,
see a few percent, and go hunting for a bug that does not exist. Or you have a real two percent
error, compare it to `-0.4431`, see a few percent, and shrug it off as finite size.

So compare like with like. Either take the reference at the same size and boundary conditions
(your own exact diagonalisation in Stage 0b is the easiest source), or compare a bulk quantity such
as a mid-chain bond energy, or extrapolate first and compare the extrapolation. Do not compare a
finite-size number to an infinite-size number and expect to learn anything.

**Anchors can also announce themselves in the data, and the announcement is easy to miss.** If the
ground-state energy is exactly constant along a stretch of a scan, to full precision rather than
approximately, and the overlap between neighbouring points is one, then the same state is the exact
ground state throughout that stretch. It is therefore an exact eigenstate of every term whose
coefficient varied, which is provable in a few lines of operator algebra, usually because a simple
product state is annihilated by each of those terms. Do the algebra and you gain the strongest
anchor available, an exact energy across a whole region, valid at every size. It also sharpens the
transition out of that region: the flat branch has exactly zero slope, so the E1 derivative test in
`transitions` reads cleanly at the boundary. A slope appearing abruptly on the other side is a
first-order signature, and a slope growing continuously from zero is a continuous one, with a fully
polarised state above saturation as the standard example of the second kind. Exact constancy is
information. Never file it as a boring number.

---

## A recommended way to write the Hamiltonian: a term list

Not required. `build_hamiltonian` written directly in Julia is a perfectly good answer, and if
that is clearer for your model, do that.

But there is a pattern that pays off as models get less standard. Instead of building the
`OpSum` inline, first write out the terms as data:

```json
{"terms": [
  {"coupling": -4.0,  "ops": [["Sx", 1], ["Sx", 2]]},
  {"coupling": -2.0,  "ops": [["Sz", 1]]}
]}
```

and let `build_hamiltonian` walk that list. The gain is that one representation covers cases
that otherwise each need their own code path. Nothing in it assumes how many sites a term touches
or how far apart they are, so longer-range couplings, terms on three or more sites (a chirality,
a ring exchange), ladders and cylinders, non-uniform or random couplings, and modulated fields all
become entries in a list rather than new loops.

The larger gain is that the Hamiltonian becomes checkable. Somebody (the physics critic, or you in
three weeks) can count the terms and compare that count against the geometry you declared, one
interaction range at a time. An open chain has one fewer nearest-neighbour bond than it has sites.
Close it into a ring and you gain one back, so a list with the wrong count is a Hamiltonian with
the wrong boundary conditions. A ladder or a longer-range model has its own count, which is the
point of deriving it from the declared geometry rather than memorising the chain case. Reading
Julia for the same information is slower and less reliable.

If you write the list, save it as `model.json` alongside the data.

---

## Before you leave Stage 0a

`plan.md` should contain, in a form somebody else can check:

- the Hamiltonian as the spec writes it, and the same Hamiltonian in library operators, with the
  conversion factors visible
- the symmetry table from A2
- the sector policy from A3, and how Stage 0b should compare against exact diagonalisation given
  that policy
- boundary conditions, the site numbering if it is not a plain chain, and the list of system
  sizes, with the reason each one can hold the patterns you expect
- at least two anchors, one of them sensitive to the operator convention.

None of this needs to be long. It needs to be explicit, because Stage 0b checks the code against
it and every later stage assumes it.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. house conventions for particular lattices, preferred anchors, local naming -->
