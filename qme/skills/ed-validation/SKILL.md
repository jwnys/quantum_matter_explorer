---
name: ed-validation
description: Read this before writing any exact-diagonalisation script, and whenever a validation check fails. Covers proving that the DMRG code implements the model in the spec - analytic anchors, an independent small-system diagonalisation, and what to do when the two disagree - plus the ways exact diagonalisation stays useful after the gate has passed. Stage 0b.
---

# Proving the code is the model

Stage 0a decided what the model is. This stage establishes that the Julia in front of you
implements that model and not a near neighbour of it. Everything downstream inherits the answer,
and the failure being caught is silent: a Hamiltonian with a wrong prefactor, a wrong boundary
term or a wrong sector converges beautifully and produces a phase diagram of a different model.

Two independent checks, and they catch different things.

## Map

```
analytic anchor      →  does the code reproduce a value you can write down by hand?
independent ED       →  does a second, separately written implementation agree?
   both pass         →  proceed to Stage 1
   disagreement      →  triage table below, before touching the Julia
   ED not buildable  →  a recorded limitation, not a failure
```

---

## Why two checks and not one

The independent diagonalisation is written from the spec, from scratch, without looking at
`hamiltonian.jl`. That is what makes it worth doing: a misreading of the problem (a factor on the
wrong term, a bond counted twice) rarely happens the same way twice, so two independent readings
disagree and you find it.

**What it cannot catch is a convention error**, and this is the part that is usually stated
wrongly. If the spec is written in Pauli operators and you read it as spin operators, you will make
that same substitution in both implementations, because it is not a misreading: it is a
translation you performed correctly and consistently against the wrong dictionary. The two codes
agree to twelve digits and both describe a model with couplings off by factors of two and four.

That is why Stage 0a insists on at least one anchor whose value depends on the operator
normalisation. A polarised limit does it: with the field written in Pauli operators the energy per
site approaches one value, and in spin operators half of it. The anchor is the only check in the
system that sees the dictionary.

---

## Choosing the backend

Pick by local Hilbert space dimension, not by habit.

**Spin-½ sites: XDiag.** Patterns below. The full space at `N ≤ 16` is at
most 65536 states, which Lanczos handles instantly. Larger rings, roughly `N = 20-24`, remain
reachable with sparse Lanczos and symmetry sectors when level spectroscopy (`transitions` E3) or a
degeneracy count (`phase-id`) needs them. The bound of 16 is the comfortable full-space size, not
a ceiling.

**Anything else (`S = 1`, `S = 3/2`, mixed-spin chains): build the matrix yourself.** Assemble `H`
as a sparse matrix from Kronecker products of the local operators, and hand it to a Lanczos
routine. It is short, it has no library-compatibility questions, and it makes the accessible `N`
explicit: the space is the product of the local dimensions, so `S = 1` reaches `N ≈ 10` where
spin-½ reaches 16.

The point of stating both is that validation should not quietly disappear for the models where it
matters most. A spin-1 chain is *more* likely to have a coding error than a spin-½ one, not less,
and the version of this skill that only covered spin-½ let those runs proceed unchecked.

---

## Making the comparison correctly

Four things have to match, and each has produced a false alarm.

**Boundary conditions.** Whatever Stage 0a recorded. Textbook examples often use periodic
boundaries while the DMRG survey runs open ones. On an open chain the bonds run `1 … N-1` with no
wrap-around term. A boundary mismatch on a perfectly correct Hamiltonian gives a clean
disagreement, and it is the most frequent cause of one.

**Normalisation.** Diagonalisation routines return the total energy. Compare per site against per
site.

**The sector.** The diagonalisation searches the whole space and returns the global ground state.
If the DMRG point is confined to one sector, the two are answering different questions, and the
disagreement is real but says nothing about the Hamiltonian. Either run the DMRG point without the
constraint, or confirm the sector you fixed is the one holding the global ground state. Stage 0a
recorded the policy. Carry it here.

**The tolerance.** Set it against the truncation error the DMRG point actually achieved rather than
a fixed number. At the small sizes used here DMRG is essentially exact, so agreement should be far
below any threshold you would name, and if it is not, that is information, not something to
accommodate. **A threshold is not renegotiable after seeing the result.** If the numbers miss it,
the answer is to find out why, not to observe that the miss is small.

---

## When they disagree

A disagreement is not one thing, and the four common causes are cheap to separate. Work down this
list before touching the Hamiltonian.

| What you see | What it is | What to do |
|---|---|---|
| The discrepancy shrinks when you raise the bond dimension or add sweeps | The DMRG point is not converged | Converge it and re-compare. Not a correctness problem |
| The code and an **anchor** differ by a simple rational: 2, 4, ½, ¼ | An operator convention | Fix the mapping in Stage 0a. Both codings are internally fine. This row is reachable only from the anchor comparison: by the argument above, a convention error cannot make the two independent codings disagree |
| It vanishes when both sides use the same boundary conditions | Boundary handling | Fix whichever side departed from the spec |
| It vanishes in the full space, or in a different charge sector | Sector policy | Fix the sector, not the Hamiltonian |
| None of the above, and it survives | The two codes implement different models | **Stop** |

The last row is a genuine hard stop and stopping is correct: past it, every number you produce
belongs to a Hamiltonian nobody has identified. Stopping is not going quiet: record the diagnosis
in `plan.md` and the note, mark the validation status in `phase_diagram.json`, and finish with that
as the result. "We could not verify that the implemented Hamiltonian is the one in the spec" is an
honest and useful outcome. A confident wrong phase diagram is not.

**"Cannot validate" is a different thing from "validation failed."** If no diagonalisation is
reachable (the local dimension is too large, or the model has no small instance), that is not
evidence of a bug and must not stop the run. The anchors carry the load alone, the limitation goes
in the note, and the study proceeds.

---

## After the gate: what else diagonalisation is good for

The check costs seconds and is usually run once and forgotten. At the sizes involved it also gives,
essentially free:

- **the exact gap**, which settles arguments the same-sector DMRG splitting cannot
- **the low-lying spectrum**, so you can count the near-degenerate states a candidate ordered phase
  predicts. Stage 3 asks for that count and this is the cheapest place to get it. Do it on a
  **periodic** ring: an order that enlarges the unit cell (a dimer pattern, a period-`n` plateau
  structure) has its degenerate partners at distinct momenta (`k = 0` and `π` for period two) with
  a splitting that shrinks exponentially with the ring, whereas an open chain selects one pattern
  and lifts the partner by an O(1) amount, so the count is invisible there. Resolving the levels by
  momentum and the other quantum numbers also corroborates the ordering wavevector, and it is the
  input `transitions` E3 needs for level spectroscopy
- **a pre-survey of the whole parameter box at small `N`**, before any DMRG is spent: the sector
  of the ground state at every point, level crossings, fidelity between neighbouring points.
  `observables` describes it, with the one rule that matters, which is that the sketch steers and
  never labels
- **exact correlators**, which validate the *observables* rather than only the energy. An
  observable coded wrongly is as damaging as a Hamiltonian coded wrongly and nothing else in the
  workflow checks it.

Its limits are equally worth knowing. Small systems are badly misleading about anything with a long
correlation length: a transition of infinite order will not show up at all, and a level crossing
at these sizes can be pure finite-size accident. Use it to settle discrete questions and to steer
where compute goes. Do not use it as evidence for a phase.

---

## XDiag specifics

**Name the file `scripts/ed_<something>.jl`.** The `ed_` prefix is how the harness recognises a
diagonalisation script. Without it you will not be pointed at this skill when you need it.

**Never import XDiag alongside ITensors.** Both export `OpSum` and `Op`, so a process holding both
fails on ambiguous names. The diagonalisation script is standalone and runs in a fresh process. The
persistent Julia session already has ITensors loaded and cannot be used for it.

```julia
block = Spinhalf(N)
ops = OpSum()
for i in 1:N-1                       # open chain: bonds 1 … N-1, no wrap
    ops += "J" * Op("SdotS", [i, i+1])
end
ops["J"] = 1.0                       # couplings are named constants, bound after the fact
e0 = eigval0(ops, block)             # total ground-state energy, Float64
```

Sites are 1-indexed, and couplings can be named constants: `"J" * Op(...)`, then
`ops["J"] = value`. `Op("SdotS", [i, j])` with the sites as a vector is the call form the package's
own tests use.

For the ground state: `eigval0(ops, block)` returns the energy alone, `eig0` the energy and the
state, and `eigs_lanczos(ops, block; neigvals = k)` the lowest `k` for a gap or a degeneracy count.
Keyword arguments `precision`, `max_iterations` and `random_seed` are available. `set_verbosity(0)`
silences the iteration log. Those four, along with `Spinhalf` and `OpSum`, are in the pinned mirror
at `third_party/XDiag.jl`.

**Operator names are a different matter, and you have to check them rather than trust a list.** The
Julia package is a wrapper around a compiled library, so the names are defined on the other side of
that boundary and grepping the mirror neither confirms nor refutes one. `lookup_doc` will not
settle it either. The cheapest check is two sites: bind the name you want on a spin-½ pair with unit
coupling and confirm a total energy of `−0.75`. If you intend to combine several names, the same
test tells you whether they add up or double-count, which matters because some libraries expose both
a combined exchange operator and its parts.

**Use the full `Spinhalf(N)` block, without fixing the magnetisation.** It returns the global
ground state, so it cannot land in the wrong sector, which is the whole point of using it as a
reference. The speed-up from fixing the sector is not needed at these sizes.

**Build the operator sum inside a function.** A bare top-level loop hits Julia's soft-scope rule and
fails with an ambiguity error about globals.

**Verify before you trust it.** A wrong reference gives a false pass, which hides a real bug, or a
false failure, which sends you to audit correct code, so its own correctness is load-bearing. In a
scratch run, first reproduce something you can check by hand: two spin-½ sites with an isotropic
coupling of unit strength give a total energy of `−0.75`, which is the singlet and is worth
recording because it is also the two-site test for every operator name you use.

**Then check the backend against your own Hamiltonian, not against a chain from a textbook.** Build
`H` at `N = 4` as a dense matrix from Kronecker products of your local operators (a few lines,
independent of any library) and diagonalise it directly. That comparison covers whatever spin
length, geometry and interaction range you actually have, which a list of reference numbers for the
isotropic spin-½ chain does not.

Say total or per site every time you quote any of these. Half of a two-site total is the per-site
value of the same state, so a factor of two between two people quoting the same anchor is ambiguous
rather than wrong. A factor of *four* on a two-site bond, or a wrong sign, is not: those point at
the operator convention.

Look up any signature you are unsure of against the local source rather than recalling it.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. preferred anchors, house tolerances, a local ED helper -->
