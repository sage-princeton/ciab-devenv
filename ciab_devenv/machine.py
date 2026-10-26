from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time

from .config import ROOT, DevError, private_write, source_info, stage_directory

from .scaffolds import SDK, get_scaffold

PROVISION_FILES = SDK.required_files


def validate_source(source, scaffold='sdk'):
    get_scaffold(scaffold).validate_source(source)


def scrub(text, values):
    import re
    for key, value in values.items():
        if isinstance(value, str) and len(value) > 6 and any(s in key.upper() for s in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
            text = text.replace(value, '[REDACTED]')
    return re.sub(r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}', '[REDACTED]', text)


def secret_values(value):
    if isinstance(value, dict):
        return [text for child in value.values() for text in secret_values(child)]
    if isinstance(value, list):
        return [text for child in value for text in secret_values(child)]
    return [value] if isinstance(value, str) and len(value) > 6 else []


def show_report(instance, run_id='latest', output=None):
    reports = instance.root / 'reports'
    if run_id == 'latest':
        found = list(reports.glob('*/report.json'))
        if not found:
            raise DevError('No reports yet.')
        path = max(found, key=lambda item: item.stat().st_mtime_ns)
    else:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise DevError('Invalid report ID')
        path = reports / run_id / 'report.json'
    print(path.read_text())
    if output:
        shutil.copytree(path.parent, output, dirs_exist_ok=True)
    return 0


class Machine:
    def __init__(self, instance):
        self.instance = instance
        self.name = instance.project + '-run'
        self.receipt = instance.root / 'provisioned.json'

    def call(self, *args, capture=False, check=True):
        return subprocess.run(['orb', 'run', '--machine', self.name, '--user', 'root', '--workdir', '/tmp',
                               *map(str, args)], check=check, capture_output=capture, text=True)

    def state(self):
        machines = json.loads(subprocess.check_output(['orb', 'list', '--format', 'json'], text=True))
        return next((m for m in machines if m['name'] == self.name), None)

    def ensure(self):
        state = self.state()
        if state is None:
            subprocess.run(['orb', 'create', '--isolated', '--user', 'ubuntu', '--memory', '4G', '--cpus', '2',
                            'ubuntu:24.04', self.name], check=True)
        elif not state['config']['isolated']:
            raise DevError(f'{self.name} is not isolated; refusing to use it.')
        elif state['state'] != 'running':
            subprocess.run(['orb', 'start', self.name], check=True)

    def require_running(self):
        state = self.state()
        if not state or state['state'] != 'running':
            raise DevError('The Ubuntu machine is stopped or absent. Run bootstrap, or up for an existing instance.')
        if not state['config']['isolated']:
            raise DevError('The Ubuntu machine must be isolated.')

    def require_idle(self):
        state = self.state()
        if state and state['state'] == 'running':
            result = self.call('systemctl', 'is-active', self.instance.scaffold.service, capture=True, check=False)
            if result.stdout.strip() in ('active', 'activating', 'deactivating'):
                raise DevError(f'{self.instance.scaffold.service} is active. Wait for the current run or use down to stop it.')

    def require_provisioned(self):
        self.require_running()
        if not self.receipt.exists():
            raise DevError('Provision this machine with a caller-supplied --drop-in first.')
        receipt = json.loads(self.receipt.read_text())
        receipt_platform = receipt.get('platform', 'openai-agents' if receipt.get('scaffold', 'sdk') == 'sdk' else 'codex')
        if (receipt.get('scaffold', 'sdk'), receipt_platform) != (self.instance.scaffold.name, self.instance.scaffold.platform):
            raise DevError('Selected scaffold changed since provisioning. Reprovision before testing.')
        if receipt['source'] != source_info(self.instance.source):
            raise DevError('Selected source changed since provisioning. Run provision --drop-in PATH before testing.')
        return receipt

    def push(self, file, target):
        subprocess.run(['orb', 'push', '--machine', self.name, str(file)], check=True, capture_output=True)
        self.call('install', '-m', '600', '/home/ubuntu/' + file.name, target)
        self.call('rm', '-f', '/home/ubuntu/' + file.name)

    def network(self):
        env = self.instance.compose_env()
        addresses = {}
        for service in ('edge', 'storage'):
            addresses[service] = subprocess.check_output(
                ['docker', '--context', 'orbstack', 'inspect', self.instance.project + '-' + service + '-1',
                 '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'], text=True).strip()
            if not addresses[service]:
                raise DevError('Start local service containers before using the machine.')
        hosts = self.instance.root / 'machine-hosts.json'
        private_write(hosts, json.dumps({'edge': addresses['edge'], 'storage': addresses['storage'],
                                        'runpod': env['CIAB_RUNPOD_HOST']}))
        self.push(hosts, '/tmp/ciab-hosts.json')
        self.call('python3', '-c', '''import json
from pathlib import Path
v=json.loads(Path('/tmp/ciab-hosts.json').read_text())
p=Path('/etc/hosts')
lines=[s for s in p.read_text().splitlines() if '# ciab-services' not in s]
lines += [v['edge']+' langfuse.test cost.test fixtures.test agentrq.test '+v['runpod']+' # ciab-services', v['storage']+' storage # ciab-services']
p.write_text('\\n'.join(lines)+'\\n')
''')

    def run_units(self):
        units = [self.instance.scaffold.service]
        if self.instance.scaffold.name == 'acp' and self.instance.scaffold.platform == 'codex':
            result = self.call('systemctl', 'show', '--property=LoadState', '--value', 'crux-codex-live-trace',
                               capture=True, check=False)
            if result.stdout.strip() == 'loaded':
                units.append('crux-codex-live-trace')
        return units

    def stop_run(self):
        self.call('systemctl', 'stop', *self.run_units(), capture=True, check=False)
        for unit in self.run_units():
            result = self.call('systemctl', 'is-active', unit, capture=True, check=False)
            if result.stdout.strip() not in ('inactive', 'failed', 'unknown'):
                self.stop()
                raise DevError('Run service did not stop; stopped the isolated machine instead.')

    def stop(self):
        state = self.state()
        if state and state['state'] == 'running':
            try:
                self.call('systemctl', 'stop', *self.run_units(), 'ciab-job-*.service', 'ciab-command-*.service', check=False)
            finally:
                subprocess.run(['orb', 'stop', self.name], check=True)

    def delete(self):
        if self.state():
            subprocess.run(['orb', 'delete', '--force', self.name], check=True)
        self.receipt.unlink(missing_ok=True)

    def provision(self, args):
        from .cli import compose
        self.instance.scaffold.validate_source(self.instance.source)
        scaffold = self.instance.scaffold
        provider = self.instance.data.get('provider', 'direct')
        key = 'OPENROUTER_API_KEY' if provider == 'openrouter' else ('ANTHROPIC_API_KEY' if scaffold.platform == 'claude' else 'OPENAI_API_KEY')
        values = json.loads(args.secrets_json.read_text()) if args.secrets_json else {}
        if os.environ.get(key):
            values.setdefault(key, os.environ[key])
        if not values.get(key):
            raise DevError(f'Production provisioning requires {key} from direnv or --secrets-json for its live probes.')
        if (scaffold.platform == 'claude' or provider == 'openrouter') and not os.environ.get('CRUX_MODEL'):
            raise DevError('Set CRUX_MODEL explicitly for Claude Code or OpenRouter.')
        if scaffold.name == 'sdk' and not args.drop_in:
            raise DevError('SDK provisioning requires --drop-in PATH.')
        runtime_pins = {}
        if scaffold.name == 'acp':
            from .agentrq import pins
            runtime_pins = pins(self.instance.source)
        self.require_idle()
        self.receipt.unlink(missing_ok=True)
        source_revision = source_info(self.instance.source)
        self.instance.stage_source()
        if source_revision != source_info(self.instance.source):
            raise DevError('Source changed while staging. Retry provisioning after edits finish.')
        staging = self.instance.root / 'machine-input'
        shutil.rmtree(staging, ignore_errors=True)
        if args.drop_in:
            stage_directory(args.drop_in, staging / 'drop-in')
        else:
            (staging / 'drop-in/workspace').mkdir(parents=True)
        if args.manifest:
            shutil.copyfile(args.manifest, staging / 'provision.json')
        inputs = {'drop_in': str(args.drop_in.resolve()) if args.drop_in else None, 'manifest': str(args.manifest.resolve()) if args.manifest else None,
                  'files': [{'path': str(file.relative_to(staging)), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
                            for file in sorted(staging.rglob('*')) if file.is_file()]}
        from devops.resources import lifecycle
        resources = lifecycle(self.instance, self)
        if resources is not None:
            resources.check()
        renewed_certificates = self.instance.certificates()
        if renewed_certificates:
            compose(self.instance, 'stop', 'edge')
        if scaffold.name == 'acp':
            from .agentrq import prepare_image
            prepare_image(self.instance, runtime_pins)
        if resources is not None:
            resources.apply()
        else:
            result = compose(self.instance, 'up', '-d', '--wait', '--wait-timeout', '300')
            if result:
                return result
        if scaffold.name == 'acp':
            from .agentrq import Client
            for attempt in range(30):
                try:
                    values.update(Client(self.instance).bootstrap())
                    break
                except (DevError, OSError):
                    if attempt == 29:
                        raise
                    time.sleep(1)
        if resources is None:
            self.ensure()
        self.network()
        devenv_revision = source_info(ROOT)
        archive = self.instance.root / 'machine-source.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            output.add(self.instance.root / 'source', arcname='source')
            output.add(staging, arcname='input')
            for name in ('services', 'devops', 'monitoring', 'ciab_devenv', 'verification', 'tests'):
                output.add(ROOT / name, arcname='devenv/' + name,
                           filter=lambda member: None if '__pycache__' in member.name else member)
            output.add(self.instance.root / 'certs/ca.crt', arcname='local.crt')
        secret = self.instance.root / 'machine-secrets.json'
        settings_file = self.instance.root / 'machine-settings.json'
        private_write(secret, json.dumps(values))
        env = self.instance.compose_env()
        local = {key: env[key] for key in ('CRUX_MODEL', 'CRUX_REASONING_EFFORT', 'COST_TRACKER_URL', 'COST_TRACKER_TOKEN',
                                         'RUNPOD_API_KEY', 'CIAB_FIXTURE_TOKEN', 'LANGFUSE_BASE_URL', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY')}
        local.update(CIAB_FIXTURE_URL='https://fixtures.test', CIAB_STORAGE_PASSWORD=env['CIAB_PASSWORD'])
        settings = {'scaffold': scaffold.name, 'platform': scaffold.platform, 'provider': provider, 'pins': runtime_pins, 'model': env['CRUX_MODEL'], 'effort': env['CRUX_REASONING_EFFORT'], 'run_slug': self.instance.project,
                    'has_manifest': bool(args.manifest), 'environment': local, 'redactions': secret_values({k: v for k, v in values.items() if k != 'AGENTRQ_WORKSPACE_ID'})}
        private_write(settings_file, json.dumps(settings))
        private_write(self.instance.root / 'redactions.json', json.dumps(settings['redactions']))
        run_id = new_id()
        report_dir = self.instance.root / 'reports' / run_id
        report_dir.mkdir(parents=True, mode=0o700)
        started = time.monotonic()
        code = 2
        try:
            for file in (archive, secret, settings_file):
                self.push(file, '/tmp/' + file.name)
            self.call('rm', '-rf', '/opt/ciab-staging')
            self.call('mkdir', '-p', '/opt/ciab-staging')
            self.call('tar', '-xzf', '/tmp/machine-source.tar.gz', '-C', '/opt/ciab-staging')
            raw = report_dir / 'output.raw'
            with raw.open('w') as stream:
                process = subprocess.Popen(['orb', 'run', '--machine', self.name, '--user', 'root', '--workdir', '/tmp',
                                            'python3', '/opt/ciab-staging/devenv/devops/machine_setup.py'],
                                           stdout=stream, stderr=subprocess.STDOUT)
                print(f'Provisioning {self.name}; log: {raw} (private). Production probes call the model provider.', flush=True)
                try:
                    code = process.wait(timeout=1800)
                except (KeyboardInterrupt, subprocess.TimeoutExpired):
                    self.stop()
                    process.wait(timeout=30)
                    code = 124
            redactions = {f'SECRET_{i}': value for i, value in enumerate(settings['redactions'])}
            clean = scrub(raw.read_text(errors='replace'), dict(self.instance.process_env(), **redactions))
            private_write(report_dir / 'output.log', clean)
            raw.unlink()
            print(clean[-12000:])
            receipt = {'source': source_revision, 'scaffold': scaffold.name, 'platform': scaffold.platform, 'provider': provider, 'pins': runtime_pins,
                       'workspace_id': self.instance.data.get('agentrq_workspace_id'),
                       'controller_image': self.instance.data.get('agentrq_image'), 'model': settings['model'], 'effort': settings['effort'],
                       'run_slug': settings['run_slug'], 'drop_in': str(args.drop_in.resolve()) if args.drop_in else None,
                       'provisioned_devenv': devenv_revision, 'provisioning_inputs': inputs,
                       'services': {k: env[k] for k in ('LANGFUSE_BASE_URL', 'COST_TRACKER_URL', 'CIAB_RUNPOD_HOST')}}
            report = dict(receipt, run_id=run_id, suite='provision', exit_code=code,
                          status='succeeded' if code == 0 else 'failed', elapsed_seconds=round(time.monotonic()-started, 2),
                          devenv=source_info(ROOT), machine=self.name)
            private_write(report_dir / 'report.json', json.dumps(report, indent=2) + '\n')
            if code == 0:
                versions = self.call('cat', '/etc/ciab-versions.json', capture=True)
                receipt['versions'] = json.loads(versions.stdout)
                report['versions'] = receipt['versions']
                private_write(report_dir / 'report.json', json.dumps(report, indent=2) + '\n')
                private_write(self.receipt, json.dumps(receipt, indent=2))
            print(f'Evidence: {report_dir}/report.json')
            return code
        finally:
            secret.unlink(missing_ok=True)
            settings_file.unlink(missing_ok=True)
            state = self.state()
            if state and state['state'] == 'running':
                self.call('rm', '-f', '/tmp/machine-secrets.json', '/tmp/machine-settings.json', '/tmp/machine-source.tar.gz', check=False)

    def job(self, suite, argv=(), timeout=900, input_path=None):
        receipt = self.require_provisioned()
        if suite not in ('fixture', 'snapshot'):
            self.require_idle()
        run_id = new_id()
        inputs = None
        if input_path:
            staging = self.instance.root / 'inputs' / run_id
            stage_directory(input_path, staging)
            inputs = {'path': str(input_path.resolve()), 'files': [
                {'path': str(p.relative_to(staging)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(staging.rglob('*')) if p.is_file()]}
            archive = self.instance.root / 'input.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                output.add(staging, arcname='input')
            self.push(archive, '/tmp/ciab-input.tar.gz')
            self.call('rm', '-rf', '/input')
            self.call('tar', '-xzf', '/tmp/ciab-input.tar.gz', '-C', '/', '--no-same-owner')
            self.call('chmod', '-R', 'a+rX,go-w', '/input')
        job = dict(receipt, run_id=run_id, suite=suite, argv=list(argv), timeout=timeout, inputs=inputs,
                   devenv=source_info(ROOT), machine=self.name)
        request = self.instance.root / ('job-' + run_id + '.json')
        private_write(request, json.dumps(job))
        remote = '/tmp/' + request.name
        self.push(request, remote)
        unit = 'ciab-job-' + run_id.lower()
        command = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--unit', unit,
                   '--property=TimeoutStopSec=30', '--property=KillMode=mixed',
                   '/usr/bin/python3', '/devenv/monitoring/machine_job.py', remote]
        try:
            result = self.call(*command, check=False)
            code = result.returncode
        except KeyboardInterrupt:
            self.call('systemctl', 'stop', unit, check=False)
            code = 130
        finally:
            request.unlink(missing_ok=True)
        destination = self.instance.root / 'reports' / run_id
        for name in ('report.json', 'output.log'):
            result = self.call('cat', f'/var/lib/ciab/reports/{run_id}/{name}', capture=True, check=False)
            if result.returncode:
                raise DevError(f'Could not collect {run_id}; inspect {self.name} /var/lib/ciab/reports.')
            private_write(destination / name, result.stdout)
        print((destination / 'output.log').read_text())
        self.last_report = destination
        report = json.loads((destination / 'report.json').read_text())
        print(f'Evidence: {destination}/report.json; status={report["status"]}')
        return report.get('exit_code', code)


def new_id():
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + os.urandom(3).hex()
