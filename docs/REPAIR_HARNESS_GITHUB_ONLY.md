# AUTO-PUBLIC: repair harness (GitHub-only)

## Scope and security contract

This is an **incremental, deterministic** self-repair layer built around the existing
GitHub Actions monitor and the existing ChatGPT SRE automation. It makes **no API model
calls**, deploys nothing, and does not introduce another scheduler.

The audit treats a successful/green GitHub workflow as insufficient evidence:
the latest **due Madrid weekday slot** must have an exact validated slot-ledger
receipt, matching authoritative 12/12 source state, and an actual monitor run
whose fetch, EDUBCN validation, finalization, and persistence steps succeeded.
Nominal hours remain **08:00 / 11:00 / 13:00 / 17:00**; a slot becomes due after
its 45-minute acceptance window. Weekends/early mornings look back to the
last due weekday slot instead of applying an arbitrary 24-hour freshness rule.

## Repair decision policy

| Observation | Engine decision | Automatic writes |
| --- | --- | --- |
| Missing due slot | `existing_rescue_only` | None; the existing ChatGPT rescue task alone can use its CAS/dedup window |
| Source audit/12 sources failed | `investigate_sources` | None; never patch from unverified source data |
| Consumer snapshot inconsistent, canonical sources verified | `rebuild_consumer` | **Only a local candidate** reconstructed from canonical files, atomically and checked |
| GitHub run steps failed / cannot be verified | `investigate_scan` | None; no blind retry |
| Unknown defect | `investigate` | None; requires verified root cause and a new tested rule |
| Audited PASS | `none` | None |

The candidate repair is bounded to **one idempotent attempt**. It cannot
change repository branches, permissions, secrets, nominal slots, remote state,
or source-of-truth files. When an audit job fails, the harness runs as a
subsequent step using the local checkout and uploads `repair-incident.json`.
**The successful local rebuild is not production recovery.** A reviewed
GitHub PR and independent post-merge scan are still required to persist a
nontrivial change. No automatic merge is configured.

## Verification

Run locally or on PR:

```bash
python3 -m unittest discover -s auto-places-docents/tests -p 'test_sre_repair_harness.py' -v
python3 -m py_compile auto-places-docents/sre_audit_v2.py auto-places-docents/repair_harness.py
```

For an operational check, inspect the SRE audit run's `sre-audit-report.json`
and `repair-incident.json` artifacts. A green SRE job is only a full PASS
when every check is PASS; missing real GitHub evidence must not be reported as
PASS. A future safe repair rule must provide a reproduction, an allowlisted
mutation, an automated postcondition, a rollback plan, and a regression test.

## Remaining work

The connected ChatGPT automation can already read GitHub, do bounded rescue,
diagnose failures, and propose patches. Its continued operation and available
tool permissions are separate from this runner. **Autonomous novel-code repair
with persistent learning is not implemented by this PR**; it requires a
verified patch/PR/test loop. Retain existing safeguards and avoid claiming
continuous autonomous reasoning without an authorized execution mechanism.
