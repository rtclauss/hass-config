#!/usr/bin/env python3
"""Read-only Linux memory samples as JSONL; keep output private and local."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


def numbers(path):
    """Read kernel key/value counters, converting meminfo kB to bytes."""
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        result[fields[0].rstrip(':')] = int(fields[1]) * (1024 if fields[2:] == ['kB'] else 1)
    return result


def pressure(path):
    return {fields[0]: {key: float(value) for key, value in
                       (entry.split('=') for entry in fields[1:])}
            for fields in (line.split() for line in path.read_text().splitlines())}


def service_sample(unit, root=Path('/sys/fs/cgroup')):
    """Resolve on every sample so a service restart cannot leave a stale cgroup."""
    try:
        group = subprocess.check_output(
            ['systemctl', 'show', '--property=ControlGroup', '--value', '--', unit],
            text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        if not group or not group.startswith('/'):
            return {'status': 'inactive_or_missing'}
        directory = (root / group.lstrip('/')).resolve()
        if not directory.is_relative_to(root.resolve()) or directory == root.resolve():
            return {'status': 'invalid_cgroup'}
        sample = {'status': 'ok', 'memory.current': int((directory / 'memory.current').read_text())}
        for field in ['memory.peak', 'memory.swap.current']:
            try:
                sample[field] = int((directory / field).read_text())
            except FileNotFoundError:
                sample[field] = None  # optional counters differ across kernels
        sample['memory.events'] = numbers(directory / 'memory.events')
        return sample
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        # Do not expose unit names, paths, stderr or host details in diagnostics.
        return {'status': 'unavailable'}


def snapshot(services, proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    started = time.monotonic()
    result = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'services': {}}
    try:
        memory = numbers(proc / 'meminfo')
        result['host'] = {key: memory[key] for key in
                          ['MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree']}
        result['pressure'] = pressure(proc / 'pressure/memory')
    except (OSError, ValueError, KeyError, IndexError):
        result['host_status'] = 'unavailable'
    for alias, unit in services.items():
        result['services'][alias] = service_sample(unit, cgroup)
    result['sample_duration_seconds'] = round(time.monotonic() - started, 3)
    return result


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', action='append', default=[], metavar='ALIAS=UNIT')
    parser.add_argument('--interval', type=positive, default=30, help='seconds between samples')
    parser.add_argument('--samples', type=positive, default=1, help='bounded sample count')
    args = parser.parse_args()
    services = {}
    for item in args.service:
        alias, separator, unit = item.partition('=')
        if not separator or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', alias) or not unit or unit.startswith('-'):
            parser.error('service must be a lowercase alias and a nonempty unit')
        if alias in services:
            parser.error('service aliases must be unique')
        services[alias] = unit
    for index in range(args.samples):
        started = time.monotonic()
        print(json.dumps(snapshot(services)), flush=True)
        if index + 1 < args.samples:
            time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
