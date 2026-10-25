import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciab_devenv.scaffolds import SDK
from ciab_devenv.config import DevError, Environment, private_write, source_info, stage_directory


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for args in (("init", "-b", "main"), ("config", "user.email", "test@example.invalid"),
                     ("config", "user.name", "Test")):
            subprocess.run(["git", "-C", str(self.source), *args], check=True, capture_output=True)
        for name in SDK.required_files:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        (self.source / "code.py").write_text("first\n")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "commit", "-m", "fixture"], check=True, capture_output=True)
        self.env = patch.dict(os.environ, {"CIAB_STATE_ROOT": str(self.root / "state")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_snapshot_contains_tracked_local_edits_and_excludes_credentials(self):
        (self.source / ".envrc").write_text("export OPENAI_API_KEY=fixture-private-value")
        (self.source / "code.py").write_text("edited\n")
        instance = Environment("sample")
        instance.setup(self.source, 23100)
        snapshot = instance.root / "source"
        self.assertEqual((snapshot / "code.py").read_text(), "edited\n")
        self.assertFalse((snapshot / ".envrc").exists())
        self.assertFalse((snapshot / ".git").exists())
        self.assertIn("code.py", source_info(self.source)["changes"])
        (self.source / "code.py").unlink()
        instance.stage_source()
        self.assertFalse((snapshot / "code.py").exists())

    def test_named_instances_have_distinct_credentials_and_private_state(self):
        first, second = Environment("first"), Environment("second")
        first.setup(self.source, 23100)
        second.setup(self.source, 23101)
        self.assertNotEqual(first.data["fixture_token"], second.data["fixture_token"])
        self.assertEqual(stat.S_IMODE(first.path.stat().st_mode), 0o600)
        saved = first.path.read_bytes()
        first.setup(self.source, 23100)
        self.assertEqual(first.path.read_bytes(), saved)
        self.assertNotIn("OPENAI_API_KEY", first.path.read_text())

    def test_invalid_names_and_mismatched_instance_are_rejected(self):
        for name in ("../other", "UPPER", "", "a/b", "a" * 37):
            with self.assertRaises(DevError):
                Environment(name)
        instance = Environment("sample")
        instance.setup(self.source, 23100)
        with self.assertRaises(DevError):
            instance.setup(self.source, 23101)

    def test_private_write_repairs_permissions(self):
        path = self.root / "config.json"
        path.write_text("old")
        path.chmod(0o644)
        private_write(path, json.dumps({"test": True}))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_caller_input_excludes_secret_files_and_symlinks(self):
        (self.source / ".envrc").write_text("private")
        (self.source / "outside").symlink_to(self.root)
        stage_directory(self.source, self.root / "staged")
        self.assertEqual((self.root / "staged/code.py").read_text(), "first\n")
        self.assertFalse((self.root / "staged/.envrc").exists())
        self.assertFalse((self.root / "staged/outside").exists())

    def test_explicit_live_override_does_not_change_other_services(self):
        instance = Environment("sample")
        instance.setup(self.source, 23100)
        with patch.dict(os.environ, {"CIAB_LIVE_LANGFUSE_BASE_URL": "https://test.example.invalid"}):
            values = instance.compose_env()
        self.assertEqual(values["LANGFUSE_BASE_URL"], "https://test.example.invalid")
        self.assertEqual(values["COST_TRACKER_URL"], "https://cost.test/cost")


if __name__ == "__main__":
    unittest.main()
