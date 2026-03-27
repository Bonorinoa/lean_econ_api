# LeanEcon MCP-First Prover Brief

Status: archived historical note

This document is retained for background context only. It reflects an earlier
MCP-heavy proving brief and is no longer the canonical description of the
public API or current architecture.

For the current workflow and endpoint contract, use:

- [`README.md`](../README.md)
- [`docs/API.md`](./API.md)
- [`docs/leanstral_architecture.html`](./leanstral_architecture.html)

## Historical Context

LeanEcon still uses Leanstral and `lean-lsp-mcp` inside the proving loop, and
final truth still comes from isolated `lake env lean` checks. The project has
since grown into a broader API with clear separation between optional
classification, formalization, direct compile/debug checks, and async verify
jobs.

Do not treat this file as the source of truth for endpoint behavior, benchmark
numbers, or release guidance.
