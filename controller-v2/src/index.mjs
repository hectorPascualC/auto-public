import { DurableObject } from "cloudflare:workers";
import { processScheduled, runScheduledController, scheduledErrorCode, scheduledErrorKind } from "./core.mjs";

export class SlotCoordinator extends DurableObject {
  // Read-only, internal-only probe used to distinguish a failed DO RPC call
  // from a failed DO binding. The public Worker fetch handler stays 404.
  async fetch(request) {
    if (request.method === "GET" &&
        new URL(request.url).pathname === "/__probe") {
      return new Response(null, {status: 204});
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
