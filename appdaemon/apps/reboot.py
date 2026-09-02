"""Reboot the Home Assistant OS host when the LAN becomes unreachable.

History: this app used to ping a single external IP (8.8.8.8). When that
address stopped answering ICMP (firewall / host under load) every cycle
"failed" and the app rebooted the HAOS host every ~2.5 h in a loop
(incident 2026-09-01). It now pings a list of always-on LAN targets and
only counts a cycle as failed when *every* target is unreachable, so one
host that drops ICMP can no longer trigger a reboot. A cooldown caps how
often a reboot can happen, and a notification is sent first so the reboot
is visible in history.

apps.yaml args (all optional):
  hosts_to_ping: list of IPs/hostnames to probe (default: Proxmox host + LAN DNS)
  host_to_ping: single legacy target; used only if hosts_to_ping is unset
  max_failures: consecutive failed cycles before rebooting (default 5)
  check_interval_minutes: minutes between cycles (default 33)
  min_reboot_interval_hours: minimum spacing between reboots (default 6)
  notify_service: notify service for the pre-reboot alert (default notify/mobile_app_wethop)
"""

import os
import subprocess
import time
from datetime import datetime, timedelta

import hassapi as hass

DEFAULT_HOSTS = ["10.24.1.253", "10.24.1.252"]  # Proxmox host, LAN DNS/firewall
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_host_reboot")


class restart_ha(hass.Hass):

    def initialize(self):
        hosts = self.args.get("hosts_to_ping")
        if not hosts:
            legacy = self.args.get("host_to_ping")
            hosts = [legacy] if legacy else list(DEFAULT_HOSTS)
        self.hosts = [str(h) for h in hosts]

        self.max_failures = int(self.args.get("max_failures", 5))
        self.check_interval = int(self.args.get("check_interval_minutes", 33)) * 60
        self.min_reboot_interval = timedelta(
            hours=float(self.args.get("min_reboot_interval_hours", 6))
        )
        self.notify_service = self.args.get("notify_service", "notify/mobile_app_wethop")

        self.num_failures = 0
        self.log(
            "restart_ha init: hosts={} max_failures={} interval={}s cooldown={}".format(
                self.hosts, self.max_failures, self.check_interval, self.min_reboot_interval
            )
        )
        self.run_every(
            self.ping_server, datetime.now() + timedelta(seconds=15), self.check_interval
        )

    def _reachable(self, host):
        try:
            return (
                subprocess.call(
                    ["ping", "-c", "3", "-W", "2", host],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                == 0
            )
        except Exception as err:  # noqa: BLE001 - ping should never crash the app
            self.log("ping {} raised {}".format(host, err), level="WARNING")
            return False

    def ping_server(self, kwargs):
        reachable = [h for h in self.hosts if self._reachable(h)]
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
                self.hosts, self.num_failures, self.max_failures
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
                        ", ".join(self.hosts), self.num_failures, minutes_down
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
