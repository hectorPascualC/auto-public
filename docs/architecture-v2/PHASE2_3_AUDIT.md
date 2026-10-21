# Phase 2 / 3 — isolated controller and executor integration audit

## Control
- Branch: architecture-v2 (production main unchanged).
- GitHub PR: https://github.com/hectorPascualC/auto-public/pull/1 (draft; no merge).
- Cloudflare Worker source: `controller-v2/src/core.mjs`, `src/index.mjs`, `wrangler.toml`.
- Durable Object lock: per exact Madrid nominal slot (not global, no overlapping controller decisions).
- Secrets: NO credentials in source; Worker `GITHUB_TOKEN` runtime secret only; dispatch intentionally disabled in `wrangler.toml`.
- GitHub executor: optional `slot_local` / `trigger_attempt` workflow_dispatch inputs; V2 named workflow runs; Python gate checks date, hour, timezone and PASS dedup; `slot_ledger.py` stores audited PASS only.

## Test evidence
- CI run 39568278730: controller unit tests PASS.
- CI run 39568576348: Python/Node external-input integration regressions PASS.
- CI run 39568866575: future-snapshot sanitization regression tests PASS.
- CI run 39569109518: 10 Node tests PASS, 16 Python tests PASS, but Wrangler bundling FAILED because Node.js 20 was below the supported Node 22 minimum. **Phase gate remained closed.**
- CI run 39569287500: Python 16/16 PASS, Node 10/10 PASS, Wrangler 4.139.0 `deploy --dry-run` PASS on Node 22. Bundle reported 8.02 KiB uncompressed. No external credential was used or deployment executed.

## Security verification and limits
- At least 172 stored source document excerpts plus 55 inline hit snippets were present in the unmodified latest.json; they might include candidate-identifying statements. V2 sanitizer strips them **before** gzip history and git publication, after extraction/audit have used them.
- A structural simulation on the last public snapshot reduced the raw JSON structure from approximately 1.35 MB to approximately 0.32 MB without deleting IDs, sources, timestamps or active placements. This is a static projection; no real V2 persisted run yet.
- Historical public git commits and compressed histories still contain original data. NO history rewrite performed. Privacy remediation remains **PENDING**.
- No Cloudflare token, account or deployment binding available through this conversation; `DISPATCH_ENABLED=false`. Therefore live scheduling, actual dispatch, production backup and ChatGPT delivery remain **NOT VERIFIED**.

## Phase gates
- PASS: new isolated controller code, DST slots, backup states, idempotency tests, GitHub typed inputs, PASS receipt checking, Python offline tests, Worker bundling (dry run), initial future-state sanitization.
- BLOCKED: live Cloudflare Worker deployment and secret, GitHub main integration, live end-to-end schedule tests, historical public data remediation, reporter's on-time visibility.
- DO NOT MERGE the PR as a production cutover or declare V2 operational before the blocked items are resolved.
