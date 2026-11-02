"""Local resource drivers for the selected production lifecycle implementation."""
import json
import os
import subprocess

from ciab_devenv.config import DEFAULT_MODEL, DevError, private_write
from devops.production import contracts


class Services:
    """Reconcile the named Compose project using stable live ownership labels."""
    def __init__(self, instance):
        """Bind the selected environment and its deterministic resource names.

        :param instance: Named local environment.
        """
        self.instance = instance

    def observe(self, resource, context):
        """Read project labels, rejecting foreign resources; return outputs if present.

        :param resource: Local services declaration.
        :param context: Stable production lifecycle ownership context.
        :returns: Compose project identity, or None if no project resources exist.
        """
        labels = subprocess.check_output([
            'docker', '--context', 'orbstack', 'ps', '-a', '--filter',
            'label=com.docker.compose.project=' + self.instance.project,
            '--format', '{{.Label "io.crux.owner"}}'], text=True).splitlines()
        if any(label != context.owner for label in labels):
            raise DevError('Existing service containers have a different owner; use a fresh name.')
        found = bool(labels)
        for kind, output in [('volume', '{{.Name}}'), ('network', '{{.ID}}')]:
            identifiers = subprocess.check_output([
                'docker', '--context', 'orbstack', kind, 'ls', '--filter',
                'label=com.docker.compose.project=' + self.instance.project,
                '--format', output], text=True).splitlines()
            if identifiers:
                owners = subprocess.check_output([
                    'docker', '--context', 'orbstack', kind, 'inspect',
                    '--format', '{{index .Labels "io.crux.owner"}}', *identifiers], text=True).splitlines()
                if any(owner != context.owner for owner in owners):
                    raise DevError('Existing service ' + kind + 's have a different owner.')
                found = True
        return {'project': self.instance.project} if found else None

    def preflight(self, resource, context):
        """Validate live Compose labels before creating or removing services.

        :param resource: Local services declaration.
        :param context: Stable production lifecycle ownership context.
        """
        self.observe(resource, context)

    def ensure(self, resource, previous, dependencies, context):
        """Reconcile the labeled Compose project and return its live project identity.

        :param resource: Resource for this operation.
        :param previous: Previous for this operation.
        :param dependencies: Dependencies for this operation.
        :param context: Context for this operation.
        """
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

    def destroy(self, resource, observed, context):
        """Remove the owned Compose project, including its volumes and networks.

        :param resource: Local services declaration.
        :param observed: Freshly observed project identity.
        :param context: Stable production lifecycle ownership context.
        """
        from ciab_devenv.cli import compose
        self.preflight(resource, context)
        if compose(self.instance, 'down', '--volumes', '--remove-orphans'):
            raise DevError('Service cleanup failed; retry reset with the same environment name.')


class Box:
    """Reconcile the reserved isolated OrbStack machine by its environment name."""
    def __init__(self, machine):
        """Bind the selected environment and its deterministic resource names.

        :param machine: Machine for this operation.
        """
        self.machine = machine

    def observe(self, resource, context):
        """Read the reserved ciab-NAME-run Box directly from OrbStack.

        :param resource: Local Box declaration.
        :param context: Production lifecycle context.
        :returns: Current machine name/ID, or None if absent.
        """
        state = self.machine.state()
        if not state:
            return None
        if not state['config']['isolated']:
            raise DevError('Local Box is not isolated.')
        return {'machine': self.machine.name, 'id': state['id']}

    def preflight(self, resource, context):
        """Reject a non-isolated machine in the reserved environment namespace.

        :param resource: Local Box declaration.
        :param context: Production lifecycle context.
        """
        self.observe(resource, context)

    def ensure(self, resource, previous, dependencies, context):
        """Create or start the isolated named Box; return its live identity.

        :param resource: Local Box declaration.
        :param previous: Fresh observed outputs.
        :param dependencies: Observed prerequisite service outputs.
        :param context: Production lifecycle context.
        """
        self.preflight(resource, context)
        self.machine.ensure()
        return self.observe(resource, context)

    def destroy(self, resource, observed, context):
        """Delete only the selected named isolated machine without waking it.

        :param resource: Local Box declaration.
        :param observed: Fresh observed machine identity.
        :param context: Production lifecycle context.
        """
        self.preflight(resource, context)
        self.machine.delete()


def lifecycle(instance, machine):
    """Use the selected source's stateless lifecycle for local named resources.

    :param instance: Selected environment and production worktree.
    :param machine: Isolated Box adapter.
    :returns: Production Lifecycle, or None for sources before that interface.
    """
    production = contracts(instance.source)
    if production is None or not hasattr(production, 'Lifecycle'):
        return None
    run = production.Run.parse({
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
    })
    return production.Lifecycle(run, {'local.services': Services(instance), 'local.box': Box(machine)})
