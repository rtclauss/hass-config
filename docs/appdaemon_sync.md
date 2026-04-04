# AppDaemon Sync

The live Home Assistant AppDaemon add-on under the Supervisor-managed
`addon_configs` share is the source of truth for this repo.

The repo copy lives at `appdaemon/` so Git tracks normal project files instead
of a hashed add-on directory name.

## Commands

Pull the live add-on tree into the repo and stage it:

```sh
python3 scripts/appdaemon_sync.py pull --stage
```

Check whether the repo copy differs from the live add-on tree:

```sh
python3 scripts/appdaemon_sync.py diff
```

Push the repo copy back to the live AppDaemon add-on:

```sh
python3 scripts/appdaemon_sync.py push
```

Use `--delete` on push only when you explicitly want the live add-on tree to be
pruned to match the repo.

## Local Runtime Targets

This workflow reads Samba connection details from the main checkout's
`AGENTS.local.md`, not from the worktree.

Expected local-only section:

```md
## Home Assistant Samba

- host: `10.24.1.11`
- user: `hassio`
- password: `pass`
- share: `addon_configs`
- appdaemon_addon_dir: `a0d7b954_appdaemon`
```

If `appdaemon_addon_dir` is omitted, the sync tool auto-detects a single
`*_appdaemon` directory in the `addon_configs` share.

## Pre-commit Hook

Install the tracked git hooks locally:

```sh
scripts/install_appdaemon_hooks.sh
```

The pre-commit hook auto-pulls live AppDaemon changes only when `appdaemon/` is
clean locally. That keeps accidental hook-driven overwrites away from intentional
local edits.

Set `APPDAEMON_SYNC_SKIP=1` to bypass the hook for a single commit.
