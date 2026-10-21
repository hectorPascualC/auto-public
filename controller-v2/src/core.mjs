// AUTO-PUBLIC V2: independent scheduler decision engine. No browser/session data.
const ZONE = "Europe/Madrid";
const HOURS = new Set([8, 10, 13, 15]);
const SLOT_HOURS = new Set([9, 11, 14, 16]);
const ONE_MINUTE = 60_000;

function madridParts(ms) {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", weekday: "short", hourCycle: "h23"
  });
  return Object.fromEntries(fmt.formatToParts(new Date(ms))
    .filter(p => p.type !== "literal").map(p => [p.type, p.value]));
}

export function scheduledSlot(scheduledTime) {
  if (!Number.isFinite(scheduledTime)) return null;
  const p = madridParts(scheduledTime);
  const localHour = Number(p.hour), minute = Number(p.minute);
  if (!["Mon", "Tue", "Wed", "Thu", "Fri"].includes(p.weekday) ||
      !HOURS.has(localHour) || ![35, 47].includes(minute) ||
      !SLOT_HOURS.has(localHour + 1)) return null;
  const date = p.year + "-" + p.month + "-" + p.day;
  return {
    key: date + "T" + String(localHour + 1).padStart(2, "0") + ":00",
    attempt: minute === 35 ? "primary" : "backup",
    scheduledTime
  };
}

export function isValidReceipt(slot, ledger, health, consumer) {
  const receipt = ledger?.slots?.[slot];
  if (!receipt || receipt.status !== "PASS" || !receipt.snapshot_run_id ||
      !health || !consumer || health.audit_status !== "PASS" ||
      health.fresh !== 12 || health.total !== 12 ||
      health.presence_authoritative !== 12 || health.audit_errors !== 0 ||
      health.partial !== 0 || health.cache_obsoleta !== 0 ||
      health.generated_at !== consumer.generated_at ||
      receipt.generated_at !== health.generated_at ||
      receipt.audit_at !== health.audit_at ||
      receipt.snapshot_run_id !== consumer.run_id) return false;
  // Slot is nominal Madrid-local time; parse the receipt's actual offsets
  // and compare using locally formatted timestamps, not a fake UTC date.
  const start = Date.parse(receipt.generated_at), audit = Date.parse(receipt.audit_at);
  if (!Number.isFinite(start) || !Number.isFinite(audit) || audit < start ||
      audit - start > 35 * ONE_MINUTE) return false;
  const parts = madridParts(start);
  const wall = Date.UTC(+parts.year, +parts.month - 1, +parts.day,
    +parts.hour, +parts.minute);
  const nominal = Date.UTC(+slot.slice(0, 4), +slot.slice(5, 7) - 1,
    +slot.slice(8, 10), +slot.slice(11, 13), 0);
  // Accept snapshots started 25 min before to 45 min after nominal,
  // but never use the previous 2-hour monitoring slot.
  return wall >= nominal - 25 * ONE_MINUTE &&
         wall < nominal + 45 * ONE_MINUTE;
}

function isMatchingRun(run, slot) {
  return run?.workflow_id === 382439148 &&
    run.event === "workflow_dispatch" &&
    typeof run.display_title === "string" &&
    run.display_title.startsWith("AUTO V2 " + slot + " / ");
}

export function decideAttempt({slot, attempt, ledger, health, consumer, runs}) {
  if (isValidReceipt(slot, ledger, health, consumer)) return "valid_receipt";
  const matching = (Array.isArray(runs) ? runs : []).filter(r => isMatchingRun(r, slot));
  if (matching.some(r => r.display_title.endsWith(" / backup")))
    return "backup_already_dispatched";
  // Important: if the primary is STILL running at :47, enqueue one standby
  // backup. GitHub serializes runs, so its gate will skip the backup after
  // a PASS primary but will scan if the primary later fails. If we merely
  // skipped here, a primary failing after :47 would never be retried.
  if (attempt === "primary" && matching.length > 0)
    return "slot_already_dispatched";
  return "dispatch";
}

export async function processScheduled({scheduledTime, nowMs = Date.now(), env, fetcher = fetch, state}) {
  const slot = scheduledSlot(scheduledTime);
  if (!slot) return {status: "IGNORED", reason: "not_a_nominal_slot"};
  if (!Number.isFinite(nowMs) ||
      nowMs < scheduledTime - 2 * ONE_MINUTE ||
      nowMs > scheduledTime + 17 * ONE_MINUTE)
    return {status: "STALE", slot: slot.key, attempt: slot.attempt};

  // A Durable Object provides serialized per-slot access. Persist the attempt
  // before allowing a later invocation for the same slot to proceed.
  if (await state.get(slot.attempt) === "sent") {
    return {status: "SKIPPED", slot: slot.key, reason: "already_sent"};
  }
  if (env.DISPATCH_ENABLED !== "true")
    return {status: "DISABLED", slot: slot.key, attempt: slot.attempt};

  const repo = env.GITHUB_REPO || "hectorPascualC/auto-public";
  if (repo !== "hectorPascualC/auto-public" ||
      !env.GITHUB_TOKEN || typeof env.GITHUB_TOKEN !== "string")
    throw new Error("controller_configuration_invalid");
  const base = "https://api.github.com/repos/" + repo;
  const headers = {
    Accept: "application/vnd.github+json",
    Authorization: "Bearer " + env.GITHUB_TOKEN,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "auto-public-v2-controller"
  };
  async function github(path, init = {}, allow404 = false) {
    const response = await fetcher(base + path, {
      method: init.method || "GET",
      headers: {...headers, ...(init.body ? {"Content-Type": "application/json"} : {})},
      body: init.body ? JSON.stringify(init.body) : undefined,
      redirect: "error"
    });
    if (allow404 && response.status === 404) return null;
    if (!response.ok) throw new Error("github_http_" + response.status);
    if (response.status === 204) return null;
    return response.json();
  }
  async function jsonFile(path) {
    const result = await github("/contents/" + path + "?ref=main", {}, true);
    if (!result) return null;
    if (result.content && result.encoding === "base64") {
      const binary = atob(result.content.replace(/\s/g, ""));
      const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
      return JSON.parse(new TextDecoder().decode(bytes));
    }
    // An explicit API schema change is a failure, not an empty PASS.
    throw new Error("github_contents_unexpected_schema");
  }
  const [ledger, health, consumer, runResponse] = await Promise.all([
    jsonFile("auto-places-docents/state/slot-ledger.json"),
    jsonFile("auto-places-docents/state/health.json"),
    jsonFile("auto-places-docents/state/consumer.json"),
    github("/actions/runs?event=workflow_dispatch&per_page=100")
  ]);
  if (!Array.isArray(runResponse?.workflow_runs))
    throw new Error("github_runs_unexpected_schema");
  const verdict = decideAttempt({
    slot: slot.key, attempt: slot.attempt, ledger, health, consumer,
    runs: runResponse.workflow_runs
  });
  if (verdict !== "dispatch")
    return {status: "SKIPPED", slot: slot.key, attempt: slot.attempt, reason: verdict};

  // The workflow must already exist on main and accept both V2 inputs.
  await github("/actions/workflows/auto-places-docents.yml/dispatches", {
    method: "POST",
    body: {
      ref: "main",
      inputs: {run_monitor: "true", force_run: "false",
        slot_local: slot.key, trigger_attempt: slot.attempt}
    }
  });
  await state.put(slot.attempt, "sent");
  return {status: "DISPATCHED", slot: slot.key, attempt: slot.attempt};
}
