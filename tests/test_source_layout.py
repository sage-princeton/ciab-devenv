"""Source selection follows repository structure without a separate manifest."""
import tempfile
import unittest
from pathlib import Path

from devops.source import required_path, source_path


class SourceLayoutTests(unittest.TestCase):
    """Verify canonical/older layouts and source-boundary enforcement."""

    def setUp(self):
        """Create an isolated source tree for each layout scenario."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_older_sources_use_original_paths(self):
        """Keep old PR worktrees testable before the layout migration."""
        (self.root / 'src/sdk-scaffold').mkdir(parents=True)
        self.assertEqual(source_path(self.root, "sdk"), self.root / "src/sdk-scaffold")

    def test_canonical_tree_uses_component_directories(self):
        """Discover current paths from the checkout itself."""
        (self.root/'devops/ec2-workspaces').mkdir(parents=True)
        self.assertEqual(required_path(self.root,"src/ec2-workspaces/install-run.sh"),
                         self.root/'devops/ec2-workspaces/install-run.sh')
        self.assertEqual(required_path(self.root,"src/ec2-workspaces/live_trace/__init__.py"),
                         self.root/'monitoring/tracing/codex/live_trace/__init__.py')

    def test_component_cannot_escape_source(self):
        """Reject path traversal and symlinks to external source content."""
        (self.root/'devops/ec2-workspaces').mkdir(parents=True)
        (self.root/'scaffolds').mkdir()
        (self.root/'scaffolds/sdk').symlink_to('/tmp')
        with self.assertRaisesRegex(ValueError,"leaves"):
            source_path(self.root,'sdk')
        with self.assertRaisesRegex(ValueError,"leaves"):
            source_path(self.root,'workspace','../../../outside')
