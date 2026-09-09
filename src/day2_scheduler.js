const FED_RSS_INTERVAL_SECONDS = 120;
const MARKET_INTERVAL_SECONDS = 300;

export function shouldEnqueueCaptureTick(scheduledTime) {
  const milliseconds = Number(scheduledTime);
  if (!Number.isFinite(milliseconds)) {
    throw new TypeError("AIDY scheduler requires a finite scheduledTime.");
  }
  const seconds = Math.floor(milliseconds / 1000);
  return (
    seconds % FED_RSS_INTERVAL_SECONDS === 0 ||
    seconds % MARKET_INTERVAL_SECONDS === 0
  );
}

export default {
  async scheduled(controller, env) {
    // The Cloudflare Cron still fires every minute so we preserve the existing
    // clock contract, but a Queue operation is only needed when at least one
    // recorder can actually be due. The 2-minute FED cadence and 5-minute
    // market cadence cover the slower macro/cross-market and hourly prune work.
    if (!shouldEnqueueCaptureTick(controller.scheduledTime)) {
      return;
    }
    await env.AIDY_CAPTURE_QUEUE.send({
      scheduledTime: controller.scheduledTime,
      cron: controller.cron,
    });
  },
};
