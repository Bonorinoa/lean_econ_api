# Verification Report: crra_fail
Status: FAIL
Return code: 1

## Errors
  LeanEcon/Proof.lean:10:4: unexpected identifier; expected command

## lake stdout
```
✖ [8027/8029] Building LeanEcon.Proof (27s)
warning: LeanEcon/Proof.lean:7:39: unused variable `hγ1`

Note: This linter can be disabled with `set_option linter.unusedVariables false`
error: LeanEcon/Proof.lean:10:4: unexpected identifier; expected command
warning: LeanEcon/Proof.lean:10:8: '' starts on column 8, but all commands should start at the beginning of the line.

Note: This linter can be disabled with `set_option linter.style.whitespace false`
error: Lean exited with code 1
Some required targets logged failures:
- LeanEcon.Proof
```
## lake stderr
```
error: build failed
```
