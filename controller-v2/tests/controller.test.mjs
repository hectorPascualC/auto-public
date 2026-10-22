import test from "node:test";
import {readFileSync} from "node:fs";
import assert from "node:assert/strict";
import {scheduledSlot, isValidReceipt, decideAttempt, processScheduled, runScheduledController} from "../src/core.mjs";

const SU = Date.parse("2026-10-20T06:35:00Z");
const BU = Date.parse("2026-10-20T06:47:00Z");
const DAY = "2026-10-20T09:00";

function evidence() {
  const generated_at = "2026-10-20T08:36:00+02:00";
  const audit_at = "2026-10-20T08:43:00+02:00";
  return {
    health: {generated_at, audit_at, fresh:12, total:12, partial:0,
      cache_obsoleta:0, presence_authoritative:12, audit_status:"PASS", audit_errors:0},
    consumer: {generated_at, run_id:"run-safe-1"},
    ledger: {slots: {[DAY]: {status:"PASS", generated_at, audit_at,
      snapshot_run_id:"run-safe-1"}}}
  };
}

function mockGithub({ledger = null, health = null, consumer = null, runs = [], error = null} = {}) {
  const calls = [];
  async function fetcher(url, options) {
    calls.push({url, method: options?.method || "GET", body: options?.body});
    if (error) return new Response("upstream error", {status:error});
    const name = String(url).includes("slot-ledger.json") ? "ledger" :
      String(url).includes("health.json") ? "health" :
      String(url).includes("consumer.json") ? "consumer" : "";
    if (name) {
      const val = {ledger, health, consumer}[name];
      if (!val) return new Response("", {status:404});
      return new Response(JSON.stringify({
        encoding:"base64", content:btoa(JSON.stringify(val))
      }), {status:200});
    }
    if (String(url).includes("/actions/runs"))
      return new Response(JSON.stringify({workflow_runs:runs}), {status:200});
    if (String(url).includes("/dispatches") && options.method === "POST")
      return new Response(null, {status:204});
    throw new Error("unexpected_url");
  }
  const stateData = new Map();
  const state = {
    get: async key => stateData.get(key),
    put: async (key, value) => stateData.set(key, value)
  };
  const env = {
    GITHUB_REPO:"hectorPascualC/auto-public",
    GITHUB_TOKEN:"fake-secret-never-logged",
    DISPATCH_ENABLED:"true"
  };
  return {calls, fetcher, state, env};
}
function run(slot, options) {
  return {workflow_id:382439148, event:"workflow_dispatch",
    display_title:"AUTO V2 " + slot + " / " + options.attempt,
    status:options.status, conclusion:options.conclusion || null};
}

test("CET/CEST, nominal hours and exact backup identities", () => {
  assert.deepEqual(scheduledSlot(SU), {key:DAY, attempt:"primary", scheduledTime:SU});
  assert.deepEqual(scheduledSlot(BU), {key:DAY, attempt:"backup", scheduledTime:BU});
  assert.equal(scheduledSlot(Date.parse("2026-10-26T07:35:00Z")).key,
    "2026-10-26T09:00");
  for (const [instant, slot] of [
    ["2026-10-20T08:35:00Z","2026-10-20T11:00"],
    ["2026-10-20T11:35:00Z","2026-10-20T14:00"],
    ["2026-10-20T13:35:00Z","2026-10-20T16:00"],
    ["2026-10-26T09:35:00Z","2026-10-26T11:00"],
    ["2026-10-26T12:35:00Z","2026-10-26T14:00"],
    ["2026-10-26T14:35:00Z","2026-10-26T16:00"]
  ]) assert.equal(scheduledSlot(Date.parse(instant)).key, slot, instant);
  assert.equal(scheduledSlot(Date.parse("2026-10-20T07:35:00Z")), null);
  assert.equal(scheduledSlot(Date.parse("2026-10-24T06:35:00Z")), null);
  assert.equal(scheduledSlot(Number.NaN), null);
});

test("evidence is strict and must match same slot", () => {
  const e = evidence();
  assert.equal(isValidReceipt(DAY,e.ledger,e.health,e.consumer),true);
  assert.equal(isValidReceipt("2026-10-20T11:00",e.ledger,e.health,e.consumer),false);
  assert.equal(isValidReceipt(DAY,e.ledger,{...e.health,audit_errors:1},e.consumer),false);
  assert.equal(isValidReceipt(DAY,e.ledger,{...e.health,generated_at:"2026-10-20T07:55:00+02:00"},e.consumer),false);
  assert.equal(isValidReceipt(DAY,e.ledger,e.health,{...e.consumer,run_id:"other"}),false);
  assert.equal(isValidReceipt(DAY,null,e.health,e.consumer),false);
});

test("primary dispatches once with typed inputs and no duplicate", async () => {
  const m=mockGithub();
  const x={scheduledTime:SU,nowMs:SU,env:m.env,fetcher:m.fetcher,state:m.state};
  assert.equal((await processScheduled(x)).status,"DISPATCHED");
  const post=m.calls.filter(x => x.method==="POST");
  assert.equal(post.length,1);
  const request=JSON.parse(post[0].body);
  assert.equal(request.ref,"main");
  assert.equal(request.inputs.slot_local,DAY);
  assert.equal(request.inputs.trigger_attempt,"primary");
  assert.equal(request.inputs.force_run,"false");
  assert.equal((await processScheduled(x)).reason,"already_sent");
  assert.equal(m.calls.filter(x => x.method==="POST").length,1);
});

test("backup fires when missing or primary failed", async () => {
  for (const runs of [[], [run(DAY,{attempt:"primary",status:"completed",
                                  conclusion:"failure"})]]) {
    const m=mockGithub({runs});
    const r=await processScheduled({scheduledTime:BU,nowMs:BU,env:m.env,
      fetcher:m.fetcher,state:m.state});
    assert.equal(r.status,"DISPATCHED");
    assert.equal(r.attempt,"backup");
  }
});

test("running primary queues exactly one conditional standby backup", async () => {
  for (const status of ["queued","waiting","in_progress"]) {
    const m=mockGithub({runs:[run(DAY,{attempt:"primary",status})]});
    const args={scheduledTime:BU,nowMs:BU,env:m.env,
      fetcher:m.fetcher,state:m.state};
    const r=await processScheduled(args);
    assert.equal(r.status,"DISPATCHED");
    assert.equal(r.attempt,"backup");
    assert.equal(m.calls.filter(x=>x.method==="POST").length,1);
    assert.equal((await processScheduled(args)).reason,"already_sent");
    assert.equal(m.calls.filter(x=>x.method==="POST").length,1);
  }
});

test("backup is omitted with a verified PASS receipt", async () => {
  const e=evidence(), m=mockGithub(e);
  const result=await processScheduled({scheduledTime:BU,nowMs:BU,env:m.env,
    fetcher:m.fetcher,state:m.state});
  assert.equal(result.reason,"valid_receipt");
  assert.equal(m.calls.some(x=>x.method==="POST"),false);
});

test("duplicate backup is not sent and success without receipt is retried", async () => {
  let m=mockGithub({runs:[run(DAY,{attempt:"backup",status:"completed",
                                   conclusion:"failure"})]});
  let r=await processScheduled({scheduledTime:BU,nowMs:BU,env:m.env,
    fetcher:m.fetcher,state:m.state});
  assert.equal(r.reason,"backup_already_dispatched");
  m=mockGithub({runs:[run(DAY,{attempt:"primary",status:"completed",
                               conclusion:"success"})]});
  r=await processScheduled({scheduledTime:BU,nowMs:BU,env:m.env,
    fetcher:m.fetcher,state:m.state});
  assert.equal(r.status,"DISPATCHED");
});

test("no public fallback on Github API error", async () => {
  const m=mockGithub({error:403});
  await assert.rejects(processScheduled({scheduledTime:SU,nowMs:SU,env:m.env,
    fetcher:m.fetcher,state:m.state}),/github_http_403/);
  assert.equal(m.calls.some(x=>x.method==="POST"),false);
});

test("scheduled event too late, disabled and invalid configuration fail closed", async () => {
  let m=mockGithub();
  let r=await processScheduled({scheduledTime:SU,nowMs:SU+18*60_000,
    env:m.env,fetcher:m.fetcher,state:m.state});
  assert.equal(r.status,"STALE");
  m=mockGithub();
  m.env.DISPATCH_ENABLED="false";
  r=await processScheduled({scheduledTime:SU,nowMs:SU,env:m.env,
    fetcher:m.fetcher,state:m.state});
  assert.equal(r.status,"DISABLED");
  m=mockGithub();
  delete m.env.GITHUB_TOKEN;
  await assert.rejects(processScheduled({scheduledTime:SU,nowMs:SU,
    env:m.env,fetcher:m.fetcher,state:m.state}),/controller_configuration_invalid/);
});

test("Cloudflare config and GitHub contract are statically aligned", () => {
  const toml=readFileSync(new URL("../wrangler.toml",import.meta.url),"utf8");
  assert.match(toml,/crons = \["35,47 6,7,8,9,11,12,13,14 \* \* 1-5"\]/);
  assert.match(toml,/DISPATCH_ENABLED = "false"/);
  assert.match(toml,/class_name = "SlotCoordinator"/);
  assert.match(toml,/new_sqlite_classes = \["SlotCoordinator"\]/);
  const worker=readFileSync(new URL("../src/index.mjs",import.meta.url),"utf8");
  assert.match(worker,/blockConcurrencyWhile/);
  assert.match(worker,/scheduled\(controller, env\)/);
});

test("14:47 Madrid is correctly ignored; 13:35 is the 14:00 primary", async () => {
  const ignored = Date.parse("2026-10-22T12:47:02.977Z");
  const primary = Date.parse("2026-10-22T11:35:02.977Z");
  assert.equal(scheduledSlot(ignored), null);
  assert.deepEqual(scheduledSlot(primary), {
    key: "2026-10-22T14:00", attempt: "primary", scheduledTime: primary
  });
  const logs = [];
  const result = await runScheduledController({
    scheduledTime: ignored, env: {},
    logger: {log: x => logs.push(JSON.parse(x)), error: () => assert.fail("unexpected error")}
  });
  assert.equal(result.status, "IGNORED");
  assert.equal(logs[0].reason, "not_a_nominal_slot");
});

test("a valid cron with missing DO binding reports a safe error before rethrow", async () => {
  const logs = [];
  const scheduledTime = Date.parse("2026-10-22T11:35:02Z");
  await assert.rejects(runScheduledController({
    scheduledTime, env: {GITHUB_TOKEN: "TOP_SECRET"},
    logger: {log: () => assert.fail("unexpected success"), error: x => logs.push(x)}
  }), /slot_coordinator_binding_invalid/);
  assert.deepEqual(JSON.parse(logs[0]), {
    controller: "v2", status: "ERROR", slot: "2026-10-22T14:00",
    attempt: "primary", phase: "resolve_coordinator",
    error: "slot_coordinator_binding_invalid"
  });
  assert.equal(logs[0].includes("TOP_SECRET"), false);
});

test("a valid cron calls the DO RPC and emits a structured result", async () => {
  const scheduledTime = Date.parse("2026-10-22T11:47:00Z");
  const seen = [], logs = [];
  const env = {SLOT_COORDINATOR: {
    idFromName: key => {seen.push(key); return {key};},
    get: id => ({runSlot: async event => {
      seen.push(id.key, event.scheduledTime);
      return {status:"DISPATCHED", slot:id.key, attempt:"backup"};
    }})
  }};
  const result = await runScheduledController({
    scheduledTime, env,
    logger: {log: x => logs.push(JSON.parse(x)), error: () => assert.fail("unexpected error")}
  });
  assert.deepEqual(seen, ["2026-10-22T14:00", "2026-10-22T14:00", scheduledTime]);
  assert.equal(result.status, "DISPATCHED");
  assert.equal(logs[0].status, "DISPATCHED");
});

test("RPC exceptions preserve known API codes and redact arbitrary errors", async () => {
  const scheduledTime = Date.parse("2026-10-22T11:35:00Z");
  for (const [reason, expected] of [
    ["github_http_403", "github_http_403"],
    ["unexpected sensitive token leaked", "unexpected_exception"]
  ]) {
    const logs = [];
    const env = {SLOT_COORDINATOR: {
      idFromName: key => key,
      get: () => ({runSlot: async () => {throw new Error(reason);}})
    }};
    await assert.rejects(runScheduledController({
      scheduledTime, env,
      logger: {log: () => assert.fail("unexpected success"), error: x => logs.push(JSON.parse(x))}
    }));
    assert.equal(logs[0].phase, "run_coordinator");
    assert.equal(logs[0].error, expected);
    assert.equal(JSON.stringify(logs).includes("sensitive token"), false);
  }
});
