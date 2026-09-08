"""Reboot the Home Assistant OS host when the LAN becomes unreachable.

History:
  * Originally pinged a single external IP (8.8.8.8). When ICMP to it started
    being dropped, every cycle "failed" and the app reboot-looped the HAOS host
    every ~2.5 h (incident 2026-09-01).
  * The first fix switched to a list of LAN targets but still shelled out to
    `ping`. The AppDaemon add-on's Debian-slim base image has no `ping` binary
    (and no CAP_NET_RAW), so `ping` failed on *every* call regardless of the
    network -> the reboot loop continued, ~every 2 h 16 m (incident 2026-09-08).

Now the reachability check is a pure-Python TCP connect (no external binary, no
raw sockets, no capabilities). A cycle only counts as a failure when *every*
target is unreachable. A cooldown caps reboot frequency and a notification is
sent first so a reboot is visible in history.

apps.yaml args (all optional):
  probe_targets: list of "host:port" to test (default: Proxmox UI + LAN DNS).
                 Also accepts the legacy keys `hosts_to_ping` / `host_to_ping`
                 (a bare host gets a default port appended).
  default_port: port to append to bare hosts (default 443)
  connect_timeout_seconds: per-target TCP connect timeout (default 3)
  max_failures: consecutive failed cycles before rebooting (default 5)
  check_interval_minutes: minutes between cycles (default 33)
  min_reboot_interval_hours: minimum spacing between reboots (default 6)
  notify_service: notify service for the pre-reboot alert (default notify/mobile_app_wethop)
"""

import os
import socket
import time
from datetime import datetime, timedelta

import hassapi as hass

# Always-on LAN infrastructure this VM must be able to reach. A connection that
# is *refused* still proves the host and the network path are alive, so only a
# timeout / no-route counts against a target.
DEFAULT_TARGETS = ["10.24.1.253:8006", "10.24.1.252:53"]  # Proxmox UI, LAN DNS
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_host_reboot")


class restart_ha(hass.Hass):

    def initialize(self):
        default_port = int(self.args.get("default_port", 443))
        raw = (
            self.args.get("probe_targets")
            or self.args.get("hosts_to_ping")
            or ([self.args["host_to_ping"]] if self.args.get("host_to_ping") else None)
            or list(DEFAULT_TARGETS)
        )
        self.targets = [self._parse_target(str(t), default_port) for t in raw]

        self.timeout = float(self.args.get("connect_timeout_seconds", 3))
        self.max_failures = int(self.args.get("max_failures", 5))
        self.check_interval = int(self.args.get("check_interval_minutes", 33)) * 60
        self.min_reboot_interval = timedelta(
            hours=float(self.args.get("min_reboot_interval_hours", 6))
        )
        self.notify_service = self.args.get("notify_service", "notify/mobile_app_wethop")

        self.num_failures = 0
        self.log(
            "restart_ha init: targets={} timeout={}s max_failures={} "
            "interval={}s cooldown={}".format(
                self.targets, self.timeout, self.max_failures,
                self.check_interval, self.min_reboot_interval,
            )
        )
        self.run_every(
            self.check_network, datetime.now() + timedelta(seconds=15), self.check_interval
        )

    @staticmethod
    def _parse_target(target, default_port):
        host, sep, port = target.rpartition(":")
        if sep and port.isdigit():
            return (host, int(port))
        return (target, default_port)

    def _reachable(self, target):
        host, port = target
        try:
            socket.create_connection((host, port), timeout=self.timeout).close()
            return True
        except ConnectionRefusedError:
            return True  # host answered with RST -> network path is fine
        except OSError as err:  # timeout, EHOSTUNREACH, ENETUNREACH, gaierror
            self.log("probe {}:{} failed: {}".format(host, port, err), level="DEBUG")
            return False

    def check_network(self, kwargs):
        reachable = [t for t in self.targets if self._reachable(t)]
        if reachable:
            if self.num_failures > 0:
                self.log(
                    "LAN reachable via {}. Resetting failure count from {}.".format(
                        reachable, self.num_failures
                    )
                )
            self.num_failures = 0
            return

        self.num_failures += 1
        self.log(
            "No LAN targets reachable ({}). Consecutive failed cycles: {}/{}.".format(
                self.targets, self.num_failures, self.max_failures
            ),
            level="WARNING",
        )
        if self.num_failures < self.max_failures:
            return

        if not self._reboot_allowed():
            self.log(
                "LAN down for {} cycles but a host reboot happened < {} ago - "
                "not rebooting again yet.".format(self.num_failures, self.min_reboot_interval),
                level="ERROR",
            )
            return

        minutes_down = self.num_failures * self.check_interval // 60
        self.log(
            "LAN unreachable for {} consecutive cycles (~{} min). "
            "Rebooting HAOS host.".format(self.num_failures, minutes_down),
            level="ERROR",
        )
        try:
            self.call_service(
                self.notify_service,
                title="Rebooting HAOS host",
                message=(
                    "LAN targets {} unreachable for {} cycles (~{} min). "
                    "Rebooting the host.".format(
                        ", ".join("{}:{}".format(*t) for t in self.targets),
                        self.num_failures,
                        minutes_down,
                    )
                ),
            )
        except Exception as err:  # noqa: BLE001
            self.log("pre-reboot notify failed: {}".format(err), level="WARNING")

        self._record_reboot()
        # Give the notification a few seconds to leave before the host goes down.
        self.run_in(self._do_reboot, 5)

    def _do_reboot(self, kwargs):
        self.call_service("hassio/host_reboot")

    def _reboot_allowed(self):
        try:
            with open(STATE_FILE) as handle:
                last = datetime.fromtimestamp(float(handle.read().strip()))
        except (OSError, ValueError):
            return True
        return datetime.now() - last >= self.min_reboot_interval

    def _record_reboot(self):
        try:
            with open(STATE_FILE, "w") as handle:
                handle.write(str(time.time()))
        except OSError as err:
            self.log("could not write {}: {}".format(STATE_FILE, err), level="WARNING")
