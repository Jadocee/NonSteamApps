import ctypes
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

import _paths  # noqa: F401
from nonsteamapps import x11

LIB = x11.library()


class MatchingTests(unittest.TestCase):
    def test_only_shown_windows_of_the_class_are_made_full_screen_once(self):
        windows = [
            (1, "nonsteamapps-helium", "Nonsteamapps-helium", True, 0),
            (2, "helium", "nonsteamapps-helium", True, 0),
            (3, "nonsteamapps-helium", "x", False, 0),
            (4, "element", "Element", True, 0),
        ]
        self.assertEqual(x11.matching(windows, "nonsteamapps-helium", set()), [1, 2])
        self.assertEqual(x11.matching(windows, "nonsteamapps-helium", {1}), [2])

    def test_dialogs_keep_their_size_but_a_main_window_transient_for_a_hidden_leader_does_not(self):
        windows = [
            (10, "leader", "nonsteamapps-kytyps5", False, 0),
            (11, "nonsteamapps-kytyps5", "Kyty_launcher", True, 10),
            (12, "nonsteamapps-kytyps5", "Kyty_launcher", True, 11),
            (13, "nonsteamapps-kytyps5", "nonsteamapps-kytyps5", True, 0),
        ]
        self.assertEqual(x11.matching(windows, "nonsteamapps-kytyps5", set()), [11, 13])

    def test_a_process_runs_until_it_has_exited(self):
        self.assertTrue(x11.running(os.getpid()))
        child = subprocess.Popen(["true"])
        while x11.running(child.pid):
            time.sleep(0.01)
        child.wait()
        self.assertFalse(x11.running(child.pid))

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "Xlib's 64-bit layout")
    def test_structures_match_xlibs_layout(self):
        self.assertEqual((ctypes.sizeof(x11.Attributes), ctypes.sizeof(x11.Event), ctypes.sizeof(x11.ClientMessage)), (136, 192, 96))

    def test_without_libx11_or_a_display_nothing_happens(self):
        self.assertEqual(x11.keep_fullscreen("nonsteamapps-helium", lambda: True, display=":424242"), 0)


class SetClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_char_p), ("res_class", ctypes.c_char_p)]


@unittest.skipUnless(LIB and shutil.which("Xvfb"), "needs libX11 and Xvfb")
class XServerTests(unittest.TestCase):
    def setUp(self):
        number = next(n for n in range(90, 200) if not Path(f"/tmp/.X{n}-lock").exists() and not Path(f"/tmp/.X11-unix/X{n}").exists())
        self.name = f":{number}"
        self.server = subprocess.Popen(["Xvfb", self.name, "-nolisten", "tcp", "-screen", "0", "1280x720x24"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_server)
        LIB.XOpenDisplay.restype = ctypes.c_void_p
        deadline = time.monotonic() + 10
        self.display = None
        while not self.display and time.monotonic() < deadline:
            time.sleep(0.05)
            self.display = LIB.XOpenDisplay(self.name.encode())
        self.assertTrue(self.display, "Xvfb did not start")
        self.addCleanup(LIB.XCloseDisplay, self.display)
        self.root = LIB.XDefaultRootWindow(self.display)

    def stop_server(self):
        self.server.terminate()
        self.server.wait(timeout=10)

    def make_window(self, name, kind, transient_for=0):
        LIB.XCreateSimpleWindow.restype = ctypes.c_ulong
        LIB.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                            ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
        LIB.XSetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(SetClassHint)]
        LIB.XSetTransientForHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        LIB.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        window = LIB.XCreateSimpleWindow(self.display, self.root, 0, 0, 640, 360, 0, 0, 0)
        LIB.XSetClassHint(self.display, window, ctypes.byref(SetClassHint(name.encode(), kind.encode())))
        if transient_for:
            LIB.XSetTransientForHint(self.display, window, transient_for)
        LIB.XMapWindow(self.display, window)
        LIB.XSync(self.display, 0)
        return window

    def test_each_window_of_the_class_is_asked_once_to_go_full_screen(self):
        LIB.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
        LIB.XPending.argtypes = [ctypes.c_void_p]
        LIB.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(x11.Event)]
        LIB.XSelectInput(self.display, self.root, x11.SUBSTRUCTURE_NOTIFY)
        browser = self.make_window("nonsteamapps-helium", "Nonsteamapps-helium")
        self.make_window("element", "Element")
        self.make_window("nonsteamapps-helium", "Nonsteamapps-helium", transient_for=browser)
        passes = iter(range(6))
        self.assertEqual(x11.keep_fullscreen("nonsteamapps-helium", lambda: next(passes, None) is not None, 0.02, self.name), 1)
        LIB.XSync(self.display, 0)
        requests = []
        event = x11.Event()
        while LIB.XPending(self.display):
            LIB.XNextEvent(self.display, ctypes.byref(event))
            if event.type == x11.CLIENT_MESSAGE:
                message = event.xclient
                requests.append((message.window, message.message_type, message.format, list(message.data)[:4]))
        state = LIB.XInternAtom(self.display, b"_NET_WM_STATE", 0)
        fullscreen = LIB.XInternAtom(self.display, b"_NET_WM_STATE_FULLSCREEN", 0)
        self.assertEqual(requests, [(browser, state, 32, [x11.ADD, fullscreen, 0, x11.FROM_APPLICATION])])


if __name__ == "__main__":
    unittest.main()
