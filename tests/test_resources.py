"""Live local resource discovery and ownership regression checks."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ciab_devenv.config import DevError
from devops.resources import Box, Services


class OwnershipTests(unittest.TestCase):
    """Exercise deterministic naming, labels and safe isolated-machine cleanup."""

    def setUp(self):
        """Create an environment namespace without resource-state files."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.instance = SimpleNamespace(root=Path(self.temp.name), project='ciab-test')
        self.context = SimpleNamespace(owner='original-owner')

    def test_nonisolated_machine_cannot_be_deleted(self):
        """Reject a same-name machine outside the isolated Box contract."""
        machine = Mock(instance=self.instance)
        machine.state.return_value = {'id': 'id', 'config': {'isolated': False}, 'state': 'stopped'}
        with self.assertRaisesRegex(DevError, 'not isolated'):
            Box(machine).destroy(None, {}, self.context)
        machine.delete.assert_not_called()

    def test_named_stopped_machine_is_discovered_without_starting(self):
        """Discover and remove a reserved named Box without local identity state."""
        machine = Mock(instance=self.instance)
        machine.name = 'ciab-test-run'
        machine.state.return_value = {'id': 'id', 'config': {'isolated': True}, 'state': 'stopped'}
        self.assertEqual(Box(machine).observe(None, self.context), {'machine': machine.name, 'id': 'id'})
        Box(machine).destroy(None, {}, self.context)
        machine.delete.assert_called_once_with()
        machine.ensure.assert_not_called()
        machine.call.assert_not_called()
        self.assertEqual(list(self.instance.root.iterdir()), [])

    @patch('devops.resources.subprocess.check_output')
    def test_foreign_container_blocks_services(self, command):
        """Reject a project-name collision when live owner labels differ."""
        command.return_value = 'another-owner\n'
        with self.assertRaisesRegex(DevError, 'containers'):
            Services(self.instance).preflight(None, self.context)

    @patch('devops.resources.subprocess.check_output')
    def test_foreign_volume_is_detected_after_containers_are_gone(self, command):
        """Use volume labels even after the service containers were removed."""
        command.side_effect = ['', 'ciab-test-data\n', 'another-owner\n']
        with self.assertRaisesRegex(DevError, 'volumes'):
            Services(self.instance).preflight(None, self.context)

    @patch('devops.resources.subprocess.check_output')
    def test_services_recover_from_only_a_retained_network(self, command):
        """An interrupted cleanup can discover a remaining project network."""
        command.side_effect = ['', '', 'ciab-test-net\n', 'original-owner\n']
        self.assertEqual(Services(self.instance).observe(None, self.context), {'project': 'ciab-test'})
