import unittest

from ops.test_upgrade import snapshot_query


class UpgradeSnapshotTests(unittest.TestCase):
    def test_current_release_compares_all_preexisting_columns(self):
        query = snapshot_query("0018_install_device")
        self.assertIn("(to_jsonb(t))::text", query)
        self.assertNotIn(" - %L", query)
        self.assertIn("',', '', c.relname", query)

    def test_older_release_excludes_only_later_columns(self):
        old = snapshot_query("0014_vault")
        self.assertEqual(old.count(" - %L"), 6)
        self.assertIn("'manual_override'", old)
        middle = snapshot_query("0016_replacement_override")
        self.assertEqual(middle.count(" - %L"), 2)
        self.assertNotIn("'manual_override'", middle)
        self.assertNotIn("'cleared_link_version'", middle)
        self.assertIn("'install_key_hash'", middle)
