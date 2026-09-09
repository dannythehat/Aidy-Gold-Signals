const FED_RSS_INTERVAL_SECONDS = 120;
const MARKET_INTERVAL_SECONDS = 300;

export function shouldEnqueueCaptureTick(scheduledTime) {
  const milliseconds = Number(scheduledTime);
  if (!Number.isFinite(milliseconds)) {
    throw new TypeError("AIDY scheduler requires a finite scheduledTime.");
  }
  // Cloudflare guarantees the scheduled minute, but ScheduledController.scheduledTime
  // must not be treated as though it is always second-aligned. Decide the recorder
  // cadence from the nominal UTC minute so delayed Cron delivery cannot silently
  // suppress every Queue message.
  const minute = new Date(milliseconds).getUTCMinutes();
  return (
    minute % (FED_RSS_INTERVAL_SECONDS / 60) === 0 ||
    minute % (MARKET_INTERVAL_SECONDS / 60) === 0
  );
}

export default {
  async scheduled(controller, env) {
    // The Cloudflare Cron fires every minute; Queue operations are emitted only
    // on the union of the 2-minute FED cadence and 5-minute market cadence.
    if (!shouldEnqueueCaptureTick(controller.scheduledTime)) {
      return;
    }
    await env.AIDY_CAPTURE_QUEUE.send({
      scheduledTime: controller.scheduledTime,
      cron: controller.cron,
    });
  },
};
