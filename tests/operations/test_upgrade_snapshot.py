import unittest

from ops.test_upgrade import application_services, same_with_empty_extensions, snapshot_query


class UpgradeSnapshotTests(unittest.TestCase):
    def test_current_release_compares_all_preexisting_columns(self):
        query = snapshot_query("0024_income_planning")
        self.assertIn("(to_jsonb(t))::text", query)
        self.assertNotIn(" - %L", query)
        self.assertIn("',', '', c.relname", query)

    def test_older_release_excludes_only_later_columns(self):
        old = snapshot_query("0014_vault")
        self.assertEqual(old.count(" - %L"), 8)
        self.assertIn("'manual_override'", old)
        middle = snapshot_query("0016_replacement_override")
        self.assertEqual(middle.count(" - %L"), 4)
        self.assertNotIn("'manual_override'", middle)
        self.assertNotIn("'cleared_link_version'", middle)
        self.assertIn("'install_key_hash'", middle)


class UpgradeServicesTests(unittest.TestCase):
    def test_old_renderer_without_inspector_keeps_two_app_services(self):
        rendered = {"services": {"scanner": {}, "api": {"depends_on": {"db": {}, "scanner": {}}}}}
        self.assertEqual(application_services(rendered), ("scanner", "api"))

    def test_current_old_renderer_keeps_required_inspector(self):
        rendered = {"services": {"scanner": {}, "inspector": {},
                    "api": {"depends_on": {"db": {}, "scanner": {}, "inspector": {}}}}}
        self.assertEqual(application_services(rendered), ("scanner", "inspector", "api"))
        del rendered["services"]["inspector"]
        with self.assertRaises(ValueError):
            application_services(rendered)

    def test_unknown_dependency_cannot_be_silently_removed(self):
        with self.assertRaises(ValueError):
            application_services({
                "services": {"scanner": {}, "api": {"depends_on": {"unknown": {}}}}
            })


class UpgradeNewTableTests(unittest.TestCase):
    def test_only_new_empty_orders_are_allowed_for_pre_order_schema(self):
        before = {"stock_movements": (2, "original-hash")}
        after = {**before, "consumable_orders": (0, "empty-hash")}
        self.assertTrue(same_with_empty_extensions(before, after, "0018_install_device"))
        self.assertIn("consumable_orders", after)
        self.assertFalse(same_with_empty_extensions(before, after, "0021_consumable_orders"))
        for changed in (
            {**before, "consumable_orders": (1, "new-row")},
            {**after, "stock_movements": (2, "changed-hash")},
            {**after, "unexpected_table": (0, "empty-hash")},
            {"consumable_orders": (0, "empty-hash")},
        ):
            self.assertFalse(same_with_empty_extensions(before, changed, "0018_install_device"))

    def test_preexisting_order_hashes_are_never_exempt(self):
        before = {"consumable_orders": (1, "original-hash")}
        self.assertTrue(same_with_empty_extensions(before, before, "0021_consumable_orders"))
        self.assertFalse(same_with_empty_extensions(
            before, {"consumable_orders": (0, "empty")}, "0021_consumable_orders"
        ))

    def test_only_empty_new_planning_tables_are_exempt(self):
        before = {"cards": (1, "unchanged")}
        for name in ("expected_incomes", "bonus_awards", "income_planning_revisions"):
            after = {**before, name: (0, "empty")}
            self.assertTrue(same_with_empty_extensions(before, after, "0021_consumable_orders"))
            self.assertFalse(same_with_empty_extensions(before, after, "0024_income_planning"))
            self.assertFalse(same_with_empty_extensions(
                before, {**before, name: (1, "unexpected")}, "0021_consumable_orders"
            ))
        query = snapshot_query("0021_consumable_orders")
        self.assertEqual(query.count(" - %L"), 2)
        self.assertIn("'annual_fee_krw'", query)
        self.assertIn("'is_family_card'", query)
