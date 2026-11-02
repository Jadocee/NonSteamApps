import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from nonsteamapps import compat, vdf

FORCED, CLEARED, OTHER = 2147483649, 3000000000, 1245620

CONFIG = r'''"InstallConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"ConnectCache"
				{
					"1a2b3c4d"		"0123456789abcdef"
				}
				"CompatToolMapping"
				{
					"0"
					{
						"name"		"proton_experimental"
						"config"		""
						"priority"		"75"
					}
					"2147483649"
					{
						"name"		"proton_experimental"
						"config"		""
						"priority"		"250"
					}
					"3000000000"
					{
						"name"		""
						"config"		""
						"priority"		"250"
					}
					"1245620"
					{
						"name"		"proton_9"
						"config"		""
						"priority"		"250"
					}
				}
				"BaseInstallFolder_1"		"D:\\Games \"Steam\""
			}
		}
	}
	"SDL_GamepadBind"		"03000000de2800000512000011010000,Steam Deck,a:b0,b:b1"
}
'''


def mapping_keys(path):
    data = vdf.loads_pairs(path.read_text())
    node = data
    for key in compat.MAPPING_PATH:
        node = next(value for name, value in node if name.lower() == key.lower())
    return [name for name, _ in node]


class CompatToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = compat.config_file(self.root)
        self.path.parent.mkdir()
        self.path.write_text(CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_a_named_tool_counts_as_forced(self):
        self.assertEqual(compat.forced(self.root, [FORCED, CLEARED]), {FORCED: "proton_experimental"})
        self.assertEqual(compat.forced(self.root, [42]), {})

    def test_clearing_removes_only_these_forced_tools_and_keeps_the_rest_of_the_file(self):
        self.assertEqual(compat.clear(self.root, [FORCED, CLEARED]), {FORCED: "proton_experimental"})
        self.assertEqual(mapping_keys(self.path), ["0", "3000000000", "1245620"])
        original = vdf.loads_pairs(CONFIG)
        changed = vdf.loads_pairs(self.path.read_text())
        self.assertEqual(changed[0][1][1], original[0][1][1])
        steam = dict(dict(dict(changed[0][1][0][1])["Valve"])["Steam"])
        self.assertEqual(steam["BaseInstallFolder_1"], 'D:\\Games "Steam"')
        self.assertEqual(steam["ConnectCache"], [("1a2b3c4d", "0123456789abcdef")])
        self.assertEqual(self.path.with_name("config.vdf.nonsteamapps.bak").read_text(), CONFIG)
        stamp = self.path.stat().st_mtime_ns
        self.assertEqual(compat.clear(self.root, [FORCED, CLEARED]), {})
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_removed_shortcuts_lose_their_entries(self):
        self.assertEqual(compat.clear(self.root, [CLEARED], everything=True), {})
        self.assertEqual(mapping_keys(self.path), ["0", "2147483649", "1245620"])

    def test_a_missing_or_damaged_file_is_left_alone(self):
        self.path.write_text('"InstallConfigStore" {')
        self.assertEqual(compat.clear(self.root, [FORCED]), {})
        self.assertEqual(self.path.read_text(), '"InstallConfigStore" {')
        self.path.unlink()
        self.assertEqual(compat.clear(self.root, [FORCED]), {})
        self.assertFalse(self.path.exists())

    def test_keys_match_whatever_their_case(self):
        self.path.write_text(CONFIG.replace('"CompatToolMapping"', '"compattoolmapping"').replace('"Valve"', '"valve"'))
        self.assertEqual(compat.clear(self.root, [FORCED]), {FORCED: "proton_experimental"})


if __name__ == "__main__":
    unittest.main()
