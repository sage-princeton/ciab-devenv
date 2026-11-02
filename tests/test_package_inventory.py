import unittest

from verification.package_inventory import packages


class PackageInventoryTests(unittest.TestCase):
    """Exercise PackageInventory behavior in isolated fixtures."""
    def test_preserves_source_version_for_binary_packages(self):
        """Verify preserves source version for binary packages."""
        result=packages('libexample:arm64\t1.2-3ubuntu1\tarm64\texample\t1.2-3ubuntu1\n')
        self.assertEqual(result,[{'name':'libexample:arm64','version':'1.2-3ubuntu1','architecture':'arm64',
                                 'source':'example','source_version':'1.2-3ubuntu1'}])

    def test_rejects_incomplete_inventory(self):
        """Verify rejects incomplete inventory."""
        with self.assertRaises(ValueError):
            packages('truncated\tversion\n')
