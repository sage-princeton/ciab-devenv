import tempfile
import unittest
from pathlib import Path

from devops.production import bundle, contracts, plan, scaffold_settings


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

    def test_controller_plan_uses_selected_source_without_cloud_operations(self):
        source=self.package('controller', 'class Controller:\n    @staticmethod\n    def parse(value): return Controller()\n    def plan(self): return {"deployment":"controller"}\n')
        spec=self.root/'controller.json'
        spec.write_text('{"kind":"controller"}')
        self.assertEqual(plan(source,spec), {'deployment':'controller'})

    def test_older_source_cannot_silently_treat_controller_as_run(self):
        source=self.package('older', 'class Run: pass\n')
        spec=self.root/'controller.json'
        spec.write_text('{"kind":"controller"}')
        with self.assertRaisesRegex(ValueError,'Controller'):
            plan(source,spec)

    def test_legacy_source_is_optional_but_explicit_plan_requires_contract(self):
        self.assertIsNone(scaffold_settings(self.root, {}))
        with self.assertRaisesRegex(ValueError, 'does not provide'):
            contracts(self.root, required=True)

    def test_failed_load_is_not_cached_as_success(self):
        root = self.package('broken', 'raise ValueError("broken")\n')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'broken'):
                contracts(root)

    def test_legacy_source_has_no_bundle(self):
        self.assertIsNone(bundle(self.root, {}, self.root, self.root / 'payload'))

    def test_bundle_uses_selected_source_and_caller_inputs(self):
        source = self.package('bundle', 'class Run:\n    @staticmethod\n    def parse(value): return value\n')
        (source / 'devops/crux_devops/bundle.py').write_text(
            'def assemble(source, run, output, *, drop_in):\n'
            '    return dict(source=str(source), run=run, inputs=str(drop_in), output=str(output))\n')
        inputs, output = self.root / 'inputs', self.root / 'payload'
        settings = dict(scaffold='acp', platform='claude', provider='direct', model='model', effort='low', run_slug='local')
        result = bundle(source, settings, inputs, output)
        self.assertEqual(result['source'], str(source))
        self.assertEqual(result['inputs'], str(inputs))
        self.assertEqual(result['run']['scaffold']['configuration']['control_mcp_base'], 'https://agentrq.test')
        self.assertEqual(result['run']['scaffold']['platform'], 'claude')

    def test_symlink_cannot_load_contracts_outside_selected_source(self):
        outside = self.package('outside', 'VERSION = 1\n')
        source = self.root / 'source'
        (source / 'devops').mkdir(parents=True)
        (source / 'devops/crux_devops').symlink_to(outside / 'devops/crux_devops')
        with self.assertRaisesRegex(ValueError, 'leave'):
            contracts(source)
