import contextlib
import io
import os
import unittest
from unittest import mock

import _fakes
from nonsteamapps import ui
from nonsteamapps.progress import WIDTH, Bar, wanted

BLOCKS = set("█▏▎▍▌▋▊▉░")


def bar_cells(line):
    return sum(character in BLOCKS for character in line)


class BarTests(unittest.TestCase):
    def setUp(self):
        self.terminal = _fakes.Terminal()

    def test_draws_nothing_before_the_first_step_and_only_what_changed_after(self):
        bar = Bar(self.terminal, 4)
        bar.update(0.5)
        self.assertEqual(self.terminal.getvalue(), "")
        bar.step("Helium")
        bar.update(0.0)
        bar.update(0.5, "60 of 120 MB")
        bar.update(0.5, "60 of 120 MB")
        self.assertEqual(_fakes.bars(self.terminal.getvalue()), [
            "░" * 18 + "   0%  1 of 4 · Helium",
            "██▎" + "░" * 15 + "  12%  1 of 4 · Helium · 60 of 120 MB",
        ])

    def test_counts_the_steps_done_and_the_part_of_the_one_under_way(self):
        bar = Bar(self.terminal, 4)
        self.assertEqual(bar.done(), 0.0)
        bar.step("Helium")
        bar.update(0.5)
        self.assertEqual(bar.done(), 0.125)
        bar.step("YouTube")
        self.assertEqual((bar.done(), bar.detail), (0.25, ""))
        bar.update(2.0)
        self.assertEqual(bar.done(), 0.5)
        self.assertIn(" 50%  2 of 4 · YouTube", bar.line(80))
        bar.step("Element")
        bar.step("Steam library")
        bar.step("more than counted")
        self.assertEqual((bar.index, bar.total, bar.done()), (5, 5, 0.8))

    def test_steps_left_out_leave_the_count_but_never_below_the_step_under_way(self):
        bar = Bar(self.terminal, 6)
        bar.step("KytyPS5")
        bar.skip(2)
        self.assertIn("1 of 4 · KytyPS5", bar.line(80))
        bar.skip(10)
        self.assertEqual(bar.total, 1)

    def test_fits_any_terminal_with_one_bar_width_for_each(self):
        bar = Bar(self.terminal, 12)
        bar.step("YouTube")
        for width in range(5, 200):
            with self.subTest(width=width):
                widths = set()
                for detail in ("", "part 1 of 4, 3%, 120 kB/s", "part 4 of 4, 100%, 12.4 MB/s and a long tail of words " * 3):
                    bar.update(0.5, detail)
                    line = bar.line(width)
                    self.assertLessEqual(len(line), width - 1)
                    widths.add(bar_cells(line))
                self.assertEqual(len(widths), 1)
                self.assertLessEqual(widths.pop(), WIDTH)
        self.assertEqual(bar_cells(bar.line(80)), 18)
        self.assertEqual(bar_cells(bar.line(200)), WIDTH)
        self.assertEqual(bar_cells(bar.line(30)), 0)
        self.assertTrue(bar.line(60).endswith("…"))
        self.assertEqual(bar.line(5), "  4%")

    def test_draws_eighths_of_a_cell(self):
        bar = Bar(self.terminal, 1)
        bar.step("Eden-NX2")
        bar.update(0.25)
        self.assertTrue(bar.line(80).startswith("████▌" + "░" * 13 + "  25%"))
        bar.update(1.0)
        self.assertTrue(bar.line(80).startswith("█" * 18 + " 100%"))

    def test_hidden_until_shown_as_often_as_it_was_hidden(self):
        bar = Bar(self.terminal, 2)
        bar.step("Helium")
        bar.hide()
        bar.hide()
        bar.update(0.5)
        bar.show()
        self.assertTrue(self.terminal.getvalue().endswith("\r\033[2K"))
        bar.show()
        self.assertIn(" 25%  1 of 2 · Helium", _fakes.screen(self.terminal.getvalue())[-1])
        bar.clear()
        bar.clear()
        self.assertEqual(_fakes.screen(self.terminal.getvalue())[-1], "")
        self.assertFalse(self.terminal.getvalue().endswith("\r\033[2K\r\033[2K"))

    def test_colour_only_when_asked_for(self):
        plain, coloured = Bar(self.terminal, 2), Bar(self.terminal, 2, colour=True)
        for bar in (plain, coloured):
            bar.step("Helium")
            bar.update(0.5)
        self.assertNotIn("\033", plain.line(80))
        self.assertTrue(coloured.line(80).startswith("\033[34m████▌\033[0m\033[2m" + "░" * 13 + "\033[0m  25%"))

    def test_wanted_on_a_terminal_that_can_draw_it(self):
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}):
            self.assertTrue(wanted(_fakes.Terminal()))
            self.assertFalse(wanted(io.StringIO()))
        with mock.patch.dict(os.environ, {"TERM": "dumb"}):
            self.assertFalse(wanted(_fakes.Terminal()))
        with mock.patch.dict(os.environ, clear=True):
            self.assertFalse(wanted(_fakes.Terminal()))


class MessagesTests(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.dict(os.environ, {"TERM": "xterm-256color"}), mock.patch.object(ui, "_COLOUR", False),
                   mock.patch.object(ui, "quiet", False), mock.patch.object(ui, "assume_yes", False)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_install(self, stream):
        with contextlib.redirect_stderr(stream), ui.progress(3):
            self.assertEqual(ui.progressing(), isinstance(stream, _fakes.Terminal))
            ui.log("Installing Helium from GitHub")
            ui.step("Helium")
            ui.downloaded(60 << 20, 120 << 20)
            ui.info("Downloading helium.tar.xz (120 MB)")
            ui.step("YouTube")
            ui.advance(0.5, "part 1 of 2, 100%")
            ui.ok("Installed VacuumTube")
            with ui.paused():
                ui.warn("asked while paused")
                ui.advance(0.75, "drawn after the pause")
                self.during = stream.getvalue()
            ui.step("Steam library")
            ui.downloaded(5 << 20, 0)
            ui.error("something failed")
        self.assertFalse(ui.progressing())

    def test_without_a_terminal_the_output_is_what_it_was_without_a_bar(self):
        stream = io.StringIO()
        self.run_install(stream)
        self.assertEqual(stream.getvalue(), "==> Installing Helium from GitHub\n    Downloading helium.tar.xz (120 MB)\n"
                                            " ✓  Installed VacuumTube\nwarning: asked while paused\nerror: something failed\n")

    def test_on_a_terminal_the_messages_go_above_the_bar_which_is_cleared_at_the_end(self):
        stream = _fakes.Terminal()
        self.run_install(stream)
        text = stream.getvalue()
        self.assertEqual(_fakes.screen(text), ["==> Installing Helium from GitHub", "    Downloading helium.tar.xz (120 MB)",
                                               " ✓  Installed VacuumTube", "warning: asked while paused", "error: something failed", ""])
        drawn = [line.split("%", 1)[1] for line in _fakes.bars(text)]
        self.assertIn("(120 MB)\n\r\033[2K███" + "░" * 15 + "  16%  1 of 3 · Helium · 60 of 120 MB", text)
        self.assertEqual([state for index, state in enumerate(drawn) if not index or drawn[index - 1] != state], [
            "  1 of 3 · Helium",
            "  1 of 3 · Helium · 60 of 120 MB",
            "  2 of 3 · YouTube",
            "  2 of 3 · YouTube · part 1 of 2, 100%",
            "  2 of 3 · YouTube · drawn after the pause",
            "  3 of 3 · Steam library",
            "  3 of 3 · Steam library · 5 MB",
        ])
        self.assertTrue(next(line for line in _fakes.bars(text) if "part 1 of 2" in line).startswith("█" * 9 + "░" * 9 + "  50%"))
        self.assertTrue(self.during.endswith("\r\033[2Kwarning: asked while paused\n"))

    def test_no_bar_when_quiet_and_none_inside_another(self):
        stream = _fakes.Terminal()
        with mock.patch.object(ui, "quiet", True), contextlib.redirect_stderr(stream), ui.progress(2):
            ui.step("Helium")
            self.assertFalse(ui.progressing())
        with contextlib.redirect_stderr(stream), ui.progress(2):
            ui.step("Helium")
            with ui.progress(5):
                ui.step("YouTube")
            self.assertTrue(ui.progressing())
        self.assertIn("2 of 2 · YouTube", _fakes.bars(stream.getvalue())[-1])

    def test_a_question_clears_the_bar_and_draws_it_after_the_answer(self):
        stream, asked = _fakes.Terminal(), []

        def tty(path, mode="r", encoding=None):
            asked.append(stream.getvalue())
            return io.StringIO("y\n") if mode == "r" else io.StringIO()

        with contextlib.redirect_stderr(stream), ui.progress(2), mock.patch("builtins.open", side_effect=tty):
            ui.step("Firewall, TV remote and updates")
            self.assertTrue(ui.confirm("Open port 53317?"))
            self.assertTrue(asked[0].endswith("\r\033[2K"))
            self.assertIn("1 of 2 · Firewall", _fakes.screen(stream.getvalue())[-1])

    def test_a_failure_inside_clears_the_bar(self):
        stream = _fakes.Terminal()
        with self.assertRaises(ui.Abort), contextlib.redirect_stderr(stream), ui.progress(2):
            ui.step("KytyPS5")
            raise ui.Abort("KytyPS5 was not installed")
        self.assertEqual(_fakes.screen(stream.getvalue()), [""])
        self.assertFalse(ui.progressing())


if __name__ == "__main__":
    unittest.main()
