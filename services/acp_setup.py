"""Stage the selected vendor scaffold and reuse its production provisioning."""
import shutil
from pathlib import Path

from services.machine_setup import run


def prepare(settings):
    if settings['platform'] == 'claude':
        shutil.copy2('/source/agentrq/claude/.claude/hooks/langfuse_hook.py',
                     '/source/src/ec2-workspaces/langfuse_hook.py')


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
