import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ciab_devenv.acp import run_task
from ciab_devenv.agentrq import pins, prepare_image
from ciab_devenv.config import DevError, Environment
from ciab_devenv.scaffolds import ACP, SDK, get_scaffold
from devops.acp_setup import settings_environment


class ACPTests(unittest.TestCase):
    def test_manifest_source_does_not_require_legacy_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            scaffold = get_scaffold('acp', 'codex')
            for name in scaffold.required_files:
                if name.endswith('placeholders-base.txt.example'):
                    continue
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            manifest = source / 'scaffolds/codex/package.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{}')
            with patch('ciab_devenv.scaffolds.source_info'):
                scaffold.validate_source(source)

    def test_registry_image_requires_digest_and_records_installed_image(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CIAB_STATE_ROOT': tmp}):
            instance = Environment('registry')
            image = 'agentrq/agentrq:1.0.0@sha256:' + 'a' * 64
            with patch('ciab_devenv.agentrq.subprocess.run') as run, patch(
                'ciab_devenv.agentrq.subprocess.check_output',
                return_value='[{"Id":"sha256:installed","Architecture":"arm64"}]',
            ):
                dsn = 'file:/_storage/agentrq.db?_txlock=immediate'
                prepare_image(instance, {'AGENTRQ_IMAGE': image, 'AGENTRQ_SQLITE_DSN': dsn})
                run.assert_called_once_with(['docker', '--context', 'orbstack', 'pull', image],
                                            check=True, capture_output=True)
                self.assertEqual(instance.data['agentrq_image'], 'sha256:installed')
                self.assertEqual(instance.data['agentrq_architecture'], 'arm64')
                self.assertEqual(instance.data['agentrq_sqlite_dsn'], dsn)
                with self.assertRaisesRegex(DevError, 'digest pin'):
                    prepare_image(instance, {'AGENTRQ_IMAGE': 'agentrq/agentrq@sha256:invalid'})
                self.assertEqual(run.call_count, 1)

    def test_archive_pins_remain_required_for_older_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            control = source / 'src/ec2-control/configure-control.sh'
            workspace = source / 'src/ec2-workspaces/placeholders-base.txt.example'
            control.parent.mkdir(parents=True)
            workspace.parent.mkdir(parents=True)
            workspace.write_text('')
            control.write_text('AGENTRQ_IMAGE=agentrq/agentrq@sha256:' + 'a' * 64 + '\n'
                               "AGENTRQ_SQLITE_DSN='file:/_storage/agentrq.db?_txlock=immediate'\n")
            self.assertIn('AGENTRQ_IMAGE', pins(source))
            self.assertEqual(pins(source)['AGENTRQ_SQLITE_DSN'], 'file:/_storage/agentrq.db?_txlock=immediate')
            control.write_text('AGENTRQ_IMAGE=agentrq-crux:old\n')
            with self.assertRaisesRegex(DevError, 'AGENTRQ_IMAGE_URL'):
                pins(source)
            control.write_text('AGENTRQ_IMAGE=agentrq-crux:old\nAGENTRQ_IMAGE_URL=https://example.test/image.tar.gz\n'
                               'AGENTRQ_IMAGE_SHA256=' + 'b' * 64 + '\n')
            self.assertEqual(pins(source)['AGENTRQ_IMAGE_SHA256'], 'b' * 64)

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
            machine.run_units.return_value = [ACP.service]
            machine.job.return_value = 0
            machine.require_provisioned.return_value = {'scaffold': 'acp', 'platform': 'codex'}
            machine.call.return_value.stdout = 'active'
            client = MagicMock()
            client.tasks.return_value = []
            client.workspace.return_value = {'agentConnected': True}
            client.create.return_value = {'id': 'task1'}
            client.task.return_value = {'task': {'id': 'task1', 'status': 'completed'}}
            args = argparse.Namespace(command='probe', timeout=20)
            with patch('ciab_devenv.acp.Client', return_value=client), patch.object(instance, 'redactions', return_value={}):
                self.assertEqual(run_task(machine, args), 0)
            calls = [call.args for call in machine.call.call_args_list]
            self.assertIn(('systemctl', 'start', ACP.service), calls)
            machine.stop_run.assert_called_once()
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


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'CIAB_STATE_ROOT': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.instance = Environment('lifecycle')
        self.instance.data = {'scaffold': 'acp', 'platform': 'codex'}
        self.machine = MagicMock(instance=self.instance)
        self.machine.name = 'ciab-lifecycle-run'
        self.machine.require_provisioned.return_value = {'scaffold': 'acp', 'platform': 'codex'}
        self.machine.run_units.return_value = [ACP.service]
        self.machine.job.return_value = 0
        self.machine.call.return_value.stdout = 'active'
        self.client = MagicMock()
        self.client.tasks.return_value = []
        self.client.workspace.return_value = {'agentConnected': True}
        self.client.create.return_value = {'id': 'task1'}
        self.state = 'ongoing'
        self.interrupt = False
        self.client.task.side_effect = self.task
        for target, kwargs in (('ciab_devenv.acp.Client', {'return_value': self.client}),
                               ('ciab_devenv.acp.time.sleep', {})):
            mock = patch(target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(self.instance, 'redactions', return_value={'API_KEY': 'private-provider-credential'})
        mock.start()
        self.addCleanup(mock.stop)

    def task(self, task_id, suffix='', body=None, method=None):
        if self.interrupt and not suffix:
            self.interrupt = False
            raise KeyboardInterrupt
        if suffix == '/status':
            self.state = body['status']['value']
        return {'task': {'id': task_id, 'status': self.state, 'response': 'Done! private-provider-credential'}}

    def report(self):
        return json.loads(next(self.instance.root.glob('reports/*/report.json')).read_text())

    def test_completion_claim_does_not_bypass_timeout_and_cleanup(self):
        import itertools
        with patch('ciab_devenv.acp.time.monotonic', side_effect=itertools.count()):
            self.assertEqual(run_task(self.machine, argparse.Namespace(command='probe', timeout=1)), 124)
        self.machine.stop_run.assert_called_once()
        report = self.report()
        self.assertEqual(report['task']['status'], 'rejected')
        self.assertEqual(report['exit_code'], 124)
        self.assertNotIn('private-provider-credential', json.dumps(report))

    def test_interrupt_rejects_task_and_preserves_failure_evidence(self):
        self.interrupt = True
        self.assertEqual(run_task(self.machine, argparse.Namespace(command='probe', timeout=30)), 130)
        self.machine.stop_run.assert_called_once()
        self.assertEqual(self.report()['task']['status'], 'rejected')

    def test_blocked_task_is_not_success_or_cancelled(self):
        self.state = 'blocked'
        self.assertEqual(run_task(self.machine, argparse.Namespace(command='probe', timeout=30)), 3)
        self.assertEqual(self.report()['task']['status'], 'blocked')
        self.machine.stop_run.assert_called_once()

    def test_requeue_happens_before_gateway_start(self):
        self.state = 'blocked'
        calls = []
        def change(task_id, suffix='', body=None, method=None):
            if suffix == '/status':
                calls.append('requeue')
            return {'task': {'id': task_id, 'status': 'completed'}}
        self.client.task.side_effect = change
        self.machine.call.side_effect = lambda *a, **kw: calls.append('start')
        self.assertEqual(run_task(self.machine, argparse.Namespace(command='run', task_id='task1', timeout=30)), 0)
        self.assertLess(calls.index('requeue'), calls.index('start'))

    def test_cancel_falls_back_when_controller_cannot_notify_agent(self):
        from ciab_devenv.acp import task_control
        original = self.task
        def unavailable(task_id, suffix='', body=None, method=None):
            if suffix == '/stop':
                raise DevError('HTTP 409')
            return original(task_id, suffix, body, method)
        self.client.task.side_effect = unavailable
        self.assertEqual(task_control(self.machine, argparse.Namespace(action='cancel', task_id='task1')), 0)
        self.machine.stop_run.assert_called_once()
        self.assertEqual(self.report()['task']['status'], 'rejected')

    def test_cancel_does_not_stop_another_task(self):
        from ciab_devenv.acp import task_control
        self.client.tasks.return_value = [{'id': 'different', 'status': 'ongoing'}]
        self.assertEqual(task_control(self.machine, argparse.Namespace(action='cancel', task_id='task1')), 2)
        self.machine.stop_run.assert_not_called()

    def test_cancel_records_state_before_stopping_service(self):
        from ciab_devenv.acp import task_control
        self.machine.stop_run.side_effect = lambda: self.assertEqual(self.state, 'rejected')
        self.assertEqual(task_control(self.machine, argparse.Namespace(action='cancel', task_id='task1')), 0)
        self.machine.stop_run.assert_called_once()

    def test_concurrent_cancel_between_task_poll_and_service_check(self):
        def stop(*args, **kwargs):
            if args[:2] == ('systemctl', 'is-active'):
                self.state = 'rejected'
                return MagicMock(stdout='inactive')
        self.machine.call.side_effect = stop
        self.assertEqual(run_task(self.machine, argparse.Namespace(command='probe', timeout=30)), 3)
        self.assertEqual(self.report()['task']['status'], 'rejected')


class ClientContractTests(unittest.TestCase):
    def test_pagination_and_workspace_scope(self):
        from ciab_devenv.agentrq import Client
        client = Client.__new__(Client)
        client.instance = MagicMock(data={'agentrq_workspace_id': 'ownworkspace'})
        client.request = MagicMock(side_effect=[{'tasks': [{'id': str(i)} for i in range(50)]}, {'tasks': [{'id': 'last'}]}])
        self.assertEqual(len(client.tasks()), 51)
        self.assertIn('/workspaces/ownworkspace/tasks?', client.request.call_args.args[0])
        self.assertIn('offset=50', client.request.call_args.args[0])
        for invalid in ('../other', 'x/y', 'x?token=bad'):
            with self.assertRaises(DevError):
                client.task(invalid)
