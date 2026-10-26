"""Local resource drivers for the selected production lifecycle implementation."""
import json
import os
import subprocess
from dataclasses import asdict

from ciab_devenv.config import DEFAULT_MODEL, DevError, private_write
from devops.production import contracts


class Services:
    def __init__(self, instance):
        self.instance = instance

    def preflight(self, resource, context):
        labels = subprocess.check_output([
            'docker', '--context', 'orbstack', 'ps', '-a', '--filter',
            'label=com.docker.compose.project=' + self.instance.project,
            '--format', '{{.Label "io.crux.owner"}}'], text=True).splitlines()
        if any(label != context.owner for label in labels):
            raise DevError('Existing service containers do not belong to this deployment receipt; use a fresh name.')
        volumes = subprocess.check_output([
            'docker', '--context', 'orbstack', 'volume', 'ls', '--filter',
            'label=com.docker.compose.project=' + self.instance.project, '--format', '{{.Name}}'], text=True).splitlines()
        if volumes:
            owners = subprocess.check_output([
                'docker', '--context', 'orbstack', 'volume', 'inspect',
                '--format', '{{index .Labels "io.crux.owner"}}', *volumes], text=True).splitlines()
            if any(owner != context.owner for owner in owners):
                raise DevError('Existing service volumes do not belong to this deployment receipt.')

    def ensure(self, resource, previous, dependencies, context):
        from ciab_devenv.cli import compose
        self.preflight(resource, context)
        configuration = json.loads(subprocess.check_output([
            'docker', '--context', 'orbstack', 'compose',
            *[arg for path in self.instance.compose_files() for arg in ('--file', str(path))],
            'config', '--format', 'json'], env=self.instance.process_env(), text=True))
        override = {kind: {name: {'labels': {'io.crux.owner': context.owner}}
                           for name, value in configuration.get(kind, {}).items() if not value.get('external')}
                    for kind in ('services', 'volumes', 'networks')}
        private_write(self.instance.root / 'compose.ownership.json', json.dumps(override))
        if compose(self.instance, 'up', '-d', '--wait', '--wait-timeout', '300'):
            raise DevError('Service startup failed; inspect reports, retry or reset this named environment.')
        return {'project': self.instance.project}

    def destroy(self, resource, receipt, context):
        from ciab_devenv.cli import compose
        self.preflight(resource, context)
        if compose(self.instance, 'down', '--volumes', '--remove-orphans'):
            raise DevError('Service cleanup failed; retry reset with the same receipt.')


class Box:
    def __init__(self, machine):
        self.machine = machine

    def preflight(self, resource, context):
        state = self.machine.state()
        if state:
            if not state['config']['isolated']:
                raise DevError('Local Box is not isolated.')
            # OrbStack cannot read a stopped disk without starting it. The host
            # receipt also binds its immutable OrbStack machine ID.
            identity = self.machine.instance.root / 'box-identity.json'
            saved = json.loads(identity.read_text()) if identity.exists() else {}
            if saved != {'id': state['id'], 'owner': context.owner}:
                raise DevError('Existing OrbStack machine is not owned by this receipt; use a fresh name.')

    def ensure(self, resource, previous, dependencies, context):
        self.preflight(resource, context)
        self.machine.ensure()
        state = self.machine.state()
        private_write(self.machine.instance.root / 'box-identity.json',
                      json.dumps({'id': state['id'], 'owner': context.owner}))
        return {'machine': self.machine.name, 'id': state['id']}

    def destroy(self, resource, receipt, context):
        self.preflight(resource, context)
        self.machine.delete()


def lifecycle(instance, machine):
    production = contracts(instance.source)
    if production is None or not hasattr(production, 'Lifecycle'):
        if (instance.root / 'resources.json').exists():
            raise DevError('Reselect a source with deployment lifecycle support before operating on these resources.')
        return None
    specification = instance.root / 'resource-run.json'
    if not specification.exists():
        value = {
            'version': 1, 'name': instance.name, 'box': 'box',
            'scaffold': {'type': 'agentrq' if instance.scaffold.name == 'acp' else 'sdk',
                         'platform': instance.scaffold.platform, 'drop_in': 'run-harness',
                         'model': os.environ.get('CRUX_MODEL', DEFAULT_MODEL),
                         'effort': os.environ.get('CRUX_REASONING_EFFORT', 'low'),
                         'provider': instance.data.get('provider', 'direct')},
            'resources': [
                {'id': 'services', 'type': 'local.services', 'config': {'project': instance.project}},
                {'id': 'box', 'type': 'local.box', 'config': {'name': machine.name}, 'depends_on': ['services']},
            ],
        }
        run = production.Run.parse(value)
        private_write(specification, json.dumps(asdict(run)))
    run = production.Run.load(specification)
    return production.Lifecycle(run, instance.root / 'resources.json',
                                {'local.services': Services(instance), 'local.box': Box(machine)})
