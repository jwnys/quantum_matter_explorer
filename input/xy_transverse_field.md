# Anisotropic XY Chain in a Transverse Field

## Hamiltonian

$$
H = -\sum_{i=1}^{L-1} \left( \frac{1+\gamma}{2} X_i X_{i+1} + \frac{1-\gamma}{2} Y_i Y_{i+1} \right) - h \sum_{i=1}^{L} Z_i
$$

where:
- $X_i, Y_i, Z_i$ are the Pauli operators on site $i$ (spin-1/2)
- $\gamma$ is the anisotropy parameter ($\gamma = 1$ is the transverse-field Ising limit; $\gamma = 0$ is the isotropic XX limit)
- $h$ is the transverse field along $z$
- the nearest-neighbour exchange scale is set to 1

## Parameter ranges to explore

- $\gamma \in [-1, 1]$
- $h \in [0, 2]$

## Notes

This is a standard model, but treat it as unknown: discover all phases and the
boundaries between them from scratch using DMRG. Think about which diagnostics most
sharply reveal each boundary.
