#!/usr/bin/env bash
# NonSteamApps' tests on SteamOS's own packages, in the SteamOS image: the unit tests on its Python, then the
# sandboxed install. The versions they ran on come first.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.."

echo "==> SteamOS ${STEAMOS_RELEASE:-?} packages: $(python3 --version), $(flatpak --version), bubblewrap $(bwrap --version | cut -d' ' -f2), $(chromium --version | cut -d' ' -f1-2)"
echo "==> unit tests"
python3 -m unittest discover -s tests
echo "==> tests/sandbox.sh"
tests/sandbox.sh
