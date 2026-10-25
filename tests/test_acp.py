import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ciab_devenv.acp import run_task
from ciab_devenv.config import DevError, Environment
from ciab_devenv.scaffolds import ACP, SDK, get_scaffold
from services.acp_setup import settings_environment


class ACPTests(unittest.TestCase):
    def test_platform_contracts_and_production_settings(self):
        for platform in ('codex', 'claude'):
            adapter = get_scaffold('acp', platform)
            self.assertEqual(adapter.platform, platform)
            self.assertNotIn('src/sdk-scaffold/requirements.txt', adapter.required_files)
            settings = settings_environment({'platform': platform, 'provider': 'direct', 'model': 'test-model',
                                             'effort': 'low', 'pins': {'ACP_GATEWAY_VERSION': 'pinned'}})
            self.assertEqual(settings['AGENT_PLATFORM'], platform)
            self.assertEqual(settings['CONTROL_MCP_BASE'], 'https://agentrq.test')
            self.assertEqual(settings['ACP_GATEWAY_VERSION'], 'pinned')
            self.assertEqual(settings['CODEX_MODEL' if platform == 'codex' else 'CLAUDE_MODEL'], 'test-model')
        with self.assertRaises(DevError):
            get_scaffold('sdk', 'claude')
        self.assertEqual(get_scaffold(), SDK)

    def test_task_status_controls_completion_and_stops_service(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CIAB_STATE_ROOT': tmp}):
            instance = Environment('unit')
            instance.data = {'scaffold': 'acp', 'platform': 'codex'}
            machine = MagicMock(instance=instance, name='test-machine')
            machine.name = 'ciab-unit-run'
            machine.job.return_value = 0
            machine.require_provisioned.return_value = {'scaffold': 'acp', 'platform': 'codex'}
            machine.call.return_value.stdout = 'active'
            client = MagicMock()
            client.tasks.return_value = []
            client.workspace.return_value = {'agentConnected': True}
            client.create.return_value = {'id': 'task1'}
            client.task.return_value = {'task': {'id': 'task1', 'status': 'completed'}}
            args = argparse.Namespace(command='probe', timeout=20)
            with patch('ciab_devenv.acp.Client', return_value=client), patch.object(instance, 'process_env', return_value={}):
                self.assertEqual(run_task(machine, args), 0)
            calls = [call.args for call in machine.call.call_args_list]
            self.assertIn(('systemctl', 'start', ACP.service), calls)
            self.assertIn(('systemctl', 'stop', ACP.service, 'crux-codex-live-trace'), calls)
            reports = list(Path(tmp).glob('unit/reports/*/report.json'))
            self.assertEqual(json.loads(reports[0].read_text())['task_id'], 'task1')
            machine.job.assert_called_once()

    def test_existing_unfinished_task_blocks_new_run(self):
        machine = MagicMock()
        client = MagicMock()
        client.tasks.return_value = [{'id': 'existing', 'status': 'ongoing'}]
        with patch('ciab_devenv.acp.Client', return_value=client):
            with self.assertRaisesRegex(DevError, 'unfinished tasks'):
                run_task(machine, argparse.Namespace(command='probe', timeout=1))
        machine.call.assert_not_called()
