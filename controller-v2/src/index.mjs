import { DurableObject } from "cloudflare:workers";
import { scheduledSlot, processScheduled } from "./core.mjs";

export class SlotCoordinator extends DurableObject {
  async runSlot(event) {
    // blockConcurrencyWhile serializes two deliveries/retries of this slot.
    return this.ctx.blockConcurrencyWhile(async () =>
      processScheduled({
        scheduledTime: event.scheduledTime,
        nowMs: Date.now(),
        env: this.env,
        state: this.ctx.storage
      })
    );
  }
}

export default {
  async scheduled(controller, env) {
    const slot = scheduledSlot(controller.scheduledTime);
    if (!slot) {
      console.log(JSON.stringify({controller: "v2", status: "IGNORED"}));
      return;
    }
    const id = env.SLOT_COORDINATOR.idFromName(slot.key);
    const stub = env.SLOT_COORDINATOR.get(id);
    try {
      const result = await stub.runSlot({
        scheduledTime: controller.scheduledTime
      });
      console.log(JSON.stringify({controller: "v2", ...result}));
    } catch (error) {
      // Error message is an internal code only; no token, headers, source data.
      console.error(JSON.stringify({
        controller: "v2", slot: slot.key,
        status: "ERROR", error: String(error.message || "unknown").slice(0, 100)
      }));
      throw error;
    }
  },
  async fetch() {
    return new Response("Not found", {status: 404});
  }
};
