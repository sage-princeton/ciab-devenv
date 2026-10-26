"""Bounded systemd execution and sanitized evidence inside the isolated machine."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/devenv')
from ciab_devenv.machine import scrub  # noqa: E402

from ciab_devenv.scaffolds import get_scaffold  # noqa: E402


def environment():
    result = {}
    for name in ('/etc/crux-run.env', '/etc/ciab-run.env'):
        for line in Path(name).read_text().splitlines():
            if '=' not in line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            result[key] = json.loads(value) if value.startswith('"') else value
    for index, value in enumerate(json.loads(Path('/etc/ciab-redactions.json').read_text())):
        result[f'SECRET_{index}'] = value
    return result


def service_state(unit):
    result = subprocess.check_output(['systemctl', 'show', unit, '--property=ActiveState,SubState,ExecMainStatus,Result,InvocationID'], text=True)
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def main():
    os.umask(0o077)
    request = Path(sys.argv[1])
    data = json.loads(request.read_text())
    request.unlink()
    run_id, suite = data['run_id'], data['suite']
    scaffold = get_scaffold(data.get('scaffold', 'sdk'), data.get('platform'))
    output = Path('/var/lib/ciab/reports') / run_id
    output.mkdir(parents=True)
    run_dir = Path('/work/runs') / run_id
    run_dir.mkdir(parents=True)
    import pwd
    user = pwd.getpwnam('ubuntu')
    for path in (run_dir.parent, run_dir):
        os.chown(path, user.pw_uid, user.pw_gid)
    values = environment()
    unit = scaffold.service if suite == 'run' else 'ciab-command-' + run_id.lower()
    interrupted = False

    def stop(signum, frame):
        nonlocal interrupted
        interrupted = True
        subprocess.run(['systemctl', 'stop', unit], check=False, capture_output=True)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    data.update(started_at=datetime.now(timezone.utc).isoformat(timespec='microseconds'), status='running',
                artifacts=scaffold.artifacts if suite in ('run', 'snapshot') else str(run_dir),
                state_dir=scaffold.state, coverage='Caller owns scenarios, assertions and acceptance interpretation.',
                gaps=['Local fixtures do not establish vendor OAuth, delivery, AWS IAM or real GPU behavior.',
                      'OrbStack shares its Linux kernel; this does not validate EC2 or cloud resource provisioning.'])
    (output / 'report.json').write_text(json.dumps(data, indent=2))
    started = time.monotonic()
    raw = output / 'output.raw'
    code = 2
    try:
        if suite == 'snapshot':
            with raw.open('w') as stream:
                subprocess.run(['journalctl', '--no-pager', '-o', 'cat', '-u', scaffold.service,
                                '--since', data['argv'][0]], stdout=stream, stderr=subprocess.STDOUT, check=True)
            code = 0
        elif suite == 'run':
            data['command'] = ['systemctl', 'start', scaffold.service]
            subprocess.run(['systemctl', 'reset-failed', unit], check=False, capture_output=True)
            subprocess.run(data['command'], check=True)
            invocation = service_state(unit)['InvocationID']
            while True:
                status = service_state(unit)
                if interrupted:
                    code = 130
                    break
                if time.monotonic() - started >= data['timeout']:
                    subprocess.run(['systemctl', 'stop', unit], check=True)
                    code = 124
                    break
                if status['ActiveState'] in ('inactive', 'failed'):
                    code = int(status['ExecMainStatus'])
                    if status['Result'] != 'success' and not code:
                        code = 1
                    break
                time.sleep(0.5)
            data['service'] = service_state(unit)
            data['invocation_id'] = invocation
            with raw.open('w') as stream:
                subprocess.run(['journalctl', '--no-pager', '-o', 'cat', '-u', unit,
                                '--since', data['started_at']], stdout=stream, stderr=subprocess.STDOUT, check=True)
        else:
            command = scaffold.command(suite, data['argv'])
            data['command'] = command
            with raw.open('w') as stream:
                process = subprocess.Popen(['systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--unit', unit,
                                            '--uid=ubuntu', '--working-directory=/work',
                                            '--property=EnvironmentFile=/etc/crux-run.env',
                                            '--property=EnvironmentFile=/etc/ciab-run.env',
                                            '--property=TimeoutStopSec=10', '--setenv=CIAB_RUN_DIR=' + str(run_dir),
                                            '/usr/bin/env', '--', *command], stdout=stream, stderr=subprocess.STDOUT)
                try:
                    code = process.wait(timeout=data['timeout'])
                    if interrupted:
                        code = 130
                except subprocess.TimeoutExpired:
                    subprocess.run(['systemctl', 'stop', unit], check=False)
                    process.wait(timeout=20)
                    code = 124
    except Exception as error:
        with raw.open('a') as stream:
            stream.write(f'\n{type(error).__name__}: {error}\n')
        subprocess.run(['systemctl', 'stop', unit], check=False, capture_output=True)
    finally:
        if code and (not raw.exists() or not raw.stat().st_size):
            with raw.open('w') as stream:
                subprocess.run(['journalctl', '--no-pager', '-o', 'cat', '-u', unit,
                                '--since', data['started_at']], stdout=stream, stderr=subprocess.STDOUT, check=False)
        clean = scrub(raw.read_text(errors='replace') if raw.exists() else '', values)
        (output / 'output.log').write_text(clean)
        raw.unlink(missing_ok=True)
        data.update(status='succeeded' if code == 0 else 'failed', exit_code=code,
                    elapsed_seconds=round(time.monotonic() - started, 2))
        directory = Path(data['artifacts'])
        data['files'] = [{'path': str(p.relative_to(directory)), 'bytes': p.stat().st_size,
                          'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in directory.rglob('*') if p.is_file() and not p.is_symlink()
                         and not any(part in ('.git', '.codex', '.claude', '.mcp.json', '.aws', '.ssh', '__pycache__')
                                     or part.startswith('.env') for part in p.relative_to(directory).parts)]
        (output / 'report.json').write_text(scrub(json.dumps(data, indent=2), values) + '\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
