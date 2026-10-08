# Local Ollama Home Analyst

This package provides six compact, read-only semantic sensors for a text-first
Home Assistant analyst. It deliberately does not add voice, STT, TTS, shell
commands, or device-control tools. The source values remain visible in the
`source_states` JSON attribute so an answer can distinguish measured state from
an inference and identify `unknown`/`unavailable` inputs.

## Review decisions

- The curated summaries reuse existing fused occupancy, bed, Ecobee, opening,
  and Zigbee availability entities; raw telemetry is not exposed.
- Summary sensors are YAML because each combines multiple entities and small
  attribute payloads. They are not replacements for existing UI helpers.
- Ollama Conversation config and entity exposure are config-entry/UI managed;
  no unsupported YAML is fabricated and no `.storage` file is edited.
- No control scripts are exposed. Recorder history and trace-aware diagnostics
  remain a future, explicitly read-only extension.
- Missing or unavailable sources are rendered as their HA state, rather than
  silently coerced to a confident value. The anomaly summary is explicitly a
  limited observation list, not a safety guarantee.

## Configure the analyst in Home Assistant

1. Confirm the Ollama integration is installed and reachable from Home
   Assistant, then create/select an Ollama Conversation agent in Settings →
   Devices & services → Ollama/Conversation.
2. Select an installed `qwen*` model. Recommended starting point is
   `qwen3:4b` when present; otherwise choose the installed Qwen model with the
   smallest context that meets your latency needs. Keep thinking off initially,
   use an approximately 8192-token context, and enable persistent keep-alive if
   the integration exposes that option.
3. Expose only these six entities to the agent:
   `sensor.home_analyst_occupancy_summary`,
   `sensor.home_analyst_bed_summary`,
   `sensor.home_analyst_hvac_summary`,
   `sensor.home_analyst_openings_summary`,
   `sensor.home_analyst_health_summary`, and
   `sensor.home_analyst_anomaly_summary`.
4. Use this instruction text for the Conversation agent:

   > You are the Home Analyst. Answer from available Home Assistant state and
   > tools only. Prefer the curated semantic summaries. Clearly label measured
   > state versus inference, report disagreement or unknown/unavailable inputs,
   > and never invent causes. For “why” questions, separate observed facts from
   > likely explanations. Keep routine status answers concise. Do not claim an
   > automation caused an outcome without evidence. You are read-only: do not
   > control devices or perform administrative actions.

If the selected Ollama integration version does not expose one of these UI
options, leave it at its integration default and record the actual model in the
agent configuration; the package remains model-agnostic.

## Validation and rollback

Validate the repository YAML/tests before reload. In Home Assistant, reload
Template entities (or restart if package reload is unavailable), then ask the
agent about occupancy, bed state, HVAC, openings, and anomalies. Roll back by
removing `packages/home_analyst.yaml` and reloading/restarting; no existing
entity IDs are changed.
