# AUTO - PUBLIC — architecture V2

## Ownership boundary
1. **Scheduler:** Cloudflare Worker, UTC cron at (previous hour) :35 / :47. A DST-aware calendar converts the scheduled instant to nominal 09:00, 11:00, 14:00, 16:00 Europe/Madrid.
2. **Controller:** durable lock/idempotency per slot; GitHub API check of latest 12/12 PASS + persistent slot ledger, and real workflow_dispatch runs. Backup runs only if first did not run or failed. If first is still running, controller must NOT dispatch a duplicate.
3. **Executor:** existing GitHub Actions scan, externally invoked by `workflow_dispatch` with strict `slot_local` and `trigger_attempt` inputs. Full extraction, audit, compact state persist, and a PASS ledger entry are required.
4. **Reporter:** single ChatGPT AUTO - PUBLIC task at HH:05, consuming public GitHub state, candidatures from private Library. Reporter MUST NOT be required to trigger GitHub, avoiding feedback/trigger mutual dependency.

## Delivery contract
- `PASS`: checkout from triggering commit, all 12 sources, authoritative presence, audit=PASS and zero errors, persistent main SHA and same-slot receipt.
- `RUNNING`: GitHub run queued/in-progress for same slot. No duplicate dispatch.
- `FAILED`: GitHub run completed failure/cancelled/timed_out; backup may dispatch if no earlier backup and no same-slot valid receipt.
- `MISSING`: no same-slot receipt or matching GitHub run. Backup dispatch once at :47.
- `STALE`: next slot already passed by controller or target window expired. Never present stale results as a fresh scan.
- Green CI and push runs alone do not count as successful production V2 activation.

## Cutover requirements
- Worker deployed in owner's Cloudflare account with a dedicated secret and Durable Object namespace.
- Workflow input support merged into main, CI green, no security regression.
- Dry-run external schedules observed, followed by real controlled workflow_dispatch runs.
- At least three consecutive nominal slots demonstrate correct first/backup/reporter sequence.
- Only then retire native schedule expressions and obsolete ChatGPT write-based rescue.
- Do not declare rollout completed while any of these requirements are open.
