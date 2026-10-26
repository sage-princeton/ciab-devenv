import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ciab_devenv.config import DevError
from devops.resources import Box, Services


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.instance = SimpleNamespace(root=Path(self.temp.name), project='ciab-test')
        self.context = SimpleNamespace(owner='original-owner')

    def test_same_name_new_machine_cannot_be_deleted(self):
        (self.instance.root / 'box-identity.json').write_text(json.dumps({'id': 'old-id', 'owner': self.context.owner}))
        machine = Mock(instance=self.instance)
        machine.state.return_value = {'id': 'replacement-id', 'config': {'isolated': True}, 'state': 'stopped'}
        with self.assertRaisesRegex(DevError, 'not owned'):
            Box(machine).destroy(None, {}, self.context)
        machine.delete.assert_not_called()

    def test_owned_stopped_machine_validates_without_starting(self):
        (self.instance.root / 'box-identity.json').write_text(json.dumps({'id': 'original-id', 'owner': self.context.owner}))
        machine = Mock(instance=self.instance)
        machine.state.return_value = {'id': 'original-id', 'config': {'isolated': True}, 'state': 'stopped'}
        Box(machine).preflight(None, self.context)
        machine.ensure.assert_not_called()
        machine.call.assert_not_called()

    @patch('devops.resources.subprocess.check_output')
    def test_foreign_container_blocks_services(self, command):
        command.return_value = 'another-owner\n'
        with self.assertRaisesRegex(DevError, 'containers'):
            Services(self.instance).preflight(None, self.context)

    @patch('devops.resources.subprocess.check_output')
    def test_foreign_volume_is_detected_after_containers_are_gone(self, command):
        command.side_effect = ['', 'ciab-test-data\n', 'another-owner\n']
        with self.assertRaisesRegex(DevError, 'volumes'):
            Services(self.instance).preflight(None, self.context)
