import { DurableObject } from "cloudflare:workers";
import { processScheduled, runScheduledController, scheduledErrorCode, scheduledErrorKind } from "./core.mjs";

export class SlotCoordinator extends DurableObject {
  // Read-only, internal-only probe used to distinguish a failed DO RPC call
  // from a failed DO binding. The public Worker fetch handler stays 404.
  async fetch(request) {
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname === "/__probe")
      return new Response(null, {status: 204});
    // Only the bound Worker can reach this DO fetch handler. The public
    // Worker fetch endpoint remains 404. Exactly one POST per cron attempt.
    if (request.method === "POST" && pathname === "/__run-slot") {
      let phase = "parse_request";
      try {
        let event;
        try {
          event = await request.json();
        } catch {
          return new Response(null, {status: 400});
        }
        phase = "validate_request";
        if (!event || typeof event !== "object" ||
            !Number.isFinite(event.scheduledTime) ||
            Object.keys(event).length !== 1)
          return new Response(null, {status: 400});
        phase = "invoke_slot";
        const result = await this.runSlot({scheduledTime: event.scheduledTime});
        phase = "encode_response";
        return Response.json(result);
      } catch (error) {
        // A thrown exception in the HTTP handler otherwise crosses the DO
        // boundary as a bare TypeError. Return only fixed safe metadata.
        // The Worker rethrows it, preserving failed-cron semantics.
        return Response.json({
          status: "ERROR", component: "slot_coordinator", phase,
          error: scheduledErrorCode(error), error_kind: scheduledErrorKind(error)
        });
      }
    }
    return new Response("Not found", {status: 404});
  }

  async runSlot(event) {
    let phase = "block_concurrency";
    try {
      // Serialize each slot, while recording ONLY safe phase identifiers.
      return await this.ctx.blockConcurrencyWhile(async () =>
        processScheduled({
          scheduledTime: event.scheduledTime,
          nowMs: Date.now(),
          env: this.env,
          state: this.ctx.storage,
          onPhase: next => { phase = next; }
        })
      );
    } catch (error) {
      // DO RPC can mask an inner error as 'unexpected_exception' in the
      // outer Worker. Emit a safe, phase-specific DO log before rethrowing.
      // Never print exception.message, stack, GitHub response or credentials.
      // Return a small allowlisted RPC value: Worker tails often omit
      // Durable Object console frames, so rethrowing here erased the phase.
      // The outer Worker rethrows after logging, preserving failed-cron status.
      return {
        status: "ERROR", component: "slot_coordinator", phase,
        error: scheduledErrorCode(error), error_kind: scheduledErrorKind(error)
      };
    }
  }
}

export default {
  async scheduled(controller, env) {
    return runScheduledController({scheduledTime: controller.scheduledTime, env});
  },
  async fetch() {
    return new Response("Not found", {status: 404});
  }
};
