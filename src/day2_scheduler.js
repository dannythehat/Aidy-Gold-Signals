export default {
  async scheduled(controller, env) {
    // Queue budgeting is enforced by the deployed Cron trigger set, not by
    // filtering ScheduledController.scheduledTime inside the Worker. Every
    // Cron invocation is therefore a recorder-due tick and must be delivered.
    await env.AIDY_CAPTURE_QUEUE.send({
      scheduledTime: controller.scheduledTime,
      cron: controller.cron,
    });
  },
};
