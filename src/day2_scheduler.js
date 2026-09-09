const FED_RSS_INTERVAL_SECONDS = 120;
const MARKET_INTERVAL_SECONDS = 300;

export function shouldEnqueueCaptureTick(scheduledTime) {
  const milliseconds = Number(scheduledTime);
  if (!Number.isFinite(milliseconds)) {
    throw new TypeError("AIDY scheduler requires a finite scheduledTime.");
  }
  // Retained as a deterministic cadence contract for rollback/testing. Production
  // capture now runs directly on the Python Worker Cron Trigger and does not use
  // Cloudflare Queues.
  const minute = new Date(milliseconds).getUTCMinutes();
  return (
    minute % (FED_RSS_INTERVAL_SECONDS / 60) === 0 ||
    minute % (MARKET_INTERVAL_SECONDS / 60) === 0
  );
}

export default {
  async scheduled(controller, env) {
    // Intentionally retired. The Python AIDY Worker owns the direct Cron Trigger.
    // Do not enqueue: stale Queue backlogs and Queue free-tier exhaustion must not
    // be able to stop Provider Context freshness again.
    void controller;
    void env;
  },
};
