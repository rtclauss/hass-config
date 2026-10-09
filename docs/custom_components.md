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
BAK=/share/custom_components.$(date +%Y%m%d-%H%M%S)        # always a fresh path: cp onto an existing folder nests the copy
cp -a custom_components "$BAK"                             # 1. back up what HACS has installed right now
git checkout -- custom_components                          # 2. drop local edits to tracked copies
git pull --ff-only                                          # 3. deletes the old tracked copies
cp -a "$BAK"/. custom_components/                           # 4. restore everything from the backup
git status --short custom_components                        # 5. must print nothing (all ignored)
```

Never reuse an older backup folder for this: restoring a stale one would bring back integrations
you have since removed.

Restart Home Assistant, confirm the integrations load, then delete the backup. If an add-on
pulls automatically (Git Pull add-on or a cron job), stop it first; anything that runs
`git reset --hard` or `git clean` will delete these files too. The same applies when this
change reaches `main`.

## Why git does not track HACS integrations

This matches common practice: the Home Assistant `.gitignore` template lists `custom_components`
under "Development files" ([template](https://www.toptal.com/developers/gitignore/api/homeassistant)),
and large public configs ignore `custom_components/*` and re-include only their own hand-written
integrations ([example](https://raw.githubusercontent.com/CCOSTAN/Home-AssistantConfig/master/.gitignore)).
HACS records what is installed in `.storage/hacs.repositories` and can redownload it, so a code
copy in git adds drift without adding recoverability. The Git Pull add-on has a "reset" mode that
runs `git reset --hard` and overwrites tracked files
([docs](https://raw.githubusercontent.com/home-assistant/addons/master/git_pull/DOCS.md)), which is
another reason not to leave HACS-owned files tracked.

## Server migration plan

Do these in order on the Home Assistant host (SSH add-on shell, repo at `/config`).

### 0. Look first (read-only)

```bash
cd /config && git status --short | head -20; git branch --show-current; git log -1 --oneline
ha addons 2>/dev/null | grep -i -B1 -A3 git            # is an auto-pull add-on installed?
ls custom_components/weatheralerts/frontend.py custom_components/smartthinq_sensors/number.py
```

If those two files exist, nothing is broken today; the tracked copy was just incomplete. Then run
this inventory. It lists every folder in `custom_components/` with its HACS version, active config
entries, enabled entities, and how many YAML/Python/Jinja files in `/config` mention it:

```bash
python3 - <<'EOF'
import json, os, subprocess, collections
cfg = "/config"
st = lambda n: json.load(open(f"{cfg}/.storage/{n}"))["data"]
entries = collections.Counter(e["domain"] for e in st("core.config_entries")["entries"] if not e.get("disabled_by"))
ents = collections.Counter(e["platform"] for e in st("core.entity_registry")["entities"] if not e.get("disabled_by"))
try:
    hacs = {(r.get("domain") or r.get("full_name", "").split("/")[-1]): r.get("version_installed")
            for r in st("hacs.repositories").values() if r.get("installed")}
except Exception:
    hacs = {}
print(f"{'directory':32}{'hacs version':14}{'entries':>8}{'entities':>9}{'yaml refs':>10}")
for d in sorted(os.listdir(f"{cfg}/custom_components")):
    if not os.path.isdir(f"{cfg}/custom_components/{d}") or d == "__pycache__":
        continue
    refs = subprocess.run(
        ["grep", "-rIlw", "--include=*.yaml", "--include=*.py", "--include=*.jinja", d, cfg,
         "--exclude-dir=custom_components", "--exclude-dir=.git", "--exclude-dir=.storage", "--exclude-dir=backup"],
        capture_output=True, text=True).stdout.split()
    print(f"{d:32}{str(hacs.get(d, '-')):14}{entries[d]:>8}{ents[d]:>9}{len(refs):>10}")
EOF
```

### 1. Safety net

Take a full backup (`ha backups new --name pre-untrack`) and stop any auto-pull add-on. The
`custom_components` copy comes later, in step 3, so it reflects the cleaned-up state.

### 2. Remove integrations nothing uses (before the git change)

Do this first so you do not back up or restore dead code. An integration is a candidate when the
inventory shows 0 entries, 0 entities **and** 0 YAML references. Services-only integrations
(`retry`, `spook`, `watchman`, `browser_mod`) have no entities but may be called from YAML, so the
YAML column decides. Evidence from this repo as of 2026-10-09 (it can only see YAML; UI-configured
integrations leave no trace, so confirm with the inventory before deleting anything):

| Evidence | Integrations |
|---|---|
| Clearly used | `adaptive_lighting`, `hacs`, `places`, `bermuda`, `mail_and_packages`, `somafm`, `tesla_custom`, `dreame_vacuum`, `garbage_collection`, `retry`, `spook`, `weatheralerts`, `f1_sensor`, `browser_mod`, `scrypted`, `smartthinq_sensors`, `localtuya`, `birdbuddy` |
| No repo trace, check the inventory | `auto_areas`, `magic_areas`, `noaa_space_weather`, `midea_ac_lan`, `ha_washdata`, `llmvision`, `ha_unavailable_devices_report` |
| Check carefully | `watchman` (only the admin-dashboard issue mentions it), `presence_simulation` (an open issue says its startup hook crashes, so it is installed and failing), `magic_areas` / `auto_areas` (named as possible sources of the unexpected blind opener in the blind-forensics issue) |
| Nothing uses it | `mass_queue`, apart from the tracked `services.yaml` mirror and its test |

Remove through HACS ("Remove"), restart, and watch Repairs and the logs for a day before deleting
the backup. Do not delete folders by hand: HACS then keeps listing them as installed.

### 3. Sync git and the host

After this change reaches the branch the host runs, follow the backup, pull, restore sequence in
"Deploy warning" above, taking its dated backup *after* step 2 so removed integrations are not restored. Then restart Home Assistant, confirm the integrations load, run a HACS
update and check `git status --short custom_components` is still empty.

### 4. Keep it that way

The final `.gitignore` block (checked by `tests/test_custom_components_gitignore.py`) keeps new HACS
files out of git. If the weekly promotion audit proposed in #1095 is merged, it will also never
recommend `custom_components/**` for promotion. To make a fresh-host restore easy, save the
inventory output (or `.storage/hacs.repositories`) next to your backups.
