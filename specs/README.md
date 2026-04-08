# Specs

These Allium files are the behavioral source of truth for the owner sleep/wake flows in this repo.

- `alarm_wakeup.allium`: iOS alarm sync, timed wake-up branches, wake-up execution, bathroom follow-up audio, snooze/cancel, and morning recovery.
- `night_routines.allium`: bedtime prep, CPAP-triggered goodnight integrity, privacy-aware overnight shutdown, and bedtime exception handling.

When wake-up, alarm, bedtime, or overnight automation behavior changes, update the relevant `.allium` file in the same change.
