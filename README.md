# AUTO-PUBLIC — docent DC 507 / 627 / F57 / F87

This PUBLIC GitHub repository contains a direct-source monitor for all 11 SSTT + EDUBCN.

## Production status as of 21 October 2026

The current main branch retains the **legacy GitHub Actions schedules**. They are NOT a proven reliable scheduler: previous `schedule` events were delayed for hours or skipped by the schedule gate, although ordinary `push` scans could pass 12/12.

**Architecture V2 is isolated on `architecture-v2`, in draft PR #1; it is not yet deployed.**
[Review the migration](https://github.com/hectorPascualC/auto-public/pull/1).

## V2 responsibilities

1. External Cloudflare Worker scheduler/controller with a per-slot Durable Object, UTC-to-Europe/Madrid conversion and two attempts at :35 / :47 before nominal 09:00, 11:00, 14:00, 16:00.
2. A single GitHub Actions executor via `workflow_dispatch` with `slot_local` and `trigger_attempt`, conditional standby backup, full-source audit and exact-slot PASS ledger.
3. The existing `AUTO - PUBLIC` ChatGPT automation reads the audited result around HH:05 and separately consults private candidate records. It is a reporter, **not a mandatory GitHub trigger**.

Production cutover is NOT complete without Cloudflare access, a restricted GitHub dispatch credential, real Worker-triggered actions and at least three consecutive verified nominal slots.

## Code, tests and safe deployment

- [Architecture](docs/architecture-v2/ARCHITECTURE.md)
- [Baseline root-cause and security audit](docs/architecture-v2/PHASE1_AUDIT.md)
- [Phase 2/3 regression and integration audit](docs/architecture-v2/PHASE2_3_AUDIT.md)
- [Cloudflare deployment and cutover runbook](docs/architecture-v2/DEPLOYMENT_RUNBOOK.md)
- Controller code: `controller-v2/`
- GitHub CI: `.github/workflows/auto-places-docents-ci.yml`
- Manual, fail-closed Cloudflare deployment: `.github/workflows/deploy-controller-v2.yml`

V2 PR CI tests Python schedule gates, Node controller decisions, Wrangler bundling and an isolated 12-source extraction. The CI never commits live official-source text.

## Privacy boundary

This repository is public. Legacy `state/latest.json` / compressed `history` contain source document excerpts; **do not add private applicant data, correspondence or secrets**. V2 strips verbatim excerpts before new public history is committed. Historical public data require a separate controlled privacy review and are not retroactively erased by that code change.

Secrets belong only in Cloudflare Worker secrets / protected GitHub Actions secrets. NEVER paste tokens into code, issues, PRs or ChatGPT.
