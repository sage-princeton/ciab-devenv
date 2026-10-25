import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciab_devenv.cli import main
from ciab_devenv.config import DevError, Environment, private_write, source_info
from ciab_devenv.machine import Machine, PROVISION_FILES, scrub, secret_values, validate_source
from ciab_devenv.scaffolds import SDK, get_scaffold


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.email', 'test@example.invalid'), ('config', 'user.name', 'Test')):
            subprocess.run(['git', '-C', str(self.source), *args], check=True, capture_output=True)
        for name in PROVISION_FILES:
            file = self.source / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('# test source\n')
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), 'commit', '-m', 'fixture'], check=True, capture_output=True)
        env = patch.dict(os.environ, {'CIAB_STATE_ROOT': str(self.root / 'state')})
        env.start()
        self.addCleanup(env.stop)
        self.instance = Environment('test')
        self.instance.setup(self.source, 23400)
        self.machine = Machine(self.instance)

    def test_source_without_provisioning_is_rejected(self):
        (self.source / PROVISION_FILES[0]).unlink()
        with self.assertRaisesRegex(DevError, 'lacks SDK provisioning'):
            validate_source(self.source)

    def test_legacy_instances_and_receipts_keep_sdk_behavior(self):
        self.instance.data.pop('scaffold')
        self.assertEqual(self.instance.scaffold, SDK)
        self.assertEqual(SDK.command('exec', ['echo', 'hello']), ['echo', 'hello'])
        self.assertEqual(SDK.command('probe')[-2:], ['--coding-agent', 'codex'])
        self.assertIn('/srv/crux-run/state', SDK.command('check'))
        with self.assertRaisesRegex(DevError, 'Unsupported scaffold'):
            get_scaffold('unknown')

    def test_scaffold_drift_cannot_execute_existing_receipt(self):
        private_write(self.machine.receipt, json.dumps({'source': source_info(self.source), 'scaffold': 'other'}))
        with patch.object(self.machine, 'require_running'):
            with self.assertRaisesRegex(DevError, 'scaffold changed'):
                self.machine.require_provisioned()

    def test_idle_check_and_shutdown_use_selected_service(self):
        with patch.object(self.machine, 'state', return_value={'state': 'running'}):
            with patch.object(self.machine, 'call', return_value=subprocess.CompletedProcess([], 0, 'active')):
                with self.assertRaisesRegex(DevError, 'crux-sdk-run is active'):
                    self.machine.require_idle()
            with patch.object(self.machine, 'call') as remote, patch('subprocess.run') as host:
                self.machine.stop()
                self.assertIn(SDK.service, remote.call_args.args)
                host.assert_called_once_with(['orb', 'stop', self.machine.name], check=True)

    def test_unprovisioned_or_changed_source_cannot_execute(self):
        with patch.object(self.machine, 'require_running'):
            with self.assertRaisesRegex(DevError, 'Provision this machine'):
                self.machine.require_provisioned()
            private_write(self.machine.receipt, json.dumps({'source': source_info(self.instance.source)}))
            self.machine.require_provisioned()
            (self.source / PROVISION_FILES[1]).write_text('# changed implementation\n')
            with self.assertRaisesRegex(DevError, 'changed since provisioning'):
                self.machine.require_provisioned()

    def test_shutdown_does_not_wake_stopped_machine(self):
        for state in (None, {'state': 'stopped'}):
            with patch.object(self.machine, 'state', return_value=state), patch.object(self.machine, 'call') as remote:
                self.machine.stop()
                remote.assert_not_called()

    def test_report_is_available_without_runtime_and_rejects_traversal(self):
        private_write(self.instance.root / 'reports/test-id/report.json', '{"exit_code": 0}\n')
        private_write(self.instance.root / 'reports/test-id/output.log', 'test output\n')
        with patch('ciab_devenv.cli.runtime_ready', side_effect=AssertionError('must stay offline')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--name', 'test', 'report', '--output', str(self.root / 'export')]), 0)
            self.assertEqual(json.loads(output.getvalue()), {'exit_code': 0})
            self.assertEqual((self.root / 'export/output.log').read_text(), 'test output\n')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--name', 'test', 'report', '../../instance']), 2)

    def test_latest_report_uses_completion_time_instead_of_random_id_order(self):
        older = self.instance.root / 'reports/z-old/report.json'
        newer = self.instance.root / 'reports/a-new/report.json'
        private_write(older, '{"run_id": "older"}')
        private_write(newer, '{"run_id": "newer"}')
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--name', 'test', 'report']), 0)
        self.assertEqual(json.loads(output.getvalue())['run_id'], 'newer')

    def test_known_credentials_are_redacted(self):
        self.assertEqual(scrub('secret-value and ordinary output', {'API_TOKEN': 'secret-value'}),
                         '[REDACTED] and ordinary output')
        bundle = {'API_KEYS': {'CUSTOM_NAME': 'nested-private-value'}, 'SERVICE_AUTH': [{'credential': 'service-private-value'}]}
        values = {f'SECRET_{i}': value for i, value in enumerate(secret_values(bundle))}
        self.assertEqual(scrub('nested-private-value service-private-value', values), '[REDACTED] [REDACTED]')


if __name__ == '__main__':
    unittest.main()
