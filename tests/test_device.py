import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths
from nonsteamapps import device


def tables(folder, vendor="Valve", board="", product=""):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in (("sys_vendor", vendor), ("board_name", board), ("product_name", product)):
        if value is not None:
            (folder / name).write_text(f"{value}\n")
    return folder


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_valves_boards_name_the_steam_machine_and_both_steam_decks(self):
        for board, name, deck, hdr in (("Fremont", "Steam Machine", False, True), ("Jupiter", "Steam Deck", True, False),
                                       ("Galileo", "Steam Deck", True, True)):
            with self.subTest(board):
                found = device.detect(tables(self.folder / board, board=board, product=board))
                self.assertEqual((found.board, found.name, found.steam_deck, found.hdr), (board, name, deck, hdr))

    def test_the_product_name_counts_where_the_board_is_not_known(self):
        self.assertEqual(device.detect(tables(self.folder, board="Unknown", product="Jupiter")).board, "Jupiter")

    def test_any_other_machine_is_a_pc(self):
        for vendor, board in (("ASUSTeK COMPUTER INC.", "Jupiter"), ("Valve", "Neptune"), ("valve", "Fremont")):
            with self.subTest(vendor=vendor, board=board):
                found = device.detect(tables(self.folder / f"{vendor}-{board}", vendor=vendor, board=board))
                self.assertEqual((found, found.name, found.steam_deck, found.hdr), (device.Device(), "PC", False, False))
        self.assertEqual(device.detect(self.folder / "missing"), device.Device())

    def test_the_tables_are_read_once_from_where_the_variable_points(self):
        self.assertEqual(device.current(), device.Device("Fremont"))
        with _paths.on_device("steam-deck") as deck:
            self.assertEqual(deck, device.Device("Jupiter"))
            tables(self.folder, board="Fremont")
            with mock.patch.dict(os.environ, {device.VARIABLE: str(self.folder)}):
                self.assertEqual(device.current(), deck)
        self.assertEqual(device.current(), device.Device("Fremont"))
        device.current.cache_clear()
        with mock.patch.dict(os.environ, {device.VARIABLE: ""}), mock.patch.object(device, "DMI", tables(self.folder / "real", board="Galileo")):
            self.assertEqual(device.current(), device.Device("Galileo"))
        device.current.cache_clear()
        device.current()



class TagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.machine_id = Path(self.tmp.name) / "machine-id"

    def tag(self, content=None):
        if content is None:
            self.machine_id.unlink(missing_ok=True)
        else:
            self.machine_id.write_text(content)
        with mock.patch.dict(os.environ, {device.MACHINE_ID_VARIABLE: str(self.machine_id)}):
            return device.tag()

    def test_each_device_gets_a_tag_of_its_own_from_its_machine_id_without_showing_it(self):
        machine = self.tag("5ca1ab1e0ddba11d0e5f00d5ca1ab1e0\n")
        deck = self.tag("0ddba11d5ca1ab1e0ddba11d5ca1ab1e\n")
        self.assertRegex(machine, r"\A[0-9a-f]{8}\Z")
        self.assertNotEqual(machine, deck)
        self.assertEqual(self.tag("5ca1ab1e0ddba11d0e5f00d5ca1ab1e0"), machine)
        self.assertNotIn(machine, "5ca1ab1e0ddba11d0e5f00d5ca1ab1e0")

    def test_without_a_machine_id_the_host_name_tells_the_device_apart(self):
        with mock.patch("socket.gethostname", return_value="steamdeck"):
            self.assertEqual(self.tag(), device.device_tag("host:steamdeck"))
            self.assertEqual(self.tag(""), device.device_tag("host:steamdeck"))
        with mock.patch("socket.gethostname", return_value="steammachine"):
            self.assertNotEqual(self.tag(), device.device_tag("host:steamdeck"))


if __name__ == "__main__":
    unittest.main()
