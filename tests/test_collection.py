import json
import tempfile
import unittest
from pathlib import Path

import _fakes
from nonsteamapps import collection

ACCOUNT = 111
OURS = collection.collection_id("0a1b2c3d")
KEY = f"user-collections.{OURS}"


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = _fakes.make_cloud_storage(self.root, ACCOUNT)

    def tearDown(self):
        self.tmp.cleanup()

    def entries(self):
        return {key: value for key, value in json.loads(self.path.read_text())}

    def test_steams_current_namespace_is_used_once_it_exists(self):
        self.assertEqual(collection.storage_file(self.root, ACCOUNT), self.path)
        other = _fakes.make_cloud_storage(self.root, ACCOUNT, namespace=3)
        self.assertEqual(collection.storage_file(self.root, ACCOUNT), other)
        self.assertIsNone(collection.storage_file(self.root, 222))

    def test_apps_go_in_and_out_without_touching_other_collections(self):
        self.assertTrue(collection.update(self.path, OURS, "NonSteamApps", add=[3000000001, 3000000002]))
        self.assertFalse(collection.update(self.path, OURS, "NonSteamApps", add=[3000000002]))
        entry = self.entries()[KEY]
        self.assertEqual(json.loads(entry["value"]), {"id": "nonsteamapps-0a1b2c3d", "name": "NonSteamApps", "added": [3000000001, 3000000002], "removed": []})
        self.assertEqual((entry["conflictResolutionMethod"], entry["strMethodId"]), ("custom", "union-collections"))
        self.assertEqual(entry["version"], str(entry["timestamp"]))
        self.assertTrue(collection.update(self.path, OURS, "Living room", remove=[3000000001]))
        self.assertEqual(json.loads(self.entries()[KEY]["value"])["removed"], [3000000001])
        self.assertEqual(json.loads(self.entries()[KEY]["value"])["name"], "Living room")
        self.assertEqual(collection.members(self.path, OURS), [3000000002])
        for key, original in _fakes.USER_COLLECTIONS:
            self.assertEqual(self.entries()[key], original)

    def test_an_empty_collection_is_deleted_and_can_come_back(self):
        collection.update(self.path, OURS, "NonSteamApps", add=[3000000001])
        self.assertTrue(collection.update(self.path, OURS, "NonSteamApps", remove=[3000000001]))
        self.assertTrue(self.entries()[KEY]["is_deleted"])
        self.assertEqual(collection.members(self.path, OURS), [])
        self.assertFalse(collection.delete(self.path, OURS))
        collection.update(self.path, OURS, "NonSteamApps", add=[3000000001])
        self.assertNotIn("is_deleted", self.entries()[KEY])
        self.assertTrue(collection.delete(self.path, OURS))
        self.assertTrue(self.entries()[KEY]["is_deleted"])

    def test_each_device_keeps_its_own_collection_and_the_shared_one_can_go(self):
        theirs = collection.collection_id("9f8e7d6c")
        collection.update(self.path, collection.SHARED_ID, "NonSteamApps", add=[3000000001])
        collection.update(self.path, OURS, "NonSteamApps (Steam Machine)", add=[3000000002])
        collection.update(self.path, theirs, "NonSteamApps (Steam Deck)", add=[3000000003])
        self.assertEqual([collection.members(self.path, ident) for ident in (collection.SHARED_ID, OURS, theirs)],
                         [[3000000001], [3000000002], [3000000003]])
        self.assertTrue(collection.delete(self.path, collection.SHARED_ID))
        self.assertTrue(self.entries()["user-collections.nonsteamapps"]["is_deleted"])
        self.assertEqual([collection.members(self.path, ident) for ident in (OURS, theirs)], [[3000000002], [3000000003]])

    def test_an_unreadable_file_is_left_alone(self):
        self.path.write_text("{broken")
        self.assertFalse(collection.update(self.path, OURS, "NonSteamApps", add=[3000000001]))
        self.assertEqual(self.path.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
