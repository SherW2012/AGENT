# BNCT TPS Agent Memory

This file plays the same role as a project-level CLAUDE.md: it tells the local
agent how to work inside this repository.

## Working Style

- Prefer small, reviewable changes.
- Use existing project patterns before adding new abstractions.
- Run focused tests after code changes.
- Do not make clinical judgments or treatment decisions.
- Treat de-identified BNCT plan snapshots as engineering data only.

## Domain Guardrails

- Never request, store, or expose direct patient identifiers.
- Clinical approval, prescription changes, patient data write-back, and beam
  delivery remain outside this agent.
