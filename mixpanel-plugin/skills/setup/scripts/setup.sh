#!/usr/bin/env bash
# Install mixpanel_headless (0.3.0 or newer) and the analysis stack, then
# verify imports, the built-in API reference (mp help), and credentials.
set -euo pipefail

echo "=== mixpanel-headless — Setup ==="
echo ""

# Find Python 3.10+
python_cmd=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
    minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
      version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
      python_cmd="$cmd"
      echo "✓ Python $version ($cmd)"
      break
    fi
  fi
done

if [ -z "$python_cmd" ]; then
  echo "✗ Python 3.10+ required but not found."
  echo "  Install from https://python.org or via your package manager."
  exit 1
fi

# Install packages. The floor matters: `mp help` (the built-in API
# reference the skills rely on) first shipped in 0.3.0, and a bare package
# name never upgrades an older install.
MIXPANEL_HEADLESS_PKG="mixpanel-headless>=0.3.0"
DEPS=(pandas numpy matplotlib seaborn 'networkx>=3.0' 'anytree>=2.8.0' scipy)

# pyarrow is only needed on Python 3.11+ (for pandas 3.x Arrow-backed dtypes)
if [ "$minor" -ge 11 ]; then
  DEPS+=('pyarrow>=17.0')
fi

# Print the installed mixpanel-headless version, or nothing when absent.
installed_version() {
  "$python_cmd" -c "
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

# Keep a copy of the installer output, so a failure can be explained.
install_log="$(mktemp)"
trap 'rm -f "$install_log"' EXIT

# Run an install command. Show its output and also save it to $install_log.
run_install() {
  "$@" 2>&1 | tee -a "$install_log"
}

# Explain an install failure, then stop. PEP 668 ("externally managed")
# Pythons, such as Homebrew and most Linux system Pythons, refuse installs
# from pip and uv. The raw error does not say what to do next.
install_failed() {
  echo ""
  if grep -qiE 'externally[- ]managed' "$install_log"; then
    echo "✗ Install refused: $python_cmd is an externally managed Python (PEP 668)."
    echo "  Homebrew and system Pythons block package installs to protect the OS."
    echo "  Fix: create and activate a virtual environment, then run setup again:"
    echo "    uv venv ~/.venvs/mixpanel && source ~/.venvs/mixpanel/bin/activate"
    echo "  Without uv:"
    echo "    python3 -m venv ~/.venvs/mixpanel && source ~/.venvs/mixpanel/bin/activate"
  else
    echo "✗ Package install failed. Read the installer output above."
  fi
  exit 1
}

if command -v uv &>/dev/null; then
  echo "  (using uv)"
  if ! run_install uv pip install --python "$python_cmd" "$MIXPANEL_HEADLESS_PKG" "${DEPS[@]}"; then
    echo "  ⚠ Virtualenv install failed, trying system install..."
    # Not logged: the first attempt's output names the real cause.
    uv pip install --system --python "$python_cmd" "$MIXPANEL_HEADLESS_PKG" "${DEPS[@]}" || install_failed
  fi
elif "$python_cmd" -m pip --version &>/dev/null; then
  echo "  (using pip via $python_cmd)"
  run_install "$python_cmd" -m pip install "$MIXPANEL_HEADLESS_PKG" "${DEPS[@]}" || install_failed
else
  echo "✗ No package manager found. Install pip or uv."
  echo "  Recommended: https://docs.astral.sh/uv/"
  exit 1
fi

# Verify imports
echo ""
echo "Verifying installation..."
"$python_cmd" -c "
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
if "$python_cmd" -m mixpanel_headless help -f json Workspace.query >/dev/null; then
  echo "✓ built-in help (mp help)"
else
  echo "✗ built-in help (mp help) failed — mixpanel-headless $new_version may be older than 0.3.0"
  exit 1
fi

# The skills prefer the mp command, but can run the same CLI as a module.
if command -v mp &>/dev/null; then
  echo "✓ mp on PATH"
else
  echo "⚠ mp not on PATH; the skills fall back to python3 -m mixpanel_headless"
fi

# Check credentials
echo ""
echo "Checking Mixpanel credentials..."
"$python_cmd" -c "
import os, sys

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
            print('⚠ No active account selected. Run: mp account use <name>')
    else:
        print('⚠ No accounts configured yet.')
        print('  Recommended:      mp login                                   # one-shot frictionless login')
        print('  Service account:  mp account add team --type service_account --username sa_xxx --project 12345 --region us')
except Exception as e:
    print(f'⚠ Could not read ~/.mp/config.toml: {e}')
    print('  Run mp login, set env vars (service-account quad or OAuth triple), or run mp account add ...')
"

echo ""
echo "=== Setup complete ==="
