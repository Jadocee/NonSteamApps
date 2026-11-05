"""NonSteamApps' own build of Eden-NX2, Eden with early support for Switch 2 games.

Eden-NX2's author publishes Windows builds only, so NonSteamApps builds Eden-NX2's official source, the
``eden-nx2`` branch of :data:`REPOSITORY`, on this machine. It builds with Flathub's KDE SDK, the one
Flathub builds Eden with, into a Flatpak of its own, :data:`APP_ID`: the build is exported to a repository
in NonSteamApps' folder and installed from there into the user installation, so that it runs as Eden from
Flathub does.

Everything the build runs comes from the SDK, in Flatpak's build sandbox: git fetches the source at one
commit, and Eden's build downloads the libraries it bundles, each checked against the SHA-512 recorded in
Eden's ``cpmfile.json``. Those downloads and the compiler's cache are kept for the next build, which
``nonsteamapps update`` starts when the branch has moved. The repository keeps the build before, for
:meth:`Builder.rollback`.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import flatpak, net, ui

APP_ID = "io.github.jadocee.nonsteamapps.EdenNX2"
NAME = "Eden-NX2"
REPOSITORY = "https://git.eden-emu.dev/Takoroka/eden-nx2.git"
BRANCH = "eden-nx2"
SDK = "org.kde.Sdk"
RUNTIME = "org.kde.Platform"
RUNTIME_VERSION = "6.11"
REMOTE = "nonsteamapps"
FLATPAK_BRANCH = "stable"
KEEP = 2
RECORD = "builds.json"
LOG = "build.log"
BUILD_SPACE = 2 << 30
SDK_SPACE = 4 << 30
JOB_MEMORY = 2 << 30
SANDBOX = "/run/nonsteamapps"
EDEN_ID = "dev.eden_emu.eden"
CPM_CACHE = ".cache/cpm"
CONFIGURE = (
    "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release",
    "-DCMAKE_INSTALL_PREFIX=/app",
    "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
    "-DBUILD_TESTING=OFF",
    "-DYUZU_TESTS=OFF",
    "-DENABLE_WERROR=OFF",
    "-DENABLE_QT_TRANSLATION=ON",
    "-DENABLE_UPDATE_CHECKER=OFF",
    "-DUSE_DISCORD_PRESENCE=OFF",
    "-DYUZU_CMD=OFF",
    "-DYUZU_ROOM_STANDALONE=OFF",
    "-DYUZU_USE_BUNDLED_QT=OFF",
    "-DYUZU_USE_QT_MULTIMEDIA=OFF",
    "-DYUZU_USE_QT_WEB_ENGINE=OFF",
    "-DYUZU_USE_BUNDLED_FFMPEG=OFF",
    "-DYUZU_USE_BUNDLED_SDL3=OFF",
    "-DYUZU_USE_BUNDLED_SIRIT=OFF",
    "-DYUZU_USE_BUNDLED_OPENSSL=OFF",
    "-DYUZU_DISABLE_LLVM=ON",
    "-DYUZU_STATIC_BUILD=OFF",
    "-DNIGHTLY_BUILD=OFF",
    "-DVulkanHeaders_FORCE_BUNDLED=ON",
)
FINISH = (
    "--command=eden",
    "--device=all",
    "--socket=wayland",
    "--socket=fallback-x11",
    "--socket=pulseaudio",
    "--share=network",
    "--share=ipc",
    "--env=QT_QPA_PLATFORM=xcb;wayland",
)
X86_64_V3 = ("avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_FLATPAK_COMMIT = re.compile(r"[0-9a-f]{64}\Z")
_PROGRESS = re.compile(r"\[(\d+)/(\d+)\]")


class NX2Error(RuntimeError):
    """Eden-NX2 could not be fetched, built, installed or switched."""


@dataclass(frozen=True)
class Build:
    """One build of Eden-NX2: the source ``commit`` it was built from, and ``flatpak``, the commit it became in the repository."""

    commit: str
    date: str = ""
    subject: str = ""
    flatpak: str = ""
    built: str = ""


def describe(build: Optional[Build]) -> str:
    """A build as people read it: its source commit and that commit's date."""
    if build is None:
        return "not built"
    if not build.commit:
        return "from a build NonSteamApps has no record of"
    return build.commit[:8] + (f" ({build.date[:10]})" if build.date else "")


def remote_refs(repository: str, fetch: Optional[Callable[[str], bytes]] = None) -> Dict[str, str]:
    """The branches and tags of a git ``repository``, as its server advertises them over HTTP."""
    data = (fetch or net.fetch_bytes)(f"{repository}/info/refs?service=git-upload-pack")
    refs: Dict[str, str] = {}
    position = 0
    while position + 4 <= len(data):
        try:
            length = int(data[position:position + 4], 16)
        except ValueError as exc:
            raise NX2Error(f"{repository} did not answer as a git repository") from exc
        if length < 4:
            position += 4
            continue
        line = data[position + 4:position + length].split(b"\0", 1)[0].decode("utf-8", "replace").rstrip("\n")
        position += length
        commit, _, name = line.partition(" ")
        if _COMMIT.match(commit) and name:
            refs[name] = commit
    return refs


def jobs(cpus: Optional[int] = None, meminfo: Path = Path("/proc/meminfo")) -> int:
    """How many compilers to run at once: one for each processor, while each has about 2 GB of free memory."""
    cpus = cpus or os.cpu_count() or 1
    try:
        values = dict(line.split(":", 1) for line in Path(meminfo).read_text(encoding="utf-8").splitlines() if ":" in line)
        available = int(values["MemAvailable"].split()[0]) * 1024
    except (OSError, KeyError, ValueError, IndexError):
        return max(1, min(cpus, 4))
    return max(1, min(cpus, available // JOB_MEMORY))


def compiler_flags(cpuinfo: Path = Path("/proc/cpuinfo")) -> str:
    """Flags for the compiler: x86-64-v3, as Flathub builds Eden, on a processor that has it."""
    try:
        text = Path(cpuinfo).read_text(encoding="utf-8")
    except OSError:
        return "-pipe"
    found = next((set(line.split(":", 1)[1].split()) for line in text.splitlines() if line.startswith("flags")), set())
    return "-march=x86-64-v3 -mtune=generic -pipe" if all(flag in found for flag in X86_64_V3) else "-pipe"


def rename_exports(files: Path) -> List[Path]:
    """Give Eden's menu entry and icons the Flatpak's own name, which Flatpak exports, and drop what would claim Eden's file types.

    Eden from Flathub stays the program that opens Switch files; Eden-NX2's entry only starts it.
    """
    renamed: List[Path] = []
    for path in sorted((Path(files) / "share").rglob(f"{EDEN_ID}.*")):
        if path.parent.name == "metainfo" or path.parent.parent.name == "mime":
            path.unlink()
            continue
        target = path.with_name(APP_ID + path.name[len(EDEN_ID):])
        if path.suffix == ".desktop":
            text = re.sub(r"(?m)^(Name|Comment)\[[^\]]*\]=.*\n|^MimeType=.*\n", "", path.read_text(encoding="utf-8"))
            text = re.sub(r"(?m)^Name=.*$", f"Name={NAME}", text, count=1)
            text = re.sub(r"(?m)^Comment=.*$", "Comment=Eden with early support for Switch 2 games, built by NonSteamApps from its source", text, count=1)
            target.write_text(re.sub(r"(?m)^Icon=.*$", f"Icon={APP_ID}", text), encoding="utf-8")
            path.unlink()
        else:
            path.rename(target)
        renamed.append(target)
    return renamed


def _show_progress(line: str, shown: Tuple[int, int]) -> Tuple[int, int]:
    """Show each tenth of Ninja's steps done, from a line of its output; ``shown`` is the steps it counts and the tenth last shown."""
    match = _PROGRESS.match(line)
    if not match:
        return shown
    done, total = int(match.group(1)), int(match.group(2))
    last = shown[1] if total == shown[0] else 0
    step = done * 100 // max(total, 1) // 10 * 10
    if step > last:
        ui.info(f"  {NAME} is {step}% built ({done} of {total} steps)")
        return total, step
    return total, last


class Builder:
    """Eden-NX2's source, builds and caches under ``root``, and the Flatpak built from them.

    ``sandbox_options`` are added to every command run in the build sandbox, for a machine that needs more
    in there than the SDK, such as a proxy's settings.
    """

    def __init__(self, root: Path, command: str = "flatpak", repository: str = REPOSITORY, branch: str = BRANCH,
                 sandbox_options: Sequence[str] = ()) -> None:
        self.root = Path(root)
        self.command = command
        self.repository = repository
        self.branch = branch
        self.sandbox_options = list(sandbox_options)

    @property
    def source(self) -> Path:
        return self.root / "source"

    @property
    def work(self) -> Path:
        return self.root / "build"

    @property
    def stage(self) -> Path:
        return self.root / "app"

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @property
    def cpm(self) -> Path:
        return self.root / "cpm"

    @property
    def ccache(self) -> Path:
        return self.root / "ccache"

    @property
    def log(self) -> Path:
        return self.root / LOG

    @property
    def record(self) -> Path:
        return self.root / RECORD

    def builds(self) -> List[Build]:
        """The builds the repository keeps, newest first."""
        try:
            data = json.loads(self.record.read_text(encoding="utf-8"))
            names = [field.name for field in fields(Build)]
            return [Build(**{name: str(entry.get(name, "")) for name in names}) for entry in data.get("builds", [])]
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def _save(self, builds: Sequence[Build]) -> None:
        partial = self.record.with_name(self.record.name + ".new")
        partial.write_text(json.dumps({"builds": [asdict(build) for build in builds]}, indent=1) + "\n", encoding="utf-8")
        os.replace(partial, self.record)

    def installed_commit(self) -> str:
        """The repository commit of the installed Flatpak, or "" when it is not installed."""
        result = self._output("info", "--user", "--show-commit", APP_ID)
        return result if _FLATPAK_COMMIT.match(result) else ""

    def current(self) -> Optional[Build]:
        """The installed build, or ``None`` when Eden-NX2's Flatpak is not installed."""
        installed = self.installed_commit()
        if not installed:
            return None
        return next((build for build in self.builds() if build.flatpak == installed), Build(commit="", flatpak=installed))

    def latest(self) -> str:
        """The newest commit on the branch."""
        try:
            refs = remote_refs(self.repository)
        except OSError as exc:
            raise NX2Error(f"could not reach {self.repository}: {exc}") from exc
        commit = refs.get(f"refs/heads/{self.branch}")
        if not commit:
            raise NX2Error(f"{self.repository} has no branch {self.branch}")
        return commit

    def update(self) -> Optional[Build]:
        """Install the branch's newest commit, built here unless the repository keeps it; return it, or ``None`` when it is installed."""
        latest = self.latest()
        current = self.current()
        if current and current.commit == latest:
            return None
        kept = next((build for build in self.builds() if build.commit == latest), None)
        if kept and self._deploy(kept):
            return kept
        return self.build(latest)

    def rollback(self) -> Build:
        """Install the other build the repository keeps, and keep Flatpak from updating it."""
        current = self.current()
        others = [build for build in self.builds() if current and build.flatpak != current.flatpak]
        if not others:
            raise NX2Error(f"there is no other build of {NAME} to switch to")
        self._call("update", "--user", "--noninteractive", "-y", f"--commit={others[0].flatpak}", APP_ID)
        self._call("mask", "--user", APP_ID, check=False)
        return others[0]

    def remove(self) -> None:
        """Forget the repository and delete the source, builds and caches; the Flatpak itself is uninstalled as other apps are."""
        self._call("mask", "--user", "--remove", APP_ID, check=False, log=False)
        self._call("remote-delete", "--user", "--force", REMOTE, check=False, log=False)
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, commit: str) -> Build:
        """Fetch ``commit``, build it, export it to the repository and install it from there."""
        if not _COMMIT.match(commit):
            raise NX2Error(f"{commit!r} is not a full git commit")
        self.root.mkdir(parents=True, exist_ok=True)
        with _Lock(self.root / ".lock"):
            missing = [f"{ref}//{RUNTIME_VERSION}" for ref in (SDK, RUNTIME) if not self._has(f"{ref}//{RUNTIME_VERSION}")]
            needed = BUILD_SPACE + (SDK_SPACE if missing else 0)
            free = shutil.disk_usage(self.root).free
            if free < needed:
                raise NX2Error(f"building {NAME} needs about {needed >> 30} GB free in {self.root}; there are {free / (1 << 30):.1f} GB")
            self.log.write_text("", encoding="utf-8")
            started = time.monotonic()
            try:
                self._prepare(missing)
                build = self._fetch(commit)
                count = jobs()
                ui.info(f"Building {NAME} {describe(build)} with {count} jobs at once; this can take an hour, and the log is {self.log}")
                self._sdk("cmake", "-S", f"{SANDBOX}/source", "-B", f"{SANDBOX}/build", *CONFIGURE, network=True)
                self._sdk("cmake", "--build", f"{SANDBOX}/build", "--parallel", str(count), progress=True)
                self._sdk("cmake", "--install", f"{SANDBOX}/build")
                rename_exports(self.stage / "files")
                if not os.access(self.stage / "files" / "bin" / "eden", os.X_OK):
                    raise NX2Error("the build installed no eden program")
                self._call("build-finish", str(self.stage), *FINISH)
                subject = f"{NAME} {build.commit[:8]}" + (f": {build.subject}" if build.subject else "")
                self._call("build-export", f"--subject={subject}", str(self.repo), str(self.stage), FLATPAK_BRANCH)
                self._call("build-update-repo", "--prune", f"--prune-depth={KEEP - 1}", str(self.repo))
                built = Build(build.commit, build.date, build.subject, self._repo_commit(), time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                self._save([built, *[old for old in self.builds() if old.flatpak != built.flatpak]][:KEEP])
                if not self._deploy(built):
                    raise NX2Error(f"{APP_ID} was exported to {self.repo} but not installed from it")
            except NX2Error as exc:
                raise NX2Error(f"{exc}{self._tail()}") from None
            finally:
                shutil.rmtree(self.stage, ignore_errors=True)
                shutil.rmtree(self.work, ignore_errors=True)
            minutes = round((time.monotonic() - started) / 60)
            ui.info(f"Built {NAME} {describe(built)} in {minutes} minute{'' if minutes == 1 else 's'}")
            return built

    def _deploy(self, build: Build) -> bool:
        """Install ``build`` from the repository, or switch the installed Flatpak to it; return whether it is the one installed."""
        if not build.flatpak or not self.repo.is_dir():
            return False
        self._call("remote-add", "--user", "--if-not-exists", "--no-gpg-verify", f"--title=NonSteamApps: {NAME} built here", REMOTE, str(self.repo))
        self._call("remote-modify", "--user", f"--url=file://{self.repo}", REMOTE)
        self._call("mask", "--user", "--remove", APP_ID, check=False)
        if self.installed_commit():
            self._call("update", "--user", "--noninteractive", "-y", f"--commit={build.flatpak}", APP_ID)
        else:
            self._call("install", "--user", "--noninteractive", "-y", REMOTE, APP_ID)
        return self.installed_commit() == build.flatpak

    def _repo_commit(self) -> str:
        arch = self._output("--default-arch")
        try:
            commit = (self.repo / "refs" / "heads" / "app" / APP_ID / arch / FLATPAK_BRANCH).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise NX2Error(f"the repository has no {APP_ID} after the export: {exc}") from exc
        if not _FLATPAK_COMMIT.match(commit):
            raise NX2Error(f"the repository holds an unexpected commit for {APP_ID}: {commit!r}")
        return commit

    def _has(self, ref: str) -> bool:
        return subprocess.run([self.command, "info", ref], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False).returncode == 0

    def _prepare(self, missing: Sequence[str]) -> None:
        """Install the SDK and runtime that no installation has, then start a fresh build folder."""
        if missing:
            ui.info(f"Installing {' and '.join(missing)} from Flathub, which the build needs")
            self._call("remote-add", "--user", "--if-not-exists", flatpak.REMOTE, flatpak.REMOTE_URL)
            self._call("install", "--user", "--noninteractive", "-y", flatpak.REMOTE, *missing)
        shutil.rmtree(self.stage, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)
        for folder in (self.work, self.cpm, self.ccache):
            folder.mkdir(parents=True, exist_ok=True)
        self._call("build-init", str(self.stage), APP_ID, SDK, RUNTIME, RUNTIME_VERSION)

    def _fetch(self, commit: str) -> Build:
        """Fetch only ``commit``, with the SDK's git, into a fresh source folder."""
        shutil.rmtree(self.source, ignore_errors=True)
        (self.source / CPM_CACHE).mkdir(parents=True)
        ui.info(f"Fetching {NAME}'s source at {commit[:8]} from {self.repository}")
        git = ("git", "-C", f"{SANDBOX}/source")
        self._sdk(*git, "init", "-q")
        self._sdk(*git, "fetch", "-q", "--depth", "1", self.repository, commit, network=True)
        self._sdk(*git, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "FETCH_HEAD")
        found, date, subject = (self._sdk(*git, "log", "-1", "--format=%H%x00%cI%x00%s", capture=True).strip().split("\0") + ["", ""])[:3]
        if found != commit:
            raise NX2Error(f"git checked out {found[:12] or 'nothing'} instead of {commit[:12]}")
        return Build(commit, date, subject)

    def _sandbox(self, network: bool) -> List[str]:
        flags = compiler_flags()
        options = [
            "--die-with-parent",
            f"--bind-mount={SANDBOX}/source={self.source}",
            f"--bind-mount={SANDBOX}/source/{CPM_CACHE}={self.cpm}",
            f"--bind-mount={SANDBOX}/build={self.work}",
            f"--bind-mount={SANDBOX}/ccache={self.ccache}",
            f"--build-dir={SANDBOX}/build",
            f"--env=CCACHE_DIR={SANDBOX}/ccache",
            "--env=CCACHE_MAXSIZE=1G",
            f"--env=CFLAGS={flags}",
            f"--env=CXXFLAGS={flags}",
            *self.sandbox_options,
        ]
        return options + (["--share=network"] if network else [])

    def _sdk(self, *command: str, network: bool = False, progress: bool = False, capture: bool = False) -> str:
        """Run ``command`` in the build sandbox, with the SDK, logging its output; return the output when ``capture``."""
        return self._logged([self.command, "build", *self._sandbox(network), str(self.stage), *command], " ".join(command[:2]),
                            progress=progress, capture=capture)

    def _call(self, *arguments: str, check: bool = True, log: bool = True) -> None:
        self._logged([self.command, *arguments], f"flatpak {arguments[0]}", check=check, log=log)

    def _output(self, *arguments: str) -> str:
        try:
            result = subprocess.run([self.command, *arguments], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        except OSError:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def _logged(self, arguments: List[str], label: str, check: bool = True, progress: bool = False, capture: bool = False,
                log: bool = True) -> str:
        output = open(self.log, "a", encoding="utf-8") if log else open(os.devnull, "w", encoding="utf-8")
        with output:
            output.write("$ " + " ".join(arguments) + "\n")
            output.flush()
            try:
                process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, errors="replace")
            except OSError as exc:
                raise NX2Error(f"could not run {arguments[0]}: {exc}") from exc
            captured: List[str] = []
            shown = (0, 0)
            with process:
                for line in process.stdout:
                    output.write(line)
                    if capture:
                        captured.append(line)
                    if progress:
                        shown = _show_progress(line, shown)
                status = process.wait()
        if status != 0 and check:
            raise NX2Error(f"{label} failed with exit status {status}")
        return "".join(captured)

    def _tail(self, lines: int = 20) -> str:
        try:
            text = self.log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return f"\nThe end of {self.log}:\n" + "\n".join(f"  {line}" for line in text[-lines:])


class _Lock:
    """One build at a time: an exclusive lock on a file, given up when the build ends."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_Lock":
        self.handle = open(self.path, "w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise NX2Error(f"another build of {NAME} is running") from None
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
