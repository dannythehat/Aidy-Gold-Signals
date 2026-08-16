# AIDY Gold Signals

Standalone AIDY Signals Gold trading intelligence and Telegram signal-provider project.

AIDY and Super Signals are separate systems. AIDY produces signals; Super Signals may later consume the AIDY Telegram group exactly like any other external provider.

## Permanent boundaries

- Separate repository, runtime and database from Super Signals.
- No GitHub Actions.
- No direct MT5 execution from the AIDY intelligence layer.
- No live-money capability during build and paper testing.
- Point-in-time market evidence and decision auditability are mandatory.
