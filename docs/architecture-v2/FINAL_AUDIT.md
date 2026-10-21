# V2 phase-gate audit — 2026-10-21

This is a release gate, NOT a claim that production migrated. Branch architecture-v2 is ahead of main; main unchanged.

| Phase | Evidence | Assessment |
|---|---|---|
| 1. Root cause + isolation | Real GitHub runs 39495027854, 39488923384, 39438471397 etc; isolated branch and PR #1 | PASS for root cause/branch isolation |
| 1b. Historic privacy | Main's public latest/history contain raw documentary excerpts; no history rewrite | OPEN RISK; requires controlled privacy decision |
| 2. External controller code | Cloudflare Worker with Europe/Madrid DST conversion, serialized Durable Objects, GitHub status/ledger, fail-closed errors | PASS in unit tests only |
| 2b. Worker packaging | GitHub CI 39569287500, Node 22, Wrangler 4.139.0 --dry-run | PASS: bundle builds |
| 3. GitHub external workflow contract | slot_local/trigger_attempt in workflow_dispatch, identifiable V2 run-name, Python gate and ledger same-slot checks | PASS in regression tests only |
| 3b. Real sources integration | GitHub CI 39570087470 and 39570370482 on pinned ubuntu-24.04; complete 12-source scan, EDUBCN, active snapshot, sanitizer and finalized gz history (no push) | PASS in ephemeral test environment |
| 3c. Standby backup | At :47, if primary still queued/running, queue one backup behind it; GitHub checks a PASS snapshot and suppresses unnecessary extraction. Node tests cover queued/running plus absent/failed primary | PASS in offline tests only |
| 4. Cloudflare production deployment | No authenticated Cloudflare connection, account ID or dedicated GitHub dispatch token available to the assistant | BLOCKED; not deployed |
| 4b. Security release | Sanitizer prevents future new raw excerpts, but legacy public git history remains; no destructive history rewrite | PARTIAL, privacy review needed |
| 5. Production cutover | No real V2 Worker-triggered workflow_dispatch observed, no 3 consecutive nominal slots, no verified real fallback and report delivery | BLOCKED |
| 6. Legacy retirement | Native scheduled crons and ChatGPT write-based rescue remain on main until true cutover | NOT STARTED intentionally |

## Real failure found during verification
- CI 39569109518: Wrangler required Node.js 22, not 20. Corrected and bundle passed CI 39569287500.
- CI 39569848490: Playwright Chromium 1.55 could not install on ubuntu26.04-x64. Pinned monitor and integration runner to ubuntu-24.04; 39570087470 then passed its real scan.

## Non-negotiable acceptance
1. No token or private applicant information in V2 code/PR.
2. A real Cloudflare scheduled event dispatches GitHub workflow (event=workflow_dispatch, not push or legacy schedule).
3. GitHub scans 12 sources, audit PASS, writes exact-slot ledger, and persists sanitized state.
4. Primary success suppresses a second actual scan; absent/failed/late-failed primary is recovered by conditional backup.
5. ChatGPT reports the exact same new photograph around HH:05, without acting as a GitHub scheduler.
6. Three consecutive slots meet those conditions before declaring production V2 operational.

## Current decision
**DO NOT MERGE OR ENABLE EXTERNAL DISPATCH AS PRODUCTION** without secret deployment, privacy review and live acceptance. Green CI is necessary but insufficient.
