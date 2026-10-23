# AUTO - PUBLIC V2 controller (Cloudflare Worker)

**Status:** deployed to Cloudflare; full scheduled Cron → GitHub → publication PASS still requires production evidence.
The original GitHub Actions native schedules remain available as fallbacks; they are not proof of Cloudflare runtime.

Responsibilities:
- **Critical: Cloudflare weekdays use 1=SUN, 2=MON, ..., 6=FRI, 7=SAT.** For Monday-Friday use `2-6` (NOT GitHub-style `1-5`). The previous Cloudflare cron accidentally excluded Fridays and included Sundays.
- UTC Cloudflare cron at :35 and :47. `Intl.DateTimeFormat(timeZone='Europe/Madrid')` chooses actual seasonal nominal slots 09/11/14/16.
- Durable Object `SlotCoordinator` serializes decisions per nominal slot; duplicate scheduled deliveries are deduplicated.
- Before any dispatch, read exact-slot GitHub PASS ledger, compact health/consumer and existing GitHub Actions runs.
- The backup at :47 dispatches only when there is no valid slot PASS receipt. If the primary is absent or failed, the backup scans. If the primary is queued/running, one **standby** backup is queued behind it in GitHub; the GitHub gate rechecks state after the primary completes, skipping a redundant scan on PASS and scanning if the primary later fails. No third retry.
- Controller invokes existing `auto-places-docents.yml` via `workflow_dispatch`, never touches applicant data, and has no public HTTP endpoint.
- GitHub is the sole extractor and persists the original scan and an exact-slot PASS ledger. The ChatGPT task only reports.

**Fail closed:** Disabled by default via `DISPATCH_ENABLED=false`; missing/invalid token, API 403/429/5xx, malformed receipts or a stale cron are not interpreted as PASS.

Testing: Node.js 22+; `node --test tests/*.test.mjs`.
Package check: `npx --yes wrangler@4.139.0 deploy --config wrangler.toml --dry-run`.

Deployment is documented at `docs/architecture-v2/DEPLOYMENT_RUNBOOK.md`. NEVER put a token in a committed file, PR, chat or log.
