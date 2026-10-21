# V2 — Phase 1: baseline, isolation and security audit

Date: 2026-10-21. Scope: public GitHub repository `hectorPascualC/auto-public`.

## Evidence and root cause
- Current monitor workflow `.github/workflows/auto-places-docents.yml`: 18 scheduled UTC candidates, on main; GitHub scheduler is independent of the extraction scripts.
- 2026-10-21 08:35 and 08:47 Madrid: no corresponding run in workflow ID 382439148 during the initial audit window. **Absence is not proof of permanent loss:** delayed scheduled events may arrive later.
- 2026-10-20 runs 39495027854 and 39488923384: event=schedule, conclusion=success, actual fetch step SKIPPED; schedule string in logs was respectively `30 17 * * 1-5` and `30 16 * * 1-5`, with delays 198 and 215 minutes from advertised UTC cron. Never classify GitHub conclusion alone as successful scan.
- 2026-10-20 runs 39438471397, 39437562301: `stale_or_early_schedule` and no actual fetch.
- Last verified 12/12 PASS, run 39489739506, event=push: **does not** prove schedule activation.
- `slot-ledger.json` absent on main; legacy `README.md` schedule obsolete.
- ChatGPT AUTO - PUBLIC rescue at 09:05 was prevented by an external write-tool authorization guard. Cloudflare controller must not depend on ChatGPT writes.

## Security review: FAIL PENDING MITIGATION
- Public `state/latest.json` currently includes many verbatim `text_excerpt` fields, including official RESULTS.
- Automated pattern checks found email-like strings and DNI/NIF labels in excerpts (pattern matches **not verified instances of private personal information**). Minimize public text in V2; do not publish tokens, names of applicants, candidate details or raw RESULTAT text. Do not copy sensitive excerpts into tests, logs, Worker output or PR.
- Never use a personal GitHub token in git. Cloudflare secret `GITHUB_TOKEN` requires a fine-grained token restricted to this repository and Actions:write only. Prefer GitHub App installation credentials where feasible.
- Historical public git data cannot be made private by removing a file in a later commit; history remediation is a separate controlled incident response, not a blind rewrite.

## Decisions and phase gates
- Keep production main untouched until new controller is independently deployed and verified.
- Build V2 on branch `architecture-v2`; PR-based offline CI. Production scan remains current on main until cutover.
- Controller = Cloudflare Worker Cron (UTC candidates, Europe/Madrid DST in code); backup = separate decision after reading GitHub run state + PASS ledger; executor = GitHub workflow_dispatch; reporter = existing single ChatGPT automation, read-only.
- GitHub's native schedule is not the production triggering source in V2. Legacy runs stay active until controller has genuinely launched verified runs.
- Phase 1 PASS only for baseline identification and branch isolation. Security is explicitly BLOCKED until sanitation is validated.

## Verification criteria
1. The V2 branch points at the captured main SHA, without writing to main.
2. Root cause is reproduced with real run IDs/logs.
3. No credentials or user-specific application data appear in V2 sources.
4. Production activation is withheld until a running external controller and end-to-end receipt are verified.
