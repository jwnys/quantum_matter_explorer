# Transverse-Field ANNNI Chain (competing Ising interactions)

## Hamiltonian

$$
H = -\sum_{i=1}^{L-1} X_i X_{i+1}  +  \kappa \sum_{i=1}^{L-2} X_i X_{i+2}  -  h \sum_{i=1}^{L} Z_i
$$

where:
- $X_i, Z_i$ are the Pauli operators on site $i$ (spin-1/2)
- the nearest-neighbour coupling scale is set to 1
- $\kappa \geq 0$ is the competing (frustrating) next-nearest-neighbour coupling
- $h$ is the transverse field along $z$

## Parameter ranges to explore

- $\kappa \in [0, 1]$
- $h \in [0, 2]$

## Notes

Treat as unknown. Discover all phases and the boundaries between them from
scratch using DMRG. Think about which diagnostics most sharply reveal each boundary.
