# V2 cutover checklist (owner Cloudflare access required)

The assistant cannot use or create private Cloudflare access credentials from GitHub. These steps require an authenticated Cloudflare session. **Never paste a token into ChatGPT.**

## 0. Preconditions
- Confirm `architecture-v2` PR CI is green and every security finding reviewed.
- Confirm branch diff is only intended code/docs and does not introduce applicant text.
- Preserve a rollback pointer to current `main` SHA. Keep legacy GitHub crons while staging.
- Verify GitHub workflow `auto-places-docents.yml` supports inputs `slot_local` and `trigger_attempt` on default branch before enabling Worker dispatch.

## 1. Set up Cloudflare
- In your Cloudflare account, create a Worker on the correct account. Cloudflare Durable Objects must be enabled; check pricing/quota.
- Install Node.js 22+ and Wrangler CLI.
- From repository root: `npx --yes wrangler@4.139.0 deploy --config controller-v2/wrangler.toml --dry-run`.
- Authenticate privately with `npx --yes wrangler@4.139.0 login` and deploy the **disabled** Worker:
  `npx --yes wrangler@4.139.0 deploy --config controller-v2/wrangler.toml`.
- Create a fine-grained GitHub token restricted to `hectorPascualC/auto-public`: Actions (read/write), Contents (read), Metadata (read); avoid classic token, broader repo access, passwords, or admin scope.
- Enter token only via secure Wrangler secret prompt: `npx --yes wrangler@4.139.0 secret put GITHUB_TOKEN --config controller-v2/wrangler.toml`.
- Confirm Scheduled Trigger entries and Durable Object binding in Cloudflare dashboard, without exposing token.
- Verify Cloudflare has recorded dry/disabled cron invocations at actual Madrid slots and that there are no accidental `workflow_dispatch` GitHub runs.

## 2. Enable only after disabled-mode proof
- Merge only after security release review. Github `workflow_dispatch` new inputs require the workflow file in the default branch.
- Change `DISPATCH_ENABLED` to `true` in Wrangler's private deployment config and redeploy. Keep the branch configuration synchronized, and avoid committing tokens.
- Observe `AUTO V2 YYYY-MM-DDTHH:00 / primary` in GitHub Actions (event must be `workflow_dispatch`), and inspect `Fetch official sources` + final audit + state persistence.
- Require a matching `auto-places-docents/state/slot-ledger.json` PASS entry whose run_id/timestamps equal health and consumer.
- Validate conditional backup in controlled failure and absent-primary scenarios, plus no duplicate when primary is queued/running/finished PASS.
- Observe at least 3 consecutive nominal slots and reports from the existing ChatGPT task. Distinguish notification preferences from task execution.

## 3. Turn off the legacy plan only when proven
- Remove native `schedule` candidates from `.github/workflows/auto-places-docents.yml` and retire obsolete ChatGPT commit-based rescue after external controller is live and monitored.
- Keep only one GitHub executor; do not run dual writers into state on a long-term basis.
- Rollback: set `DISPATCH_ENABLED=false` on Worker; restore previous audited GitHub workflow if needed. Never force-push, delete history, or expose token.

## Monitoring and acceptance
Pass only when Cloudflare scheduled event -> GitHub workflow_dispatch -> actual 12/12 scan -> audit PASS -> GitHub exact-slot ledger -> ChatGPT scheduled feedback, all independently timestamped.
A local unit test, green PR CI, Cloudflare `--dry-run` or successful git `push` is NOT production end-to-end proof.

## Alternative for a mobile-only setup (GitHub Actions)

This PR also includes `.github/workflows/deploy-controller-v2.yml`, **manual-only**, with modes:
- `dry-run`: bundle without credentials and without deployment.
- `deploy-disabled`: deploy Worker with DISPATCH_ENABLED=false and inject its GitHub token.
- `deploy-enabled`: same, then explicitly activate controller. It requires typing `ENABLE_V2_NOW` into the workflow input.

After merging this reviewed workflow to `main`, set exactly these protected GitHub Actions secrets (never publish their values):
- `CLOUDFLARE_API_TOKEN`: account token permitting Workers script/deployment administration.
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare account identifier.
- `V2_GITHUB_DISPATCH_TOKEN`: fine-grained token for only this GitHub repository, Actions:write and Contents:read.

Then use Actions -> **AUTO PUBLIC V2 - deploy independent controller** -> Run workflow. Begin with `dry-run`, then `deploy-disabled`. Check both before `deploy-enabled`. GitHub's GITHUB_TOKEN cannot serve as the Worker's permanent dispatch credential: it expires.
