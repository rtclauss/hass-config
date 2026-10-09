# custom_components and HACS

HACS (and the files it installs) is the source of truth for third-party integrations.
Git does **not** track them. Before #1097 a partial copy was tracked: edited files were
committed but brand-new files from each HACS update were silently ignored by `.gitignore`,
so the tracked copy drifted into a half-updated snapshot that could not import itself.

## What is tracked

Only hand-written stubs: `custom_components/mass_queue/services.yaml` (used by the Music
Assistant dashboard, see `tests/test_mass_queue_services_present.py`) and a few
`services.yaml`-only placeholders. Everything else under `custom_components/` is ignored.

## Restoring a host

Install HACS, then reinstall the integrations from HACS. The list of integrations that used
to be tracked: `adaptive_lighting`, `auto_areas`, `bermuda`, `birdbuddy`, `browser_mod`,
`garbage_collection`, `hacs`, `localtuya`, `magic_areas`, `mail_and_packages`,
`noaa_space_weather`, `places`, `retry`, `scrypted`, `smartthinq_sensors`, `somafm`, `spook`,
`tesla_custom`, `weatheralerts`. Home Assistant backups also include `custom_components/`.

## Deploy warning (read before pulling this change onto a host)

A commit that stops tracking files deletes them from the working tree of any host that pulls it
(Git Pull add-on, `git pull`, `git checkout`). On a host that runs from this repo, either:

1. Make the untracking commit **on that host** (`git rm -r --cached custom_components/<dir>`)
   so the files stay on disk; or
2. Back up first: `cp -a /config/custom_components /config/custom_components.bak`, pull, then
   `cp -a /config/custom_components.bak/. /config/custom_components/`. The restored files are
   ignored, so they stay untracked.

This also applies when this lands on `main`.
