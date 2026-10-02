---
name: transitions
description: Read this in Stage 2, when the survey has shown where something changes and you need to pin the boundary down, and again before claiming any transition. Covers what qualifies as a boundary at all, how to locate one from finite systems, how to tell first-order from continuous from infinite-order, and how to trace a boundary through a parameter space with more than one axis.
---

# Boundaries: what counts as one, where it is, and what kind

The survey has told you roughly where things change. This stage turns that into boundaries with
positions and characters. Two things go wrong here and they pull in opposite directions: boundaries
get invented where there is only a crossover, and real boundaries get missed because no obvious
diagnostic peaks at them.

Both come from the same gap, so start there.

## Map

```
first: what changes across it?  →  nothing nameable → a crossover, not a boundary
                                   something changes character → a boundary, even if nothing peaks

E1  first order?      step in ∂E/∂λ · level crossing (needs quantum numbers) · jump sharpening
E2  continuous?       curves for different sizes crossing in a dimensionless ratio
E3  infinite order?   no clean crossing, and the estimate drifting logarithmically
E4  several parameters?  anchor the edges, cut across, then trace the boundary
```

---

## What qualifies as a boundary

**A boundary is defined by naming what changes across it.** In the thermodynamic limit something
must change non-analytically, and if you cannot say what, you have a crossover: a smooth
interpolation that looks sharp at the sizes you ran.

The half that gets missed is the converse. If any qualitative character changes, that *is* a
boundary, **even when the energy, the gap and the ordering wavevector are all perfectly smooth
across it.** Things that count as a change of character:

- the dominant correlation channel switches from one operator to another
- the ordering axis rotates while the wavevector stays put
- the ground-state degeneracy changes
- the ordering wavevector jumps, or unlocks from a commensurate value
- a gap opens or closes.

The reason to spell this out is that the usual boundary-hunting tools (a peak in the energy
curvature, a peak in a susceptibility) look for a singularity in a *scalar*, and several of those
changes barely produce one. Where two regions differ only in which axis orders, the energy is
usually a smooth, featureless curve through the transition at the resolution a survey runs at: not
because there is nothing there, but because the non-analyticity is weak enough to hide. If the two
sides happen to be related by an exact symmetry of `H` the energies are equal outright, and there
is nothing at all to find in that channel.

So the transition is real and the standard scan will not point at it. You find it by noticing that
the answer to "what is ordered here" differs on the two sides, which is why Stage 3 and this stage
have to talk to each other rather than running in sequence. Refining the energy curvature in a
narrow window is still worth trying (it is cheap and it sometimes works) but a flat curve there
is not evidence against a boundary.

Two cheap diagnostics need no order parameter at all and belong in every survey for exactly this
reason. The ground-state fidelity `|⟨ψ(λ)|ψ(λ+δλ)⟩|` between neighbouring scan points, at fixed
size and fixed step, dips where the state changes character and falls to zero at a level crossing.
The mid-chain entanglement entropy peaks, or kinks, at a transition. Both flag a boundary
rather than locate it, and both share a blind spot: an infinite-order transition shows no clean
feature in either, which is E3's business. One reading to make first: with quantum numbers on, two
states in different sectors have zero overlap by construction, so a vanishing fidelity is a question
about the conserved charge before it is a question about a transition.

So: before locating anything, write down what you claim changes. That sentence is the boundary. The
rest of this file is about pinning its position and character.

---

## Which kind of transition

Settle this before spending effort on the position, because the methods differ and a first-order
transition located by continuous-transition machinery gives a confidently wrong answer.

### E1. First order

**The definition, and the cheapest test.** In the thermodynamic limit a first-order transition is a
discontinuity in the first derivative of the ground-state energy with respect to the parameter. A
continuous one has that derivative continuous and a singularity in the second. So take a fine sweep
of `E₀(λ)` through the window and look at `∂E₀/∂λ`. The sweep is data you were collecting anyway. One special case reads especially cleanly: where one
side of the window is an exact-eigenstate region with exactly constant energy (`model-setup` A5),
the flat branch has zero slope, and the character of the exit is read directly from how the slope
departs on the other side.

What you see at finite size depends on whether the ground state changes symmetry sector, and it is
worth knowing which case you are in before reading the plot. If it does, the two branches genuinely
cross and the derivative has a real step, at any size: that is the same event as the level crossing
below, and it is unambiguous. If it does not, the levels repel instead, `E₀(λ)` is smooth, and the
discontinuity only emerges as the system grows. There you need the size trend: does the feature
sharpen, or does it keep the same width?

**A level crossing, if you can label the states.** Two levels exchanging places is the clearest
picture of a first-order transition, but two states with the *same* quantum numbers do not cross in
a one-parameter family. They approach and repel. So the crossing is visible only between states
carrying different quantum numbers, which means you need the symmetry labels to see it at all.
Small-system diagonalisation is where to look, and where the location should then be read off.

**A jump that sharpens.** An observable steps, and the step gets *steeper* with system size rather
than staying the same width. A step of fixed width is a crossover.

**Bistability under an up-and-down sweep: corroboration only.** Sweep the parameter up, starting
each point from the previous converged state, then sweep down the same way. Getting different
answers over an interval is suggestive and costs almost nothing.

It is also the weakest of the four, for a specific reason: an optimisation started
from a nearby state tends to stay near it, so this test reports bistability in models with no
transition at all, and it can slide straight through a real one if the warm start happens to track
the ground state. Before it counts for anything, show that the bistability survives a larger bond
dimension. Compare `itensor-dmrg`, which treats two initial states disagreeing as a sign the
calculation is stuck: the same observation, and that is the reading to prefer until the
`χ`-convergence check says otherwise.

Report the location from the derivative or the crossing, not from the midpoint of a jump.

### E2. Continuous

Locate it with a **dimensionless ratio**: a quantity built so the system-size dependence cancels
at the critical point. The correlation ratio is the usual choice:

$$ R(L) = 1 - S(q^* + \delta q)/S(q^*), \qquad \delta q = 2\pi/L $$

**The offset must shrink like `1/L`, and this is the part that is easy to get wrong.** What makes
`R` invariant under a change of scale is that `δq · L` is the same at every size. `2π/L` is the
usual choice and any fixed multiple of it does equally well. Pick a *fixed* offset instead (the
obvious thing to do once you have `S(q)` on a fine grid) and the quantity is no longer
dimensionless in the scaling sense, so the curves for different sizes drift instead of crossing.
If your curves drift, check this before anything else.

That is not a conflict with the dense grid `observables` asks for. The two serve different jobs. The
dense grid is how you *find* `q*`, because a coarse one cannot resolve an incommensurate peak. The
ratio then wants `S` evaluated at two specific places, `q*` and `q* + 2π/L`. If `q*` is
incommensurate and moves with size, use each size's own fitted `q*(L)`. If it drifts strongly,
treat the crossing as approximate and corroborate it with a second estimator.

A Binder cumulant does the same job and is sometimes the better choice, but it is not the drop-in
alternative it looks like: it needs the fourth moment of the order parameter, which is a four-point
correlator summed over every quadruple of sites, and neither `observables` nor `itensor-dmrg`
computes one. Budget for it before promising it.

The point is that curves for different sizes **cross** at the transition rather than peaking near
it. A crossing is a far better estimator than a peak, because a peak position drifts with size
while a crossing converges, and because you get an error estimate for free from how the crossings
for successive pairs of sizes move.

Energy curvature and fidelity susceptibility both peak near a continuous transition and are worth
plotting, but treat them as corroboration. Curvature computed by finite differences on a coarse
scan is noisy and its peak is biased by the grid spacing.

**Preconditions.** The correlation ratio needs a structure factor, so it needs translation
invariance and a well-defined `q*`. Without those, use the crossing of any other dimensionless
combination you can build: a ratio of correlations at two distances that scale the same way at
criticality will do.

### E3. Infinite order

The trigger is a property of the data, not a family of models: **the crossings do not converge, and
the apparent location drifts logarithmically with size.** Transitions of this kind have an
exponentially diverging correlation length, so at accessible sizes every method that assumes a
power law reports a location that keeps moving.

When you see that, say so. Report the transition as infinite-order with the drift shown, and if you
need a number, take it from the crossing of energy levels chosen by symmetry rather than from
extrapolating the drifting estimates: the level-based method converges far faster at these sizes.
What you must not do is fit the drifting values to a constant and quote the result. That number is
an artefact of where you stopped.

**Level spectroscopy, concretely.** Diagonalise periodic rings of several even sizes and resolve
the low excitations by their quantum numbers (total spin or spin-flip parity, momentum, inversion
parity). Each of the two competing phases has a characteristic lowest excitation. For a dimerisation
transition out of a gapless phase it is the lowest singlet against the lowest triplet, both at
`k = π`. The parameter value at which those two levels cross, `λ*(N)`, is the finite-size estimate.
For transitions of this kind it moves as `1/N²` (confirm that the sequence is consistent with that
form before extrapolating), and it converges at sizes where every correlation-ratio crossing is
still drifting. `ed-validation` has the backend. Rings of 20–24 sites are reachable with sparse
Lanczos when 16 is not enough.

---

## Pinning the position

Whatever the character, the recipe is the same shape: measure the estimator across several sizes in
a window around the boundary, and extrapolate.

Two practical notes. First, refine the window rather than the whole range: the survey already told
you where to look, and points far from the boundary contribute nothing to its position. Second,
each point in the window is a natural place to start from the neighbouring converged state rather
than from scratch, which is both faster and better conditioned. That serialises the scan, so it
belongs here rather than in the survey, where independent points run in parallel.

Report the position with an uncertainty that reflects the spread of the crossings across size
pairs, not the spacing of your parameter grid.

**No boundary on a single diagnostic.** Independent estimators should converge to the same place.
Where they disagree, that disagreement is information: most often that the region between them is
not a single boundary but two, or that one of the estimators is being contaminated by a nearby
feature. Report it rather than averaging it away.

---

## E4. More than one parameter

With a two-dimensional parameter space the boundaries are curves rather than points, and covering
the area on a fine grid is not affordable if the boundaries need any precision at all.

Work in this order:

1. **Anchor the edges.** The faces of the box often contain limits that are exactly solvable or
   trivially known from Stage 0a. Those points cost nothing and fix where the boundaries meet the
   edges.
2. **Take a few cuts.** Straight lines through the box, chosen to cross the structure you expect:
   including at least one along each axis and one diagonal. Each cut is a one-dimensional problem
   and everything above applies to it unchanged.
3. **Trace, rather than scan.** Once you have two points on the same boundary, predict where the
   next one lies, bracket it, and bisect on whichever estimator you chose. Following a curve costs
   effort proportional to its length, while filling the area costs effort proportional to the area.
4. **Fill the interior last, coarsely,** only to the density the final figure needs.

A cut that reveals no boundary is still information and goes in the note. A region the cuts never
crossed is unexplored and must be marked as such rather than coloured in by interpolation.

---

## Local rules

Additions specific to this group go here. They survive regeneration of the rest of the file.

<!-- e.g. preferred estimators, house conventions for reporting uncertainties -->
