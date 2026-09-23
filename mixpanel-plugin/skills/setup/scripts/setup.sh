#!/usr/bin/env bash
# Create or reuse the plugin's own virtual environment, install
# mixpanel_headless (0.3.0 or newer) and the analysis stack into it, then
# verify the imports, the built-in API reference (mp help), and credentials.
#
# Usage: setup.sh <venv-path>
#
# Nothing is installed outside <venv-path>. The skills run everything with
# <venv-path>/bin/python and <venv-path>/bin/mp.
set -euo pipefail

echo "=== mixpanel-headless — Setup ==="
echo ""

venv_dir="${1:-}"
# An absolute path is required. "/venv" means the plugin data directory was
# not substituted into the command, so refuse it instead of writing to "/".
if [ -z "$venv_dir" ] || [ "${venv_dir#/}" = "$venv_dir" ] || [ "$venv_dir" = "/venv" ]; then
  echo "✗ Usage: setup.sh <absolute-venv-path>  (got: '${venv_dir}')"
  echo "  Run setup through /mixpanel-headless:setup, which passes the plugin data directory."
  exit 2
fi
venv_dir="${venv_dir%/}"
venv_python="$venv_dir/bin/python"
venv_mp="$venv_dir/bin/mp"
venv_parent="$(dirname "$venv_dir")"
mkdir -p "$venv_parent"

has_uv=""
if command -v uv &>/dev/null; then
  has_uv=1
fi

# Print "major minor" for a Python interpreter, or nothing if it does not run.
python_version() {
  "$1" -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2>/dev/null || true
}

# Return success when the interpreter runs and is Python 3.10 or newer.
python_ok() {
  local ver
  ver="$(python_version "$1")"
  [ -n "$ver" ] || return 1
  local major="${ver% *}" minor="${ver#* }"
  [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }
}

# Find a base Python 3.10+ on PATH, as an absolute path.
base_python=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null && python_ok "$(command -v "$cmd")"; then
    base_python="$(command -v "$cmd")"
    break
  fi
done

# Reuse a working venv. Replace a broken or too-old one, but only when the
# directory is really a venv (it has pyvenv.cfg).
if [ -e "$venv_dir" ] && ! python_ok "$venv_python"; then
  if [ -f "$venv_dir/pyvenv.cfg" ]; then
    echo "⚠ The existing environment at $venv_dir does not run Python 3.10+. Recreating it."
    rm -rf "$venv_dir"
  else
    echo "✗ $venv_dir exists but is not a virtual environment. Move it away, then run setup again."
    exit 1
  fi
fi

if [ -e "$venv_dir" ]; then
  echo "✓ Plugin environment found: $venv_dir"
else
  echo "Creating the plugin environment at $venv_dir ..."
  venv_log="$(mktemp)"
  created=""
  if [ -n "$has_uv" ]; then
    # uv picks (or fetches) a Python 3.10+ when no base Python was found.
    # --directory keeps the current project's uv settings out of this step.
    if uv --directory "$venv_parent" venv --python "${base_python:->=3.10}" "$venv_dir" >"$venv_log" 2>&1; then
      created=1
    fi
  elif [ -n "$base_python" ]; then
    if "$base_python" -m venv "$venv_dir" >"$venv_log" 2>&1; then
      created=1
    fi
  else
    echo "✗ Python 3.10+ required but not found, and uv is not installed."
    echo "  Install Python 3.10+ (https://python.org) or uv (https://docs.astral.sh/uv/)."
    rm -f "$venv_log"
    exit 1
  fi
  if [ -z "$created" ]; then
    cat "$venv_log"
    echo ""
    echo "✗ Could not create the virtual environment."
    if grep -qiE 'ensurepip|python3-venv|externally[- ]managed' "$venv_log"; then
      echo "  This Python cannot create virtual environments. Debian and Ubuntu ship"
      echo "  that part separately, and some system Pythons are externally managed (PEP 668)."
      echo "  Fix: install uv (https://docs.astral.sh/uv/), or install the venv package"
      echo "  (for example: sudo apt install python3-venv). Then run setup again."
    fi
    rm -rf "$venv_dir" "$venv_log"
    exit 1
  fi
  rm -f "$venv_log"
  echo "✓ Plugin environment created: $venv_dir"
fi

python_ok "$venv_python" || { echo "✗ $venv_python does not run Python 3.10+."; exit 1; }
read -r _ venv_minor <<<"$(python_version "$venv_python")"
echo "✓ Python $("$venv_python" -c 'import platform; print(platform.python_version())')"

# The floor matters: `mp help` (the built-in API reference the skills rely
# on) first shipped in 0.3.0, and a bare package name never upgrades an
# older install.
MIXPANEL_HEADLESS_PKG="mixpanel-headless>=0.3.0"
DEPS=(pandas numpy matplotlib seaborn 'networkx>=3.0' 'anytree>=2.8.0' scipy)

# pyarrow is only needed on Python 3.11+ (for pandas 3.x Arrow-backed dtypes)
if [ "$venv_minor" -ge 11 ]; then
  DEPS+=('pyarrow>=17.0')
fi

# Print the installed mixpanel-headless version, or nothing when absent.
installed_version() {
  "$venv_python" -c "
from importlib.metadata import PackageNotFoundError, version
try:
    print(version('mixpanel-headless'))
except PackageNotFoundError:
    pass
" 2>/dev/null || true
}

old_version="$(installed_version)"

echo ""
echo "Installing mixpanel-headless (import name: mixpanel_headless) and dependencies..."
if [ -n "$has_uv" ]; then
  echo "  (using uv)"
  uv --directory "$venv_parent" pip install --python "$venv_python" "$MIXPANEL_HEADLESS_PKG" "${DEPS[@]}" \
    || { echo ""; echo "✗ Package install failed. Read the installer output above."; exit 1; }
else
  echo "  (using pip)"
  "$venv_python" -m pip install --upgrade "$MIXPANEL_HEADLESS_PKG" "${DEPS[@]}" \
    || { echo ""; echo "✗ Package install failed. Read the installer output above."; exit 1; }
fi

# Verify imports
echo ""
echo "Verifying installation..."
"$venv_python" -c "
import sys
import mixpanel_headless as mp
import pandas as pd
import numpy as np
import matplotlib
import seaborn as sns
import networkx as nx
import anytree
import scipy
print(f'✓ pandas {pd.__version__}')
if sys.version_info >= (3, 11):
    import pyarrow as pa
    print(f'✓ pyarrow {pa.__version__}')
print(f'✓ numpy {np.__version__}')
print(f'✓ matplotlib {matplotlib.__version__}')
print(f'✓ seaborn {sns.__version__}')
print(f'✓ networkx {nx.__version__}')
print(f'✓ anytree {anytree.__version__}')
print(f'✓ scipy {scipy.__version__}')
" || { echo "✗ Import verification failed"; exit 1; }

new_version="$(installed_version)"
if [ -z "$old_version" ]; then
  echo "✓ mixpanel-headless INSTALLED $new_version"
elif [ "$old_version" != "$new_version" ]; then
  echo "✓ mixpanel-headless UPGRADED $old_version → $new_version"
else
  echo "✓ mixpanel-headless OK $new_version"
fi

# The skills look up every API name with `mp help`; confirm it runs offline.
if "$venv_python" -m mixpanel_headless help -f json Workspace.query >/dev/null; then
  echo "✓ built-in help (mp help)"
else
  echo "✗ built-in help (mp help) failed — mixpanel-headless $new_version may be older than 0.3.0"
  exit 1
fi

# The skills run the CLI by its full path inside the plugin environment.
if [ -x "$venv_mp" ]; then
  echo "✓ mp CLI: $venv_mp"
else
  echo "✗ mp CLI missing at $venv_mp"
  exit 1
fi

# Check credentials
echo ""
echo "Checking Mixpanel credentials..."
"$venv_python" -c "
import os, sys

mp_cli = sys.argv[1]

# 1) Service-account env quad
sa_quad = ['MP_USERNAME', 'MP_SECRET', 'MP_PROJECT_ID', 'MP_REGION']
sa_set = [v for v in sa_quad if os.environ.get(v)]
if len(sa_set) == len(sa_quad):
    print('✓ Service-account env quad is fully set (MP_USERNAME + MP_SECRET + MP_PROJECT_ID + MP_REGION)')
    sys.exit(0)
elif sa_set:
    missing = [v for v in sa_quad if not os.environ.get(v)]
    print(f'⚠ Partial service-account env config — missing: {\", \".join(missing)}')

# 2) OAuth-token env triple
oauth_triple = ['MP_OAUTH_TOKEN', 'MP_PROJECT_ID', 'MP_REGION']
oauth_set = [v for v in oauth_triple if os.environ.get(v)]
if len(oauth_set) == len(oauth_triple):
    print('✓ OAuth-token env triple is fully set (MP_OAUTH_TOKEN + MP_PROJECT_ID + MP_REGION)')
    sys.exit(0)

# 3) Persisted accounts in ~/.mp/config.toml
try:
    import mixpanel_headless as mp
    accounts = mp.accounts.list()
    if accounts:
        active = next((a for a in accounts if a.is_active), None)
        names = ', '.join(a.name for a in accounts)
        print(f'✓ {len(accounts)} account(s) in ~/.mp/config.toml: {names}')
        if active:
            print(f'  Active: {active.name} ({active.type}, {active.region})')
        else:
            print(f'⚠ No active account selected. Run: {mp_cli} account use <name>')
    else:
        print('⚠ No accounts configured yet.')
        print(f'  Recommended: {mp_cli} login')
except Exception as e:
    print(f'⚠ Could not read ~/.mp/config.toml: {e}')
    print(f'  Run {mp_cli} login, or set the service-account or OAuth-token env vars.')
" "$venv_mp"

echo ""
echo "Plugin environment: $venv_dir"
echo "  Run your own scripts with: $venv_python your_script.py"
echo ""
echo "=== Setup complete ==="
