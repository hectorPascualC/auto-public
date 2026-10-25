# GitHub-only parity audit — private working path to public (25 October 2026)

## Verified baseline (do not mistake GitHub SUCCESS for a scan)

- The private repository `hectorPascualC/private` executed a **real GitHub `schedule` scan** on 2026-10-02: run [36999739394](https://github.com/hectorPascualC/private/actions/runs/36999739394), with source fetch, dynamic EDUBCN revalidation, compact snapshot and safe persistence successful.
- That historical private workflow commit `ecc6c63ab7d60068236ef232c70073f113bf6d8d` scheduled `30 7,10,12,16 * * *` in `Europe/Madrid` as a **fallback**. Its documented primary scheduler was external, at minute `:20`. The current private workflow no longer contains this schedule. Do not confuse the historic workflow with the current one.
- Other private scheduled runs failed after source fetching (e.g. [37309544102](https://github.com/hectorPascualC/private/actions/runs/37309544102) and [37520429098](https://github.com/hectorPascualC/private/actions/runs/37520429098)), so history cannot justify a claim of 100% reliability.
- Public [40178034412](https://github.com/hectorPascualC/auto-public/actions/runs/40178034412) completed real scanning via `push` with fresh 12/12, authoritative 12/12, audit PASS. This confirms the public executor can work.
- The GitHub-only public monitor has native timezone-aware `schedule` entries for 08:00/11:00/13:00/17:00 with primary H-23, backup H-11, recovery H+13, late H+27. It records a PASS per nominal slot using `state/slot-ledger.json` and avoids duplicate scans.
- The read-only 30-minute schedule smoke test produced two real `schedule` deliveries [40201436178](https://github.com/hectorPascualC/auto-public/actions/runs/40201436178), [40218094773](https://github.com/hectorPascualC/auto-public/actions/runs/40218094773), but **did not demonstrate 30-minute regularity**. It was retired safely in PR #50.

## Safe equivalent of the private push execution path

Reuse the **existing single hourly ChatGPT SRE task**, scheduled on the half-hour, as a conditional GitHub-only recovery trigger. This is not a new GitHub cron or an additional monitor. It does not scan sources itself.

For each weekday slot 08:00, 11:00, 13:00, 17:00 (Madrid time), when the SRE task runs around HH:30:

1. Read the current GitHub default-branch HEAD, runs, jobs, health/audit/consumer, `slot-ledger.json` and the existing `external-trigger.txt`. Missing data is NOT proof of PASS.
2. If a *valid* PASS already belongs to the slot, or a qualifying monitor scan is queued/in progress, **do nothing**. Never dispatch while provenance remains ambiguous.
3. Only between HH:29 and HH:38, when the slot is demonstrably missing and no scan is queued/in progress, stage **one** commit modifying only `auto-places-docents/state/external-trigger.txt`. The marker must contain:
   `AUTO-PUBLIC scheduled-slot rescue\nslot_local=YYYY-MM-DDTHH:00:00±HH:MM\npublic_data_only=true\n`.
   Use the actual `Europe/Madrid` UTC offset; the commit must have a non-identifying GitHub noreply author/committer and pass a HEAD/commit/tree/diff comparison before publication. Publish using a branch-ref compare-and-swap/lease, never a forced update. Do not retry a successful marker.
4. The *existing* public workflow triggers on that `push`, checks the current ledger/freshness again under its existing concurrency group, and runs the scan at most once if still required. Verify the resulting run includes **actual** source fetch, EDUBCN revalidation, state persistence, fresh 12/12, audit PASS and matching slot ledger before claiming success.
5. If the gate sees a malformed scheduled rescue marker (wrong DST offset, missing public-data restriction, unsupported nominal hour), it must return `invalid_rescue_marker` and **not** reinterpret the marker as an unslotted scan. Ordinary legacy manual push markers are unchanged.
6. If the scheduled GitHub scan is missing but recovery prerequisites cannot be proven or tools lack access, report BLOCKED with evidence. Never synthesize a PASS or push a marker just to produce a green workflow.

## Non-goals and limitations

- No changes to production cron times, secrets, permissions, DNS, personal data, or fail-closed deduplication. No duplicate scans or additional ChatGPT automation.
- A GitHub scheduled event can be delayed or dropped; neither the historic private fallback cron nor this conditional rescue provides a guaranteed wall-clock SLA.
- The SRE task itself may be delayed. Recovery after HH:38 requires fresh revalidation and shall **not** blindly issue a late push.
- The first post-change weekday (Monday 2026-10-26) is the real acceptance test: check all four nominal slots from GitHub logs, not just workflow-level SUCCESS.
