# custom_components and HACS

HACS (and the files it installs) is the source of truth for third-party integrations.
Git does **not** track them. Before #1097 a partial copy was tracked: edited files were
committed but brand-new files from each HACS update were silently ignored by `.gitignore`,
so the tracked copy drifted into a half-updated snapshot that could not import itself.

## What is tracked

Only `custom_components/mass_queue/services.yaml`, which `tests/test_mass_queue_services_present.py`
reads for the Music Assistant dashboard. It mirrors the upstream Music Assistant Queue Actions
integration's `services.yaml`, so if that integration is ever installed through HACS it will
modify this tracked file and make the host dirty. If that happens, or if nothing uses the
integration, drop the file and its test and ignore the whole directory. Everything else under
`custom_components/` is ignored, including the small `services.yaml`-only copies that used to be
tracked: HACS rewrites them on every update, so tracking them would keep the host dirty.

## Restoring a host

Install HACS, then reinstall the integrations from HACS. Home Assistant backups also include
`custom_components/`. Integrations that used to be tracked: `adaptive_lighting`, `auto_areas`,
`bermuda`, `birdbuddy`, `browser_mod`, `garbage_collection`, `hacs`, `localtuya`, `magic_areas`,
`mail_and_packages`, `noaa_space_weather`, `places`, `retry`, `scrypted`, `smartthinq_sensors`,
`somafm`, `spook`, `tesla_custom`, `weatheralerts`, plus `services.yaml`-only copies of
`dreame_vacuum`, `f1_sensor`, `ha_unavailable_devices_report`, `ha_washdata`, `llmvision`,
`midea_ac_lan`, `presence_simulation` and `watchman`.

## Deploy warning (read before pulling this change onto a host)

Pulling a commit that stops tracking files **deletes them from that host's working tree**, and
a plain `git pull` is refused while HACS has modified any tracked file (the normal state of a
host that has updated an integration). Do not make a local "untracking" commit on the host:
it diverges from the incoming commit and an `--ff-only` pull rejects it.

Use backup, pull, restore. Keep the backup **outside** the repo (for example `/share`),
otherwise git lists it as untracked:

```bash
cd /config
cp -a custom_components /share/custom_components.bak      # 1. back up what HACS installed
git checkout -- custom_components                         # 2. drop local edits to tracked copies
git pull --ff-only                                         # 3. deletes the old tracked copies
cp -a /share/custom_components.bak/. custom_components/    # 4. restore everything from the backup
git status --short custom_components                       # 5. must print nothing (all ignored)
```

Restart Home Assistant, confirm the integrations load, then delete the backup. If an add-on
pulls automatically (Git Pull add-on or a cron job), stop it first; anything that runs
`git reset --hard` or `git clean` will delete these files too. The same applies when this
change reaches `main`.
