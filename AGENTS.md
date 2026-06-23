# BNCT TPS Agent Repository Guidance

## Scope

This repository contains an engineering assistant, not a medical device and not
an autonomous treatment-planning system.

## Safety invariants

- Never add a tool that approves a treatment plan, changes a prescription, or
  writes patient or DICOM data without a separately reviewed safety design.
- Keep clinical actions blocked in deterministic policy code. A prompt is not
  an authorization boundary.
- Use synthetic or de-identified fixtures only.
- Preserve a human approval step for file writes and process execution.
- Keep audit records free of direct identifiers and secrets.

## Development

- Run `python -m unittest discover -s tests -v` before completing changes.
- Prefer standard-library dependencies unless a dependency removes substantial
  complexity.
- Add tests for path containment, approval policy, PHI rejection, and any new
  TPS adapter behavior.

