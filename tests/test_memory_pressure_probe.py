import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

PATH = Path(__file__).parents[1] / 'scripts/memory_pressure_probe.py'
spec = importlib.util.spec_from_file_location('memory_pressure_probe', PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_correlated_counters_and_no_identity(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    (proc / 'pressure').mkdir(parents=True)
    (proc / 'meminfo').write_text('MemTotal: 100 kB\nMemAvailable: 20 kB\nSwapTotal: 10 kB\nSwapFree: 2 kB\n')
    (proc / 'pressure/memory').write_text('some avg10=1.2 avg60=0.5 total=123\nfull avg10=0.1 total=42\n')
    cgroup = tmp_path / 'cgroup'
    group = cgroup / 'system.slice/private-host.service'
    group.mkdir(parents=True)
    (group / 'memory.current').write_text('1234')
    (group / 'memory.events').write_text('high 2\noom 3\noom_kill 1\n')
    monkeypatch.setattr(probe.subprocess, 'check_output', lambda *a, **kw: '/system.slice/private-host.service\n')
    result = probe.snapshot({'database': 'private-host.service'}, proc, cgroup)
    assert result['host']['MemAvailable'] == 20480
    assert result['pressure']['some']['avg10'] == 1.2
    assert result['services']['database']['memory.events']['oom_kill'] == 1
    assert result['services']['database']['memory.current'] == 1234
    assert result['services']['database']['memory.peak'] is None
    assert 'private-host' not in json.dumps(result)


@pytest.mark.parametrize('group,status', [('', 'inactive_or_missing'), ('/', 'invalid_cgroup'), ('/../../outside', 'invalid_cgroup'), ('/missing', 'unavailable')])
def test_inactive_deleted_and_escaping_cgroups(tmp_path, monkeypatch, group, status):
    monkeypatch.setattr(probe.subprocess, 'check_output', lambda *a, **kw: group)
    assert probe.service_sample('private.service', tmp_path)['status'] == status


def test_lookup_failure_redacts_details(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired('private command', 5)
    monkeypatch.setattr(probe.subprocess, 'check_output', fail)
    assert probe.service_sample('private.service') == {'status': 'unavailable'}


def test_missing_proc_is_reported(tmp_path):
    assert probe.snapshot({}, tmp_path)['host_status'] == 'unavailable'


@pytest.mark.parametrize('args', [['--samples', '0'], ['--interval', '-1'], ['--service', 'bad'], ['--service', 'a=x', '--service', 'a=y']])
def test_invalid_arguments(args):
    result = subprocess.run([sys.executable, str(PATH), *args], capture_output=True, text=True)
    assert result.returncode == 2


def test_bounded_cli(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['probe', '--service', 'database=private.service', '--samples', '2'])
    monkeypatch.setattr(probe, 'snapshot', lambda services: {'aliases': list(services)})
    waits = []
    monkeypatch.setattr(probe.time, 'sleep', waits.append)
    probe.main()
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert len(waits) == 1
