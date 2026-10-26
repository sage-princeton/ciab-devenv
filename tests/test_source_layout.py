import json
import tempfile
import unittest
from pathlib import Path

from devops.source import required_path, source_path


class SourceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def layout(self, data):
        path = self.root / "devops/layout.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))

    def test_older_sources_use_original_paths(self):
        self.assertEqual(source_path(self.root, "sdk"), self.root / "src/sdk-scaffold")

    def test_selected_source_defines_paths_and_tracing_is_separate(self):
        self.layout({"version": 1, "components": {"workspace": "devops/boxes",
                                               "codex_tracing": "monitoring/tracing/codex"}})
        self.assertEqual(required_path(self.root, "src/ec2-workspaces/install-run.sh"),
                         self.root / "devops/boxes/install-run.sh")
        self.assertEqual(required_path(self.root, "src/ec2-workspaces/live_trace/__init__.py"),
                         self.root / "monitoring/tracing/codex/live_trace/__init__.py")

    def test_unsupported_version_fails_without_legacy_fallback(self):
        self.layout({"version": 2, "components": {}})
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            source_path(self.root, "sdk")

    def test_component_cannot_escape_source(self):
        for path in ("../outside", "/outside"):
            with self.subTest(path=path):
                self.layout({"version": 1, "components": {"sdk": path}})
                with self.assertRaisesRegex(ValueError, "leaves"):
                    source_path(self.root, "sdk")
