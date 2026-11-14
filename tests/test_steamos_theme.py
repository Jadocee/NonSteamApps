import base64
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import _paths
from nonsteamapps import artwork
from test_artwork import chromium

THEME = Path(_paths.ROOT) / "src" / "share" / "userstyles" / "nonsteamapps-steamos.css"
YOUTUBE = """
.AF89N, .fLo1Nd { background-color: #f1f1f1; }
.LXFmc .AF89N, .LXFmc .fLo1Nd { background-color: #f03; }
.fLo1Nd { height: 100%; }
.QBQn5 { background-color: #606060; }
.PQKKSe { position: relative; }
body { margin: 0; background: #000; }
[idomkey="progress-bar"] { display: flex; height: 10px; margin-bottom: 10px; }
[idomkey^="chapter-"] { height: 10px; }
"""
SPONSORBLOCK = """
ytlr-multi-markers-player-bar-renderer [idomkey^="chapter-"]::after {
    content: ''; position: absolute; inset: 0; pointer-events: none; opacity: 0.7;
}
ytlr-multi-markers-player-bar-renderer [idomkey="chapter-0"]::after {
    background: linear-gradient(to right, transparent 50%, #00d400 50%, #00d400 100%, transparent 100%);
}
"""


def chapters(current: int, count: int = 4, inline: bool = False, named: bool = True) -> str:
    """A chapter bar as YouTube's TV interface draws it: chapters before the current one played, coloured by a class or inline,
    and the current one holding the playhead's part, named ``current-chapter`` unless ``named`` is false."""
    parts = []
    for index in range(count):
        if index < current:
            colour = "background: rgb(255, 0, 51); " if inline else ""
            parts.append(f'<div idomkey="chapter-{index}" class="PQKKSe I0ojfb AF89N" style="{colour}width: 100px"></div>')
        elif index == current:
            name = ' idomkey="current-chapter"' if named else ""
            parts.append(f'<div idomkey="chapter-{index}" class="PQKKSe I0ojfb QBQn5 qH4xQd" style="width: 100px">'
                         f'<div class="fLo1Nd"{name} style="width: 40%"></div></div>')
        else:
            parts.append(f'<div idomkey="chapter-{index}" class="PQKKSe I0ojfb QBQn5 qH4xQd" style="width: 100px"></div>')
    parts.append('<div class="PQKKSe" idomkey="segment" style="position: absolute; left: 0"></div>')
    return '<div idomkey="progress-bar" class="afTAdb v25Ekb">' + "".join(parts) + "</div>"


def pixel(png: bytes) -> tuple:
    """The colour of a one-pixel PNG, whose row is the same whatever filter it was written with."""
    position, data, channels = 8, b"", 3
    while position < len(png):
        length, kind = struct.unpack(">I4s", png[position:position + 8])
        body = png[position + 8:position + 8 + length]
        if kind == b"IHDR":
            channels = {2: 3, 6: 4}[body[9]]
        elif kind == b"IDAT":
            data += body
        position += 12 + length
    row = zlib.decompress(data)
    return tuple(row[1:1 + channels])[:3]


class SteamOsThemeTests(unittest.TestCase):
    """NonSteamApps' SteamOS theme on the player bar of YouTube's TV interface, in a real Chromium; skipped where none starts."""

    def setUp(self):
        program = chromium()
        if program is None:
            self.skipTest("no Chromium on this machine")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.browser = artwork.Browser(program, timeout=30)
        try:
            self.browser.start()
        except artwork.BrowserError as exc:
            self.skipTest(f"Chromium did not start here: {exc}")
        self.addCleanup(self.browser.close)
        self.session = self.browser.page()

    def show(self, bars: str, seeking: bool = False, styles: str = "") -> None:
        """Draw ``bars`` in YouTube's player bar, in its style while seeking if ``seeking``, with VacuumTube's ``styles``."""
        page = Path(self.tmp.name) / "player.html"
        focused = ' class="LXFmc"' if seeking else ""
        page.write_text(f"<!doctype html><style>{YOUTUBE}</style><style>{styles}</style><style>{THEME.read_text()}</style>"
                        f"<ytlr-progress-bar><ytlr-multi-markers-player-bar-renderer idomkey=\"player-bar-renderer\"{focused}>{bars}"
                        "</ytlr-multi-markers-player-bar-renderer></ytlr-progress-bar>")
        self.assertTrue(self.browser.load(self.session, page.as_uri(), 600, 200, transparent=False))

    def colour(self, x: int, y: int) -> tuple:
        shot = self.browser.call("Page.captureScreenshot", {"format": "png", "clip": {"x": x, "y": y, "width": 1, "height": 1, "scale": 1}},
                                 self.session)["data"]
        return pixel(base64.b64decode(shot))

    def assertBlue(self, colour: tuple) -> None:
        red, green, blue = colour
        self.assertTrue(red < 60 and 130 < green < 190 and blue > 230, colour)

    def test_chapters_already_played_turn_blue_however_youtube_colours_them_and_those_to_come_stay_grey(self):
        self.show(chapters(2) + chapters(2, inline=True) + chapters(0))
        for row in (5, 25):
            self.assertBlue(self.colour(50, row))
            self.assertBlue(self.colour(150, row))
            self.assertBlue(self.colour(220, row))
            self.assertEqual(self.colour(280, row), (96, 96, 96))
            self.assertEqual(self.colour(350, row), (96, 96, 96))
        self.assertBlue(self.colour(20, 45))
        self.assertEqual(self.colour(80, 45), (96, 96, 96))
        self.assertEqual(self.colour(150, 45), (96, 96, 96))

    def test_chapters_already_played_stay_blue_while_seeking_where_youtube_turns_them_red(self):
        self.show(chapters(2) + chapters(2, inline=True), seeking=True)
        for row in (5, 25):
            self.assertBlue(self.colour(50, row))
            self.assertBlue(self.colour(150, row))
            self.assertBlue(self.colour(220, row))
            self.assertEqual(self.colour(280, row), (96, 96, 96))
            self.assertEqual(self.colour(350, row), (96, 96, 96))

    def test_chapters_already_played_turn_blue_whatever_youtube_names_the_playheads_part(self):
        for seeking in (False, True):
            with self.subTest(seeking=seeking):
                self.show(chapters(2, named=False), seeking=seeking)
                self.assertBlue(self.colour(50, 5))
                self.assertBlue(self.colour(150, 5))
                self.assertBlue(self.colour(220, 5))
                self.assertEqual(self.colour(280, 5), (96, 96, 96))
                self.assertEqual(self.colour(350, 5), (96, 96, 96))

    def test_sponsorblock_segments_keep_their_colour_on_chapters_already_played(self):
        self.show(chapters(2), styles=SPONSORBLOCK)
        self.assertBlue(self.colour(20, 5))
        red, green, blue = self.colour(70, 5)
        self.assertTrue(green > 180 and blue < 120, (red, green, blue))

    def test_a_bar_without_chapters_colours_its_played_part(self):
        self.show('<div idomkey="progress-bar" class="afTAdb v25Ekb"><div style="width: 100%; height: 10px">'
                  '<div class="fLo1Nd STXq3b" idomkey="current-chapter" style="width: 50%"></div></div></div>')
        self.assertBlue(self.colour(100, 5))


if __name__ == "__main__":
    unittest.main()
