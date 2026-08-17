export default {
  async scheduled(controller, env) {
    await env.AIDY_CAPTURE_QUEUE.send({
      scheduledTime: controller.scheduledTime,
      cron: controller.cron,
    });
  },
};
