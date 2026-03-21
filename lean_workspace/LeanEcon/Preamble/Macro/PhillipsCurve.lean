import Mathlib

/-- New Keynesian Phillips Curve (NKPC).
    Current inflation equals discounted expected future inflation plus
    the slope coefficient times the output gap: π = β * π_next + κ * x. -/
noncomputable def nkpc (β π_next κ x : ℝ) : ℝ :=
  β * π_next + κ * x

/-- The NKPC identity: inflation equals its NKPC-predicted value. -/
theorem phillips_curve_identity
    (π β π_next κ x : ℝ)
    (h : π = β * π_next + κ * x) :
    π = nkpc β π_next κ x := h
