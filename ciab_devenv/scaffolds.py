"""Execution contracts shared by host orchestration and machine adapters."""
from dataclasses import dataclass, replace
from devops.source import required_path

from .config import DevError, source_info


@dataclass(frozen=True)
class Scaffold:
    name: str
    platform: str
    service: str
    python: str
    pythonpath: str
    artifacts: str
    state: str
    required_files: tuple[str, ...]

    def validate_source(self, source):
        files = self.required_files
        manifest = source / 'scaffolds' / self.platform / 'package.json'
        if self.name == 'acp' and manifest.is_file():
            files = tuple(name for name in files if not name.endswith('placeholders-base.txt.example'))
        missing = [name for name in files if not required_path(source, name).is_file()]
        if missing:
            raise DevError(f'Selected source lacks {self.name.upper()} provisioning: ' + ', '.join(missing))
        source_info(source)

    def command(self, suite, argv=()):
        if suite in ('services', 'fixture'):
            return [self.python, '/devenv/services/check_services.py', suite, *argv]
        if suite == 'exec':
            return list(argv)
        if self.name == 'acp':
            if suite == 'check':
                return [self.python, '-c',
                        'import subprocess; state = subprocess.check_output(["systemctl", "show", '
                        '"--property=LoadState", "--value", "crux-acp-gateway"], text=True).strip(); '
                        'assert state == "loaded", state; print("PASS production ACP service installed")']
            raise DevError('ACP probes and runs require AgentRQ task execution.')
        if suite == 'probe':
            return [self.python, '-m', 'crux_scaffold', 'probe', '--coding-agent', 'codex']
        if suite == 'check':
            return [self.python, '-m', 'crux_scaffold', 'check', '--drop-in',
                    '/srv/crux-run/run-harness', '--state-dir', self.state]
        raise DevError('Unsupported machine operation: ' + suite)


SDK = Scaffold('sdk', 'openai-agents', 'crux-sdk-run', '/opt/crux-sdk-scaffold/.venv/bin/python',
               '/opt/crux-sdk-scaffold:/devenv', '/srv/crux-run/run-harness/workspace', '/srv/crux-run/state',
               ('src/ec2-workspaces/install-run.sh', 'src/ec2-workspaces/configure-run.sh',
                'src/ec2-workspaces/scaffolds/sdk.sh', 'src/sdk-scaffold/requirements.txt'))


ACP = Scaffold('acp', 'codex', 'crux-acp-gateway', '/opt/ciab-tools/.venv/bin/python', '/devenv',
               '/srv/crux-run', '/srv/crux-run/state',
               ('src/ec2-workspaces/install-run.sh', 'src/ec2-workspaces/configure-run.sh',
                'src/ec2-workspaces/scaffolds/acp.sh', 'src/ec2-workspaces/agent-config.sh',
                'src/ec2-control/configure-control.sh', 'src/ec2-workspaces/placeholders-base.txt.example'))


def get_scaffold(name='sdk', platform=None):

    if name == 'sdk' and platform in (None, 'openai-agents'):
        return SDK
    if name == 'acp' and platform in (None, 'codex', 'claude'):
        extra = ('agentrq/claude/.claude/hooks/langfuse_hook.py',) if platform == 'claude' else (
            'src/ec2-workspaces/codex-flush-turns.py', 'src/ec2-workspaces/codex-live-trace.py',
            'src/ec2-workspaces/live_trace/__init__.py')
        return replace(ACP, platform=platform or 'codex', required_files=ACP.required_files + extra)
    raise DevError('Unsupported scaffold: ' + str(name))
