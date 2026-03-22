# Verification Report: Even Numbers as `2n`

Status: PASS
Run date: 2026-03-19

## Summary

This curated example formalizes the standard parity witness claim for natural
numbers: if `m` is even, then there exists `n` with `m = 2 * n`.

## Notes

- Proof shape: `rcases hm with ⟨k, hk⟩; use k; simpa [two_mul] using hk`
- Domain: general mathematics / parity over naturals
