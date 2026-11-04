import tempfile
import unittest
from pathlib import Path

from ciab_devenv.config import DevError
from ciab_devenv.scaffolds import SDK
from devops.source import required_path, source_path


class SourceLayoutTests(unittest.TestCase):
    """Preserve SDK discovery and diagnostics across the directory migration."""

    def test_current_and_legacy_layouts(self):
        """Prefer canonical files while accepting existing legacy worktrees."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for current, legacy in (
                ('devops/ec2-workspaces/install-run.sh', 'src/ec2-workspaces/install-run.sh'),
                ('scaffolds/sdk/requirements.txt', 'src/sdk-scaffold/requirements.txt'),
            ):
                old = root / legacy
                old.parent.mkdir(parents=True, exist_ok=True)
                old.touch()
                self.assertEqual(required_path(root, legacy), old)
                new = root / current
                new.parent.mkdir(parents=True, exist_ok=True)
                new.touch()
                self.assertEqual(required_path(root, legacy), new)

    def test_missing_path_still_reports_current_location(self):
        """Report canonical locations when the selected source is incomplete."""
        self.assertEqual(source_path(Path('/missing'), 'sdk'),
                         Path('/missing/scaffolds/sdk'))

    def test_source_validation_reports_resolved_missing_files(self):
        """Name the missing canonical file in user-facing source errors."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DevError, 'scaffolds/sdk/requirements.txt'):
                SDK.validate_source(Path(tmp))
