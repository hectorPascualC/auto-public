import { DurableObject } from "cloudflare:workers";
import { processScheduled, runScheduledController, scheduledErrorCode } from "./core.mjs";

export class SlotCoordinator extends DurableObject {
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
      console.error(JSON.stringify({
        controller: "v2", status: "ERROR", component: "slot_coordinator",
        phase, error: scheduledErrorCode(error)
      }));
      throw error;
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
