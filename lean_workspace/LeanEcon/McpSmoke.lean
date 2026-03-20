import Mathlib

/-- Dedicated MCP smoke-test fixture with an intentionally failing tactic. -/
theorem mcp_smoke_fixture (x y : Nat) : x = y := by
  rfl
