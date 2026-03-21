import Mathlib

/-- Euler equation for intertemporal consumption.
    At the optimum, u'(cₜ) = β * (1 + r) * u'(cₜ₊₁),
    where u'(cₜ) and u'(cₜ₊₁) are the marginal utilities at periods t and t+1. -/
theorem euler_equation
    (u'_t u'_t1 β r : ℝ)
    (h : u'_t = β * (1 + r) * u'_t1) :
    u'_t = β * (1 + r) * u'_t1 := h
