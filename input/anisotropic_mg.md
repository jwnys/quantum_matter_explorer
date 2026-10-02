# Anisotropic Frustrated Spin-1/2 Chain

## Hamiltonian

$$
H = \sum_{j=1}^{L} \sum_{\mu \in \{x,y,z\}} J^{\mu}
        \left( S^{\mu}_{j} S^{\mu}_{j+1}  +  \tfrac{1}{2} S^{\mu}_{j} S^{\mu}_{j+2} \right)
$$

where:

- $S^{x}_j, S^{y}_j, S^{z}_j$ are spin-1/2 operators on site $j$ (so $S^\mu = \sigma^\mu / 2$)
- each spin component $\mu$ carries its own coupling strength $J^{\mu}$
- the next-nearest-neighbour coupling is fixed at exactly half the nearest-neighbour coupling,
  for every component independently
- periodic boundary conditions, even chain length $L$

A positive $J^{\mu}$ is antiferromagnetic in that component and a negative $J^{\mu}$ is
ferromagnetic in that component.

## Parameter ranges to explore

Fix $J^{x} = 1$ throughout, and explore the plane

- $J^{y} \in [-1, 1]$
- $J^{z} \in [-1, 1]$

## Notes

Treat as unknown. Discover the phases and the boundaries between them from scratch using
DMRG. The isotropic line $J^{x} = J^{y} = J^{z}$ is a useful orientation point, but the behaviour
away from it is the object of the study.

Think carefully about which diagnostics distinguish the candidate orders here. The anisotropy
breaks the SU(2) symmetry of the isotropic chain, so a single rotationally-invariant correlator
may not be sufficient to characterise every region of this plane.
