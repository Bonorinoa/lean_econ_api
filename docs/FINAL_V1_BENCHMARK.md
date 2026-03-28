# LeanEcon v1 — Final Benchmark Report

**Date:** March 28, 2026
**Branch:** `codex-v2-proposal-hardening-20260326`
**Purpose:** Final stabilization benchmark before maintenance-only freeze

## Validation Gates

- ruff: PASS
- pytest: `253 passed, 13 deselected`
- lake build: PASS
- production smoke: PASS

## Benchmark Artifact Note

This report uses the latest completed on-disk artifacts in `benchmarks/reports/`
as of March 28, 2026. The tier-1 formalizer-only and selected tier-1 full
artifacts below were regenerated during this stabilization session after the
MCP-validation timeout path was corrected.

A post-rollback selected tier-1 full rerun completed during this stabilization
session and now supersedes the earlier 20260328T174122Z selected-full artifact.

## Formalizer-Only

| Tier | pass@1 | semantic ≥4 | Notes |
|------|--------|-------------|-------|
| tier0_smoke | 1.000 | 0.667 | Latest completed artifact: `benchmarks/reports/tier0_smoke_formalizer_only_20260325T063439Z.md` |
| tier1_core | 0.667 | 0.750 | Latest completed artifact: `benchmarks/reports/tier1_core_formalizer_only_20260328T174455Z.md` |
| tier2_frontier | 0.667 | 1.000 | Latest completed artifact: `benchmarks/reports/tier2_frontier_formalizer_only_20260325T065620Z.md` |

## Full Pipeline

| Tier | Lane | pass@1 | p50 (s) | p95 (s) | Notes |
|------|------|--------|---------|---------|-------|
| tier0 | raw_claim | 1.000 | 188.4 | 198.1 | Latest completed artifact: `benchmarks/reports/tier0_smoke_full_20260323T234951Z.md` |
| tier0 | theorem_stub | 1.000 | 22.8 | 161.6 | Latest completed artifact: `benchmarks/reports/tier0_smoke_full_20260323T234951Z.md` |
| tier0 | raw_lean | 1.000 | 16.1 | 149.9 | Latest completed artifact: `benchmarks/reports/tier0_smoke_full_20260323T234951Z.md` |

## Selected Tier-1 Full Slice

| Tier | Lane | pass@1 | p50 (s) | p95 (s) | Notes |
|------|------|--------|---------|---------|-------|
| tier1_core_selected | raw_claim | 0.000 | 211.6 | 272.0 | Latest completed artifact: `benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md` |
| tier1_core_selected | theorem_stub | 1.000 | 148.0 | 181.7 | Latest completed artifact: `benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md` |
| tier1_core_selected | raw_lean | 1.000 | 146.8 | 149.7 | Latest completed artifact: `benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md` |

## Performance Changes from This Sprint

| Change | Before | After | Delta |
|--------|--------|-------|-------|
| Formalizer prompt tightening (`StrictConcaveOn`, nat-power preference, unknown-identifier repair guard) | Tier 1 formalizer-only baseline: `pass@1 = 0.833`, semantic `>=4 = 1.000` from `tier1_core_formalizer_only_20260325T181104Z.md` | Latest completed rerun: `pass@1 = 0.667`, semantic `>=4 = 0.750` from `tier1_core_formalizer_only_20260328T174455Z.md` | `-0.166` pass@1, `-0.250` semantic |
| Prover instruction tuning after rolling back the stricter read-only/search budget clamp | Tier 1 selected full baseline: `raw_claim -> full API pass@1 = 0.333` from `tier1_core_selected_full_full_20260325T151134Z.md` | Latest completed post-rollback rerun: `raw_claim -> full API pass@1 = 0.000` from `tier1_core_selected_full_full_20260328T181026Z.md` | `-0.333` |
| Fast-path and curated-hint expansion (raw Lean lane) | Tier 1 selected full baseline: `raw_lean -> verify pass@1 = 1.000` from `tier1_core_selected_full_full_20260325T151134Z.md` | Latest completed post-rollback rerun: `raw_lean -> verify pass@1 = 1.000` from `tier1_core_selected_full_full_20260328T181026Z.md` | `0.000` |
