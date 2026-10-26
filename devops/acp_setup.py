"""Stage the selected vendor scaffold and reuse its production provisioning."""
import shutil
from pathlib import Path

from devops.machine_setup import run
from devops.source import source_path


def prepare(settings):
    if settings['platform'] == 'codex':
        source = source_path('/source', 'codex_tracing')
        target = source_path('/source', 'workspace')
        if source != target:
            for name in ('codex-flush-turns.py', 'codex-live-trace.py'):
                shutil.copy2(source / name, target / name)
            shutil.copytree(source / 'live_trace', target / 'live_trace', dirs_exist_ok=True)
    if settings['platform'] == 'claude':
        shutil.copy2(source_path('/source', 'claude_tracing', 'langfuse_hook.py'),
                     source_path('/source', 'workspace', 'langfuse_hook.py'))


def installed(scaffold):
    run(['/home/ubuntu/.local/bin/uv', 'venv', '--allow-existing', '/opt/ciab-tools/.venv'])


def settings_environment(settings):
    platform = settings['platform']
    model_key, effort_key = ('CODEX_MODEL', 'CODEX_REASONING_EFFORT') if platform == 'codex' else ('CLAUDE_MODEL', 'CLAUDE_EFFORT')
    return dict(settings['pins'], AGENT_PLATFORM=platform, MODEL_PROVIDER=settings['provider'],
                CONTROL_MCP_BASE='https://agentrq.test', **{model_key: settings['model'], effort_key: settings['effort']})


def configured(scaffold):
    run(['systemctl', 'disable', '--now', scaffold.service])
    if Path('/etc/systemd/system/crux-codex-live-trace.service').exists():
        run(['systemctl', 'disable', '--now', 'crux-codex-live-trace'])
