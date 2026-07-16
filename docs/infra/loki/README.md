# Log Aggregation: Loki + Promtail

## Architecture

```
HA core logs (/config/home-assistant.log)
        │
        ▼
Promtail (HA app, 39bd2704_promtail)
        │  pushes to http://10.24.1.99:3100
        ▼
Loki (Docker on 10.24.1.99, port 3100)
        │
        ▼
Grafana (native on 10.24.1.99, port 3000) ← datasource: Loki
```

## Loki Setup (infra server: 10.24.1.99)

Files in this directory are deployed to `~/loki/` on the infra server.

```bash
cd ~/loki
cp .env.example .env      # then set LOKI_BIND_ADDR to the server's LAN address
docker compose up -d
```

`.env` is required and is not committed. Loki runs with `auth_enabled: false`, so
the API is unauthenticated and must be published on one interface rather than all
of them; compose refuses to start if `LOKI_BIND_ADDR` is unset rather than
falling back to an all-interfaces bind.

Data is stored at `~/loki/data/` (Docker bind mount, runs as root for write access).
That bind mount is the only persisted path, so the ingester WAL is pointed at
`/loki/wal` inside it — Loki's default WAL location lives in the container's
writable layer and would lose unflushed entries on every recreate.

## Promtail Configuration (HA App)

Promtail (mdegat01/addon-promtail v2.6.1) is installed as a HA app.

**Note on journal scraping**: The default journal scraping is disabled on HA OS 2026.x
due to apparmor restrictions blocking systemd journal socket access. Instead, Promtail
is configured to tail `/config/home-assistant.log` directly.

Current live config (set via supervisor API):
```yaml
client:
  url: http://10.24.1.99:3100/loki/api/v1/push
log_level: info
skip_default_scrape_config: true
additional_scrape_configs: |
  - job_name: homeassistant
    static_configs:
      - targets: [localhost]
        labels:
          job: homeassistant
          host: brewery-ha
          __path__: /config/home-assistant.log
    pipeline_stages:
      - regex:
          expression: '^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+) (?P<level>\w+) \(\w+\) \[(?P<logger>[^\]]+)\] (?P<message>.+)$'
      # Promote the parsed HA timestamp. Without this stage Promtail stamps each
      # entry at scrape time, so a first tail or a backfill lands the whole file
      # at "now" — time-range queries and alerts then read the wrong times.
      # HA writes local time with millisecond precision and no offset, so the
      # location must be given explicitly.
      - timestamp:
          source: timestamp
          format: '2006-01-02 15:04:05.000'
          location: America/Chicago
      - labels:
          level:
          logger:
```

## Grafana Datasource

`grafana-datasource.yaml` is provisioned to `/etc/grafana/provisioning/datasources/loki.yaml`
on the infra server. Grafana is restarted to apply.

Datasource URL: `http://localhost:3100` (local to infra server)

## Querying Logs in Grafana

Example LogQL queries:
- All HA logs: `{job="homeassistant"}`
- Errors only: `{job="homeassistant", level="ERROR"}`
- Z2M events: `{job="homeassistant"} |= "zigbee2mqtt"`
- Integration load failures: `{job="homeassistant"} |= "Error" |= "setup"`

## Known Issues

- **Alloy not available**: The Grafana Alloy HA app (Promtail replacement) is not yet in
  the HA app store. Promtail (deprecated but functional) is used until Alloy becomes available.
- **Journal access blocked**: HA OS 2026.x apparmor profile blocks Promtail from reading
  the systemd journal. File-based scraping is used as a workaround.
- **Loki HA app broken**: The mdegat01 Loki HA app (v1.11.2) fails with permission errors
  on HA OS 2026.x. Loki runs on the infra server instead.
