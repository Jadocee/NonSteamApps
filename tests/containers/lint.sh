#!/usr/bin/env bash
# The static checks CI runs, in the CI image: ShellCheck on the shell scripts, pyflakes on the Python, and a compile
# of the artwork tool. The tests import _paths only to find the package, so pyflakes' note on that is left out.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

shellcheck -x -P SCRIPTDIR install.sh uninstall.sh src/bin/nonsteamapps tests/sandbox.sh tests/fakes/sudo tests/fakes/dolphin \
    src/share/sandbox/xdg-open src/share/kytyps5/terminal tests/containers/*.sh tests/containers/steamos/*.sh
echo "ShellCheck: no findings"

report=$(python3 -m pyflakes src/lib/nonsteamapps tests tools 2>&1 | grep -v "'_paths' imported but unused" || true)
if [ -n "$report" ]; then
    printf '%s\n' "$report"
    exit 1
fi
echo "pyflakes: no findings"

python3 -c 'import py_compile, sys; py_compile.compile(sys.argv[1], cfile="/tmp/render-artwork.pyc", doraise=True)' tools/render-artwork.py
echo "tools/render-artwork.py compiles"
