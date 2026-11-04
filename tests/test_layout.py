import tempfile
import unittest
from pathlib import Path

from ciab_devenv.layout import source_path


class SourceLayoutTests(unittest.TestCase):
    def test_current_and_legacy_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for current, legacy in (
                ('devops/ec2-workspaces/install-run.sh', 'src/ec2-workspaces/install-run.sh'),
                ('scaffolds/sdk/requirements.txt', 'src/sdk-scaffold/requirements.txt'),
            ):
                old = root / legacy
                old.parent.mkdir(parents=True, exist_ok=True)
                old.touch()
                self.assertEqual(source_path(root, legacy), old)
                new = root / current
                new.parent.mkdir(parents=True, exist_ok=True)
                new.touch()
                self.assertEqual(source_path(root, legacy), new)

    def test_missing_path_still_reports_current_location(self):
        self.assertEqual(source_path(Path('/missing'), 'src/sdk-scaffold'),
                         Path('/missing/scaffolds/sdk'))
