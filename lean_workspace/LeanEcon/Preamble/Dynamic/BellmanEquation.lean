import Mathlib

/- Bellman equation template for deterministic dynamic programming:
   `V(k) = max_{k'} { u(f(k) - k') + β * V(k') }`.

After substituting a candidate policy or Euler equation, the resulting claim is
usually formalized as an algebraic identity or inequality. -/
