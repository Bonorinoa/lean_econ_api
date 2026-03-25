# Contributing to LeanEcon

Thanks for helping improve LeanEcon. This repository is intentionally small and
single-repo, so contributions work best when they stay focused and easy to
review.

## Ground Rules

- keep Apache-2.0 and `NOTICE` intact
- do not add a CLA, DCO, or heavyweight governance process
- prefer small, scoped changes with clear validation
- do not introduce capabilities that the API does not actually have
- keep `README.md` as the landing page, `docs/API.md` as the operational guide,
  and `docs/TECHNICAL_WHITEPAPER.md` as the architecture/trust-model doc

## Local Validation

Run the baseline checks before opening a change:

```bash
ruff check src tests scripts
pytest -m "not live and not slow" --tb=short -q
```

For API-related changes, also run:

```bash
./leanEconAPI_venv/bin/python -m pytest tests/test_api_smoke.py -q
```

For Lean/MCP-related changes, also run:

```bash
./leanEconAPI_venv/bin/python src/mcp_smoke_test.py
```

If you touch benchmark or evaluation code, add the relevant smoke or targeted
tests from `tests/` and `scripts/`.

## What Makes a Good Change

- the behavior change is described clearly in the PR or commit message
- the doc update matches the code paths in `src/`
- the validation commands are listed in the final summary
- the change is easy to roll back if something surprises us

## Documentation Changes

- keep public claims conservative
- avoid overstating pricing, status, or availability
- keep `/api/v1/lean_compile` positioned as optional compile/debug, not the
  default workflow
- keep `/api/v1/formalize` as the claim-shaping step
- keep `/api/v1/verify` as the async proving path

## Security And Hardening Changes

There is no separate monitored security inbox or disclosure SLA for the API
right now. If you find a security issue, hardening gap, or unsafe public claim,
open a PR with a focused fix and a minimal reproduction when you can.

If the issue touches public positioning, make sure the wording stays
conservative and does not imply stable pricing, quota, or a stably free
Leanstral tier.
