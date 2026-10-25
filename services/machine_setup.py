"""Install the selected production scaffold and local service connections."""
import json
import os
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path


def run(argv, **kwargs):
    subprocess.run(argv, check=True, **kwargs)


def replace_tree(source, destination, preserve=()):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.name not in preserve:
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=lambda path, names: list(preserve) if Path(path) == Path(source) else [])


def main():
    os.umask(0o022)
    settings = json.loads(Path('/tmp/machine-settings.json').read_text())
    staging = Path('/opt/ciab-staging')
    sys.path.insert(0, str(staging / 'devenv'))
    from ciab_devenv.scaffolds import get_scaffold
    scaffold = get_scaffold(settings.get('scaffold', 'sdk'), settings.get('platform'))
    adapter = import_module('services.' + scaffold.name + '_setup')
    run(['apt-get', 'update', '-qq'])
    run(['apt-get', 'install', '-y', '-qq', 'ca-certificates', 'curl', 'python3', 'jq', 'unzip', 'shellcheck'])
    shutil.copy2(staging / 'local.crt', '/usr/local/share/ca-certificates/ciab-local.crt')
    Path('/usr/local/share/ca-certificates/ciab-local.crt').chmod(0o644)
    run(['update-ca-certificates'])
    trust = Path('/etc/systemd/system.conf.d/ciab-local-trust.conf')
    trust.parent.mkdir(parents=True, exist_ok=True)
    trust.write_text('[Manager]\nDefaultEnvironment=CODEX_CA_CERTIFICATE=/usr/local/share/ca-certificates/ciab-local.crt SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt\n')
    run(['systemctl', 'daemon-reexec'])
    replace_tree(staging / 'source', '/source')
    replace_tree(staging / 'devenv', '/devenv')
    run(['chmod', '-R', 'a+rX,go-w', '/source', '/devenv'])
    source = Path('/source/src/ec2-workspaces')
    Path('/usr/local/lib/crux').mkdir(parents=True, exist_ok=True)
    for name in ('run_provision.py', 'run_service_auth.py'):
        if (source / name).is_file():
            shutil.copy2(source / name, Path('/usr/local/lib/crux') / name)
    shutil.copy2(source / ('scaffolds/' + scaffold.name + '.sh'), source / 'scaffold.sh')
    adapter.prepare(settings)
    if settings['has_manifest']:
        shutil.copy2(staging / 'input/provision.json', '/etc/crux-provision.json')
        Path('/etc/crux-provision.json').chmod(0o644)
    else:
        Path('/etc/crux-provision.json').unlink(missing_ok=True)
    environment = dict(os.environ, AGENT_PLATFORM=scaffold.platform, DEBIAN_FRONTEND='noninteractive')
    environment.update(adapter.settings_environment(settings))
    run(['bash', str(source / 'install-run.sh')], env=environment)
    adapter.installed(scaffold)
    run(['/home/ubuntu/.local/bin/uv', 'pip', 'install', '--python', scaffold.python,
         'pytest==8.4.2', 'ruff==0.14.1'])
    drop = Path('/srv/crux-run/run-harness')
    preserve = ('workspace',) if (drop / 'workspace').exists() else ()
    replace_tree(staging / 'input/drop-in', drop, preserve=preserve)
    (drop / 'workspace').mkdir(exist_ok=True)
    Path('/srv/crux-run/state').mkdir(exist_ok=True)
    Path('/work').mkdir(exist_ok=True)
    run(['chown', '-R', 'ubuntu:ubuntu', '/srv/crux-run', '/work'])
    aws = Path('/root/.aws')
    aws.mkdir(mode=0o700, exist_ok=True)
    (aws / 'config').write_text('[profile ciab-local]\nregion=us-east-1\n')
    (aws / 'credentials').write_text('[ciab-local]\naws_access_key_id=CIABLOCAL\naws_secret_access_key=ciab-local-only\n')
    (aws / 'credentials').chmod(0o600)
    environment.update(AWS_PROFILE='ciab-local', AWS_REGION='us-east-1', AWS_EC2_METADATA_DISABLED='true',
                       AWS_ENDPOINT_URL='https://fixtures.test', AWS_ENDPOINT_URL_SSM='https://fixtures.test',
                       AWS_CA_BUNDLE='/etc/ssl/certs/ca-certificates.crt',
                       RUN_SECRETS_PATH='/tmp/machine-secrets.json', SYSTEM_SSM_PARAM='/crux/local/system/env',
                       RUN_SLUG=settings['run_slug'])
    environment.update(adapter.settings_environment(settings))
    run(['bash', str(source / 'configure-run.sh')], env=environment)
    adapter.configured(scaffold)
    values = settings['environment']
    values.update(CODEX_CA_CERTIFICATE='/usr/local/share/ca-certificates/ciab-local.crt',
                  PATH=str(Path(scaffold.python).parent) + ':/opt/crux-run-tools/bin:/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin',
                  PYTHONPATH=scaffold.pythonpath, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
                  NODE_EXTRA_CA_CERTS='/etc/ssl/certs/ca-certificates.crt',
                  SSL_CERT_FILE='/etc/ssl/certs/ca-certificates.crt', REQUESTS_CA_BUNDLE='/etc/ssl/certs/ca-certificates.crt',
                  AWS_CA_BUNDLE='/etc/ssl/certs/ca-certificates.crt', AWS_PROFILE='ciab-local',
                  AWS_CONFIG_FILE='/home/ubuntu/.aws/config', AWS_SHARED_CREDENTIALS_FILE='/home/ubuntu/.aws/credentials',
                  AWS_EC2_METADATA_DISABLED='true', AWS_DEFAULT_REGION='us-east-1', AWS_ENDPOINT_URL='https://fixtures.test',
                  AWS_ENDPOINT_URL_S3='http://storage:9000')
    for service in ('STS', 'SSM', 'COST_EXPLORER', 'EC2'):
        values['AWS_ENDPOINT_URL_' + service] = 'https://fixtures.test'
    with os.fdopen(os.open('/etc/ciab-run.env', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(''.join(key + '=' + json.dumps(value) + '\n' for key, value in values.items()))
    with os.fdopen(os.open('/etc/ciab-redactions.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(settings['redactions'], stream)
    aws = Path('/home/ubuntu/.aws')
    aws.mkdir(mode=0o700, exist_ok=True)
    (aws / 'config').write_text('[profile ciab-local]\nregion=us-east-1\n[profile ciab-storage]\nregion=us-east-1\ns3 =\n    addressing_style = path\n')
    (aws / 'credentials').write_text('[ciab-local]\naws_access_key_id=CIABLOCAL\naws_secret_access_key=local-fixture-only\n'
                                   '[ciab-storage]\naws_access_key_id=ciab\naws_secret_access_key=' + values['CIAB_STORAGE_PASSWORD'] + '\n')
    (aws / 'credentials').chmod(0o600)
    run(['chown', '-R', 'ubuntu:ubuntu', str(aws)])
    override = Path('/etc/systemd/system') / (scaffold.service + '.service.d/ciab.conf')
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text('[Service]\nEnvironmentFile=/etc/ciab-run.env\n')
    run(['systemctl', 'daemon-reload'])
    print('Production installation, sandbox/model probes and service configuration completed. Use devctl run to start CRUX.')


if __name__ == '__main__':
    main()
