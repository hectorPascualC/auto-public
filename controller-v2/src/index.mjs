import { DurableObject } from "cloudflare:workers";
import { processScheduled, runScheduledController } from "./core.mjs";

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
    return runScheduledController({scheduledTime: controller.scheduledTime, env});
  },
  async fetch() {
    return new Response("Not found", {status: 404});
  }
};
