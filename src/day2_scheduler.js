export function shouldEnqueueCaptureTick(scheduledTime) {
  const milliseconds = Number(scheduledTime);
  if (!Number.isFinite(milliseconds)) {
    throw new TypeError("AIDY scheduler requires a finite scheduledTime.");
  }
  const minute = new Date(milliseconds).getUTCMinutes();
  return minute % 2 === 0 || minute % 5 === 0;
}

export default {
  async scheduled(controller, env) {
    // Keep one standard every-minute Cloudflare Cron trigger and enforce the
    // Queue budget from the nominal UTC minute. This avoids relying on exact
    // second alignment in ScheduledController.scheduledTime while preserving
    // the 2-minute FED and 5-minute market recorder cadence.
    if (!shouldEnqueueCaptureTick(controller.scheduledTime)) {
      return;
    }
    await env.AIDY_CAPTURE_QUEUE.send({
      scheduledTime: controller.scheduledTime,
      cron: controller.cron,
    });
  },
};
