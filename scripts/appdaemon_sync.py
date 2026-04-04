#!/usr/bin/env python3
"""Synchronize the live AppDaemon add-on tree with the git-tracked repo copy."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote


RSYNC_EXCLUDES = (
    "__pycache__/",
    "*.pyc",
    "compiled/",
    "namespaces/",
    "web/",
    "drift_model_data.csv",
)


@dataclass(frozen=True)
class SyncConfig:
    host: str
    samba_user: str
    samba_password: str
    samba_share: str = "addon_configs"
    addon_dir_name: str | None = None


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def repo_root() -> Path:
    result = run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
    )
    return Path(result.stdout.strip()).resolve()


def git_common_dir(root: Path) -> Path:
    result = run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        capture_output=True,
    )
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    return common


def main_checkout_dir(root: Path) -> Path:
    return git_common_dir(root).parent


def load_agents_local(main_checkout: Path) -> dict[str, dict[str, str]]:
    agents_path = main_checkout / "AGENTS.local.md"
    if not agents_path.exists():
        raise RuntimeError(f"Missing local runtime targets file: {agents_path}")

    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None

    for raw_line in agents_path.read_text().splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections.setdefault(current_section, {})
            continue
        if current_section is None or not line.startswith("- "):
            continue

        match = re.match(r"-\s+([^:]+):\s*(.+)", line)
        if not match:
            continue

        key = match.group(1).strip().lower().replace(" ", "_")
        value = match.group(2).strip()
        if value.startswith("`") and value.endswith("`"):
            value = value[1:-1]
        sections[current_section][key] = value

    return sections


def load_sync_config(root: Path, args: argparse.Namespace) -> SyncConfig:
    sections = load_agents_local(main_checkout_dir(root))
    ha = sections.get("Home Assistant", {})
    samba = sections.get("Home Assistant Samba", {})

    host = args.host or samba.get("host") or ha.get("host")
    samba_user = args.samba_user or samba.get("user")
    samba_password = args.samba_password or samba.get("password")
    samba_share = args.samba_share or samba.get("share") or "addon_configs"
    addon_dir_name = args.addon_dir or samba.get("appdaemon_addon_dir")

    missing = [
        name
        for name, value in (
            ("host", host),
            ("samba_user", samba_user),
            ("samba_password", samba_password),
        )
        if not value
    ]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Missing AppDaemon sync settings in AGENTS.local.md or CLI args: "
            f"{joined}"
        )

    return SyncConfig(
        host=host,
        samba_user=samba_user,
        samba_password=samba_password,
        samba_share=samba_share,
        addon_dir_name=addon_dir_name,
    )


def ensure_tools() -> None:
    missing = [
        tool
        for tool in ("git", "mount_smbfs", "umount", "rsync")
        if shutil.which(tool) is None
    ]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required tool(s): {joined}")


def smb_url(config: SyncConfig) -> str:
    user = quote(config.samba_user, safe="")
    password = quote(config.samba_password, safe="")
    host = quote(config.host, safe="")
    share = quote(config.samba_share, safe="")
    return f"//{user}:{password}@{host}/{share}"


@contextmanager
def mounted_share(config: SyncConfig) -> Iterator[Path]:
    mount_dir = Path(tempfile.mkdtemp(prefix="appdaemon-smb."))
    try:
        run(["mount_smbfs", smb_url(config), str(mount_dir)])
        yield mount_dir
    finally:
        run(["umount", str(mount_dir)], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)


def resolve_addon_dir(share_root: Path, configured_name: str | None) -> Path:
    if configured_name:
        addon_dir = share_root / configured_name
        if not addon_dir.is_dir():
            raise RuntimeError(f"Configured add-on directory not found: {addon_dir}")
        return addon_dir

    matches = sorted(
        path for path in share_root.iterdir() if path.is_dir() and path.name.endswith("_appdaemon")
    )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuntimeError("No *_appdaemon directory found in the addon_configs share")
    joined = ", ".join(path.name for path in matches)
    raise RuntimeError(
        "Multiple *_appdaemon directories found; set appdaemon_addon_dir in "
        f"AGENTS.local.md or pass --addon-dir. Matches: {joined}"
    )


def build_rsync_command(
    source: Path,
    destination: Path,
    *,
    delete: bool,
    dry_run: bool = False,
    itemize: bool = False,
) -> list[str]:
    cmd = ["rsync", "-a"]
    if dry_run:
        cmd.append("-n")
    if itemize:
        cmd.append("--itemize-changes")
    if delete:
        cmd.append("--delete")
    for pattern in RSYNC_EXCLUDES:
        cmd.extend(["--exclude", pattern])
    cmd.extend([f"{source}/", f"{destination}/"])
    return cmd


def tracked_appdaemon_dir(root: Path) -> Path:
    return root / "appdaemon"


def pull(root: Path, args: argparse.Namespace) -> int:
    config = load_sync_config(root, args)
    local_dir = tracked_appdaemon_dir(root)
    local_dir.mkdir(parents=True, exist_ok=True)

    with mounted_share(config) as share_root:
        remote_dir = resolve_addon_dir(share_root, config.addon_dir_name)
        cmd = build_rsync_command(
            remote_dir,
            local_dir,
            delete=True,
            dry_run=args.dry_run,
            itemize=not args.quiet or args.dry_run,
        )
        result = run(cmd, capture_output=True)

    if result.stdout and not args.quiet:
        print(result.stdout, end="")
    if not args.dry_run and args.stage:
        run(["git", "add", "--", str(local_dir.relative_to(root))], cwd=root)

    return 0


def push(root: Path, args: argparse.Namespace) -> int:
    config = load_sync_config(root, args)
    local_dir = tracked_appdaemon_dir(root)
    if not local_dir.exists():
        raise RuntimeError(f"Local AppDaemon directory does not exist: {local_dir}")

    with mounted_share(config) as share_root:
        remote_dir = resolve_addon_dir(share_root, config.addon_dir_name)
        cmd = build_rsync_command(
            local_dir,
            remote_dir,
            delete=args.delete,
            dry_run=args.dry_run,
            itemize=True,
        )
        result = run(cmd, capture_output=True)

    if result.stdout:
        print(result.stdout, end="")

    return 0


def diff(root: Path, args: argparse.Namespace) -> int:
    config = load_sync_config(root, args)
    local_dir = tracked_appdaemon_dir(root)
    local_dir.mkdir(parents=True, exist_ok=True)

    with mounted_share(config) as share_root:
        remote_dir = resolve_addon_dir(share_root, config.addon_dir_name)
        cmd = build_rsync_command(
            remote_dir,
            local_dir,
            delete=True,
            dry_run=True,
            itemize=True,
        )
        result = run(cmd, capture_output=True)

    output = result.stdout.strip()
    if output:
        print(output)
        return 1
    if not args.quiet:
        print("AppDaemon repo copy matches the live add-on tree.")
    return 0


def install_hooks(root: Path, _args: argparse.Namespace) -> int:
    run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root)
    print("Configured local git hooks path: .githooks")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize the git-tracked appdaemon/ directory with the live "
            "Home Assistant AppDaemon add-on under addon_configs."
        )
    )
    parser.add_argument("--host", help="Home Assistant host or IP")
    parser.add_argument("--samba-user", help="Samba username")
    parser.add_argument("--samba-password", help="Samba password")
    parser.add_argument("--samba-share", help="Samba share name", default=None)
    parser.add_argument(
        "--addon-dir",
        help="Explicit AppDaemon add-on directory name inside addon_configs",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    pull_parser = subparsers.add_parser(
        "pull",
        help="Pull the live add-on tree into repo/appdaemon and optionally stage it.",
    )
    pull_parser.add_argument("--dry-run", action="store_true")
    pull_parser.add_argument("--stage", action="store_true")
    pull_parser.add_argument("--quiet", action="store_true")
    pull_parser.set_defaults(func=pull)

    diff_parser = subparsers.add_parser(
        "diff",
        help="Show whether repo/appdaemon differs from the live add-on tree.",
    )
    diff_parser.add_argument("--quiet", action="store_true")
    diff_parser.set_defaults(func=diff)

    push_parser = subparsers.add_parser(
        "push",
        help="Copy repo/appdaemon back to the live add-on tree.",
    )
    push_parser.add_argument("--dry-run", action="store_true")
    push_parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete live files missing from repo/appdaemon",
    )
    push_parser.set_defaults(func=push)

    hooks_parser = subparsers.add_parser(
        "install-hooks",
        help="Point the local repo config at the tracked .githooks directory.",
    )
    hooks_parser.set_defaults(func=install_hooks)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_tools()
    parser = build_parser()
    args = parser.parse_args(argv)
    root = repo_root()
    try:
        return args.func(root, args)
    except RuntimeError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
