# Memory pressure investigation

Use `scripts/memory_pressure_probe.py` on a Linux service host to correlate host
memory pressure with selected systemd services. It uses only Python's standard
library, reads procfs/cgroup v2 and calls `systemctl show`. It does not restart,
limit or modify services, and does not connect to Home Assistant or upload data.

Run a bounded capture locally on the affected host, using actual unit names only
in the local command. For example (synthetic units):

```sh
umask 077
python3 memory_pressure_probe.py --service database=example-db.service \
  --service media=example-media.service --samples 1440 --interval 30 > memory-private.jsonl
```

Keep captures outside the repository. Use neutral aliases: the output deliberately
omits hostname, service unit names, cgroup paths, command lines and process IDs.
Aliases and timestamps can still be sensitive; review any excerpt before sharing.
No scheduled public report or artifact upload is configured.

Each JSON line records UTC time, host available RAM and swap (bytes), memory PSI,
and selected service current/peak/swap usage plus memory-event counters. A sample
is sequential, not atomic; its duration exposes slow collection. Unit cgroups are
resolved again each sample to follow restarts. Unsupported optional counters are
null; absent/inaccessible services and host data report status instead of silently
becoming zero. Peak counters cover the cgroup lifetime and **must not be added
as simultaneous demand**. Compare current values at matching timestamps and
changes in `oom`/`oom_kill`, allowing for counter resets after service restarts.

Capture an entire known busy window. Correlate pressure and current usage with
privately retained workload/job timing before choosing a service to reschedule,
move or constrain. A quiet sample does not establish recovery. This tool provides
evidence for #723; it does not itself fix host capacity or close the issue.
