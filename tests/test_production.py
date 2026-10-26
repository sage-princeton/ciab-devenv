import tempfile
import unittest
from pathlib import Path

from devops.production import contracts, scaffold_settings


class ProductionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, name, text):
        root = self.root / name
        package = root / 'devops/crux_devops'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text(text)
        return root

    def test_selected_sources_do_not_share_imported_contracts(self):
        one = self.package('one', 'VERSION = 1\n')
        two = self.package('two', 'VERSION = 2\n')
        self.assertEqual(contracts(one).VERSION, 1)
        self.assertEqual(contracts(two).VERSION, 2)

    def test_legacy_source_is_optional_but_explicit_plan_requires_contract(self):
        self.assertIsNone(scaffold_settings(self.root, {}))
        with self.assertRaisesRegex(ValueError, 'does not provide'):
            contracts(self.root, required=True)

    def test_failed_load_is_not_cached_as_success(self):
        root = self.package('broken', 'raise ValueError("broken")\n')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'broken'):
                contracts(root)

    def test_symlink_cannot_load_contracts_outside_selected_source(self):
        outside = self.package('outside', 'VERSION = 1\n')
        source = self.root / 'source'
        (source / 'devops').mkdir(parents=True)
        (source / 'devops/crux_devops').symlink_to(outside / 'devops/crux_devops')
        with self.assertRaisesRegex(ValueError, 'leave'):
            contracts(source)
