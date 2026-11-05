import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
import _paths  # noqa: F401
from nonsteamapps import nx2

COMMIT = _fakes.NX2_COMMIT
NEWER = _fakes.NX2_NEWER
THIRD = "3" * 40
REPOSITORY = "https://git.example.org/someone/eden-nx2.git"


def packet(text: bytes) -> bytes:
    return b"%04x" % (len(text) + 4) + text


def advertisement(*refs) -> bytes:
    """What a git server sends for ``info/refs?service=git-upload-pack``: the service, a flush, the refs and a flush."""
    lines = [f"{commit} {name}".encode() + (b"\0multi_ack side-band-64k ofs-delta" if index == 0 else b"") + b"\n"
             for index, (commit, name) in enumerate(refs)]
    return packet(b"# service=git-upload-pack\n") + b"0000" + b"".join(packet(line) for line in lines) + b"0000"


class RefsTests(unittest.TestCase):
    def test_the_branch_head_comes_from_gits_http_advertisement(self):
        asked = []
        data = advertisement((COMMIT, "HEAD"), (COMMIT, "refs/heads/eden-nx2"), (NEWER, "refs/heads/master"),
                             (THIRD, "refs/tags/nx2-2026-10-29"), (NEWER, "refs/tags/nx2-2026-10-29^{}"))
        refs = nx2.remote_refs(REPOSITORY, fetch=lambda url: asked.append(url) or data)
        self.assertEqual(asked, [f"{REPOSITORY}/info/refs?service=git-upload-pack"])
        self.assertEqual(refs["refs/heads/eden-nx2"], COMMIT)
        self.assertEqual((refs["HEAD"], refs["refs/tags/nx2-2026-10-29^{}"]), (COMMIT, NEWER))
        self.assertEqual(len(refs), 5)

    def test_an_answer_that_is_not_git_is_refused(self):
        with self.assertRaisesRegex(nx2.NX2Error, "did not answer as a git repository"):
            nx2.remote_refs(REPOSITORY, fetch=lambda url: b"<html><body>Just a moment...</body></html>")
        self.assertEqual(nx2.remote_refs(REPOSITORY, fetch=lambda url: b""), {})

    def test_the_newest_commit_is_the_branchs_and_a_missing_branch_is_an_error(self):
        builder = nx2.Builder(Path("/nonexistent"), repository=REPOSITORY)
        with mock.patch("nonsteamapps.nx2.remote_refs", return_value={"refs/heads/eden-nx2": NEWER, "refs/heads/master": COMMIT}):
            self.assertEqual(builder.latest(), NEWER)
        with mock.patch("nonsteamapps.nx2.remote_refs", return_value={"refs/heads/master": COMMIT}), \
                self.assertRaisesRegex(nx2.NX2Error, "has no branch eden-nx2"):
            builder.latest()
        with mock.patch("nonsteamapps.nx2.remote_refs", side_effect=OSError("timed out")), \
                self.assertRaisesRegex(nx2.NX2Error, "could not reach"):
            builder.latest()


class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = Path(self.tmp.name) / name
        path.write_text(text)
        return path

    def test_each_compiler_gets_about_two_gigabytes_of_free_memory(self):
        for available, cpus, wanted in ((12 << 20, 12, 6), (12 << 20, 4, 4), (3 << 20, 12, 1), (512 << 10, 12, 1)):
            with self.subTest(available=available, cpus=cpus):
                meminfo = self.write("meminfo", f"MemTotal:       16000000 kB\nMemAvailable:   {available} kB\n")
                self.assertEqual(nx2.jobs(cpus, meminfo), wanted)
        self.assertEqual(nx2.jobs(12, Path(self.tmp.name) / "missing"), 4)

    def test_x86_64_v3_only_on_a_processor_that_has_it(self):
        flags = "fpu sse4_2 avx avx2 bmi1 bmi2 f16c fma abm movbe xsave popcnt"
        self.assertEqual(nx2.compiler_flags(self.write("cpuinfo", f"processor\t: 0\nflags\t\t: {flags}\n")), "-march=x86-64-v3 -mtune=generic -pipe")
        self.assertEqual(nx2.compiler_flags(self.write("cpuinfo", f"flags\t\t: {flags.replace(' avx2', '')}\n")), "-pipe")
        self.assertEqual(nx2.compiler_flags(Path(self.tmp.name) / "missing"), "-pipe")

    def test_a_build_reads_as_its_commit_and_date(self):
        self.assertEqual(nx2.describe(nx2.Build(COMMIT, "2026-10-29T19:23:21-04:00")), "50fa86bb (2026-10-29)")
        self.assertEqual(nx2.describe(nx2.Build(COMMIT)), "50fa86bb")
        self.assertEqual(nx2.describe(nx2.Build("", flatpak="f" * 64)), "from a build NonSteamApps has no record of")
        self.assertEqual(nx2.describe(None), "not built")

    def test_edens_menu_entry_and_icons_take_the_flatpaks_name_and_its_file_types_go(self):
        files = Path(self.tmp.name) / "files"
        for name, text in _fakes_eden_files().items():
            path = files / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        renamed = nx2.rename_exports(files)
        share = files / "share"
        self.assertEqual(sorted(path.relative_to(share).as_posix() for path in renamed), [
            f"applications/{nx2.APP_ID}.desktop", f"icons/hicolor/scalable/apps/{nx2.APP_ID}.svg",
        ])
        self.assertEqual((share / "applications" / f"{nx2.APP_ID}.desktop").read_text(), (
            "[Desktop Entry]\nName=Eden-NX2\nComment=Eden with early support for Switch 2 games, built by NonSteamApps from its source\n"
            f"Exec=eden %f\nIcon={nx2.APP_ID}\nStartupWMClass=eden\n"
        ))
        self.assertEqual(sorted(path.relative_to(share).as_posix() for path in share.rglob("*") if path.is_file()), [
            f"applications/{nx2.APP_ID}.desktop", f"icons/hicolor/scalable/apps/{nx2.APP_ID}.svg",
        ])


def _fakes_eden_files():
    return {
        "share/applications/dev.eden_emu.eden.desktop": (
            "[Desktop Entry]\nName=Eden\nName[de]=Eden\nComment=Multiplatform FOSS Switch 1 emulator\nComment[de]=Emulator\nExec=eden %f\n"
            "Icon=dev.eden_emu.eden\nMimeType=application/x-nx-nsp;application/x-nx-xci;\nStartupWMClass=eden\n"
        ),
        "share/icons/hicolor/scalable/apps/dev.eden_emu.eden.svg": "<svg/>",
        "share/metainfo/dev.eden_emu.eden.metainfo.xml": "<component/>",
        "share/mime/packages/dev.eden_emu.eden.xml": "<mime-info/>",
    }


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = _fakes.FakeFlatpak(Path(self.tmp.name))
        self.branch = COMMIT
        for patch in (
            mock.patch.dict(os.environ, self.fake.env),
            mock.patch("nonsteamapps.nx2.remote_refs", side_effect=lambda repository, fetch=None: {"refs/heads/eden-nx2": self.branch}),
            mock.patch.multiple("nonsteamapps.nx2", BUILD_SPACE=0, SDK_SPACE=0),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.root = Path(self.tmp.name) / "eden-nx2"
        self.builder = nx2.Builder(self.root, self.fake.command)

    def quietly(self, action, *args):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = action(*args)
        self.errors = errors.getvalue()
        return result

    def sandboxed(self):
        """The commands run in the build sandbox, each with its sandbox options."""
        calls = []
        for call in self.fake.calls("build"):
            folder = next(index for index, argument in enumerate(call[1:], 1) if not argument.startswith("-"))
            calls.append((call[1:folder], call[folder + 1:]))
        return calls

    def test_a_build_fetches_one_commit_builds_it_with_the_sdk_and_installs_it_from_its_repository(self):
        build = self.quietly(self.builder.build, COMMIT)
        self.assertEqual((build.commit, build.date, build.subject), (COMMIT, "2026-10-29T19:23:21-04:00", "nx2: a change"))
        self.assertEqual(
            [call[0] for call in self.fake.calls() if call[0] not in ("info", "build", "--default-arch")],
            ["remote-add", "install", "build-init", "build-finish", "build-export", "build-update-repo",
             "remote-add", "remote-modify", "mask", "install"],
        )
        self.assertEqual(self.fake.calls("install")[0], ["install", "--user", "--noninteractive", "-y", "flathub", "org.kde.Sdk//6.11",
                                                         "org.kde.Platform//6.11"])
        self.assertEqual(self.fake.calls("build-init")[0][1:], [str(self.root / "app"), nx2.APP_ID, "org.kde.Sdk", "org.kde.Platform", "6.11"])
        sandboxed = self.sandboxed()
        self.assertEqual([command[:4] for _, command in sandboxed], [
            ["git", "-C", "/run/nonsteamapps/source", "init"],
            ["git", "-C", "/run/nonsteamapps/source", "fetch"],
            ["git", "-C", "/run/nonsteamapps/source", "-c"],
            ["git", "-C", "/run/nonsteamapps/source", "log"],
            ["cmake", "-S", "/run/nonsteamapps/source", "-B"],
            ["cmake", "--build", "/run/nonsteamapps/build", "--parallel"],
            ["cmake", "--install", "/run/nonsteamapps/build"],
        ])
        self.assertEqual(sandboxed[1][1][-2:], [nx2.REPOSITORY, COMMIT])
        self.assertEqual([index for index, (options, _) in enumerate(sandboxed) if "--share=network" in options], [1, 4])
        self.assertEqual(sandboxed[4][1][5:], list(nx2.CONFIGURE))
        options = sandboxed[5][0]
        for mount in (f"--bind-mount=/run/nonsteamapps/source={self.root / 'source'}", f"--bind-mount=/run/nonsteamapps/source/.cache/cpm={self.root / 'cpm'}",
                      f"--bind-mount=/run/nonsteamapps/build={self.root / 'build'}", f"--bind-mount=/run/nonsteamapps/ccache={self.root / 'ccache'}",
                      "--env=CCACHE_DIR=/run/nonsteamapps/ccache", "--die-with-parent"):
            self.assertIn(mount, options)
        self.assertEqual(self.fake.calls("build-finish")[0][2:], list(nx2.FINISH))
        export = self.fake.calls("build-export")[0]
        self.assertEqual(export[1:], [f"--subject=Eden-NX2 {COMMIT[:8]}: nx2: a change", str(self.root / "repo"), str(self.root / "app"), "stable"])
        self.assertEqual(self.fake.calls("install")[-1], ["install", "--user", "--noninteractive", "-y", "nonsteamapps", nx2.APP_ID])
        self.assertEqual(self.fake.apps()[nx2.APP_ID]["commit"], build.flatpak)
        self.assertEqual((self.builder.current(), self.builder.builds()), (build, [build]))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), [".lock", "build.log", "builds.json", "ccache", "cpm", "repo", "source"])
        self.assertIn("Fetching Eden-NX2's source at 50fa86bb", self.errors)
        self.assertIn("Eden-NX2 is 50% built (2 of 4 steps)", self.errors)
        self.assertIn("Eden-NX2 is 100% built (4 of 4 steps)", self.errors)
        self.assertNotIn("of 2 steps", self.errors)
        self.assertIn("$ flatpak build", self.builder.log.read_text().replace(self.fake.command, "flatpak"))

    def test_an_sdk_already_installed_is_used_as_it_is(self):
        self.fake.state.write_text('{"apps": {}, "runtimes": ["org.kde.Sdk//6.11", "org.kde.Platform//6.11"]}')
        self.quietly(self.builder.build, COMMIT)
        self.assertEqual([call[-1] for call in self.fake.calls("install")], [nx2.APP_ID])
        self.assertEqual(self.fake.calls("remote-add")[0][-2], "nonsteamapps")

    def test_a_failed_step_keeps_the_build_installed_and_shows_the_end_of_the_log(self):
        first = self.quietly(self.builder.build, COMMIT)
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_BUILD_FAIL": "cmake --build"}), \
                self.assertRaisesRegex(nx2.NX2Error, r"(?s)cmake --build failed with exit status 1\nThe end of .*build.log:.*ninja: build stopped"):
            self.quietly(self.builder.build, NEWER)
        self.assertEqual((self.builder.current(), self.builder.builds()), (first, [first]))
        self.assertFalse((self.root / "app").exists() or (self.root / "build").exists())
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_GIT_HEAD": THIRD}), self.assertRaisesRegex(nx2.NX2Error, "git checked out 333333333333 instead of c0ffee00d15e"):
            self.quietly(self.builder.build, NEWER)

    def test_update_builds_only_when_the_branch_moves_and_rollback_switches_between_the_two_builds_kept(self):
        first = self.quietly(self.builder.update)
        self.assertIsNone(self.quietly(self.builder.update))
        self.branch = NEWER
        second = self.quietly(self.builder.update)
        self.assertEqual((second.commit, self.builder.builds()), (NEWER, [second, first]))
        self.assertEqual(self.quietly(self.builder.rollback), first)
        self.assertEqual((self.builder.current(), self.fake.state_value("masked")), (first, [nx2.APP_ID]))
        exports = len(self.fake.calls("build-export"))
        self.assertEqual(self.quietly(self.builder.update), second)
        self.assertEqual((len(self.fake.calls("build-export")), self.fake.state_value("masked")), (exports, []))
        self.quietly(self.builder.rollback)
        self.branch = THIRD
        third = self.quietly(self.builder.update)
        self.assertEqual((self.builder.current(), self.builder.builds()), (third, [third, second]))
        self.assertEqual(self.fake.calls("build-update-repo")[-1][1:3], ["--prune", "--prune-depth=1"])

    def test_rollback_needs_another_build_and_only_full_commits_are_built(self):
        with self.assertRaisesRegex(nx2.NX2Error, "no other build"):
            self.builder.rollback()
        self.quietly(self.builder.build, COMMIT)
        with self.assertRaisesRegex(nx2.NX2Error, "no other build"):
            self.builder.rollback()
        with self.assertRaisesRegex(nx2.NX2Error, "is not a full git commit"):
            self.builder.build(COMMIT[:8])

    def test_one_build_at_a_time_and_only_with_room_for_it(self):
        self.root.mkdir()
        with nx2._Lock(self.root / ".lock"), self.assertRaisesRegex(nx2.NX2Error, "another build of Eden-NX2 is running"):
            self.builder.build(COMMIT)
        with mock.patch.multiple("nonsteamapps.nx2", BUILD_SPACE=1 << 60), self.assertRaisesRegex(nx2.NX2Error, r"needs about \d+ GB free"):
            self.builder.build(COMMIT)
        self.assertEqual(self.fake.calls("build-init"), [])

    def test_removing_forgets_the_repository_and_deletes_everything_built(self):
        self.quietly(self.builder.build, COMMIT)
        self.builder.remove()
        self.assertFalse(self.root.exists())
        self.assertEqual(self.fake.calls("remote-delete"), [["remote-delete", "--user", "--force", "nonsteamapps"]])


if __name__ == "__main__":
    unittest.main()
