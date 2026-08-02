#!/bin/bash
# Fresh-VM bootstrap for the LLM credential scanner.
#
# Assumes a fresh Ubuntu VM with this repo already cloned. Installs system
# dependencies (Google Chrome, Docker, nmap, Ollama), provisions Python 3.14
# (via pyenv if it's already installed, otherwise via the deadsnakes PPA),
# creates the project venv, installs Python dependencies, pulls the Ollama
# models configured in scanner/settings.py, and smoke-tests that headless
# Chrome + chromedriver actually work end-to-end.
#
# Usage: ./install.sh   (run from the repo root as a normal sudo-capable user)
#
# Safe to re-run: every step checks whether it's already done before acting.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_DIR="$REPO_ROOT/scanner"
VENV_DIR="$SCANNER_DIR/.venv"

log() { echo -e "\n=== $* ===\n"; }
fail() { echo "error: $*" >&2; exit 1; }

if [ ! -f "$SCANNER_DIR/requirements.txt" ]; then
    fail "scanner/requirements.txt not found - run this script from a cloned repo checkout"
fi

if [ "$(id -u)" -eq 0 ]; then
    fail "run this as a normal user with sudo access, not as root"
fi

command -v sudo &>/dev/null || fail "sudo is required"

log "Updating apt package lists"
sudo apt-get update -y

log "Installing base system packages"
sudo apt-get install -y \
    curl wget git ca-certificates gnupg lsb-release software-properties-common \
    build-essential nmap

# ============================================================================
# Google Chrome
#
# Deliberately NOT the snap-packaged 'chromium-browser' Ubuntu ships by default:
# snap's AppArmor confinement is a known source of intermittent "tab crashed"
# errors under Selenium/undetected-chromedriver automation. Real Google Chrome
# via apt avoids that entirely.
# ============================================================================
log "Installing Google Chrome"
if ! command -v google-chrome &>/dev/null; then
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        | sudo tee /etc/apt/sources.list.d/google-chrome.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y google-chrome-stable
else
    echo "google-chrome already installed: $(google-chrome --version)"
fi

# Headless Chrome runtime libraries that are often missing on minimal server images.
sudo apt-get install -y \
    libnss3 libatk-bridge2.0-0 libgtk-3-0 libxss1 libasound2t64 libgbm1 \
    fonts-liberation libu2f-udev xdg-utils

# ============================================================================
# Docker (needed by scanner/tests/*.py to deploy the test/evaluation networks)
# ============================================================================
log "Installing Docker Engine + Compose plugin"
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Added $USER to the docker group - log out and back in (or run 'newgrp docker') before using docker without sudo."
else
    echo "docker already installed: $(docker --version)"
fi
sudo systemctl enable --now docker

# ============================================================================
# Ollama
# ============================================================================
log "Installing Ollama"
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "ollama already installed: $(ollama --version)"
fi
sudo systemctl enable --now ollama 2>/dev/null || true

# ============================================================================
# Python 3.14
# ============================================================================
log "Checking for Python 3.14"

find_python314() {
    if command -v python3.14 &>/dev/null; then
        command -v python3.14
        return 0
    fi
    if command -v pyenv &>/dev/null || [ -x "$HOME/.pyenv/bin/pyenv" ]; then
        local pyenv_root
        pyenv_root="${PYENV_ROOT:-$HOME/.pyenv}"
        local found
        found=$(find "$pyenv_root/versions" -maxdepth 1 -type d -name "3.14*" 2>/dev/null | sort -V | tail -1)
        if [ -n "$found" ] && [ -x "$found/bin/python3.14" ]; then
            echo "$found/bin/python3.14"
            return 0
        fi
    fi
    return 1
}

PYTHON_BIN=""
if PYTHON_BIN=$(find_python314); then
    echo "Found Python 3.14: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
elif command -v pyenv &>/dev/null || [ -x "$HOME/.pyenv/bin/pyenv" ]; then
    log "pyenv detected - using it to install Python 3.14 (preferred over a system-wide install)"
    export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"

    # pyenv builds Python from source, so it needs the standard build dependencies.
    sudo apt-get install -y \
        libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
        llvm libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
        libffi-dev liblzma-dev

    LATEST_314=$(pyenv install --list | grep -E '^\s*3\.14\.[0-9]+$' | tail -1 | xargs)
    if [ -z "$LATEST_314" ]; then
        fail "pyenv doesn't know about any 3.14.x release yet. Run 'pyenv update' and re-run this script."
    fi
    pyenv install -s "$LATEST_314"
    PYTHON_BIN="$PYENV_ROOT/versions/$LATEST_314/bin/python3.14"
    echo "Installed via pyenv: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
else
    log "No pyenv found - installing Python 3.14 system-wide via the deadsnakes PPA"
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update -y
    if ! sudo apt-get install -y python3.14 python3.14-venv python3.14-dev; then
        fail "python3.14 isn't available via deadsnakes yet on this Ubuntu release. Install pyenv (https://github.com/pyenv/pyenv) and re-run this script, or install Python 3.14 manually."
    fi
    PYTHON_BIN="$(command -v python3.14)"
    echo "Installed via apt/deadsnakes: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
fi

# ============================================================================
# venv + Python dependencies
# ============================================================================
log "Creating virtualenv at $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR" || fail "venv creation failed - is the venv module installed for this interpreter?"

log "Installing Python dependencies (this pulls torch/sentence-transformers, may take a while)"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCANNER_DIR/requirements.txt" || fail "pip install failed"

# ============================================================================
# .env
# ============================================================================
if [ ! -f "$REPO_ROOT/.env" ] && [ -f "$REPO_ROOT/example.env" ]; then
    cp "$REPO_ROOT/example.env" "$REPO_ROOT/.env"
    echo ".env created from example.env - edit it to add a real OPENAI_API_KEY if you plan to use the remote LLM backend (not needed for USE_LOCAL_LLM=true)."
fi

# ============================================================================
# Pull the Ollama models scanner/settings.py is configured to use
# ============================================================================
log "Pulling Ollama models configured for local use"
MODELS=$("$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, '$REPO_ROOT')
from scanner.settings import Settings
s = Settings(use_local_llm=True)
print(s.reasoning_llm_name)
print(s.nonreasoning_llm_name)
" | sort -u) || fail "could not resolve configured Ollama model names"

PULL_FAILED=0
while IFS= read -r model; do
    [ -z "$model" ] && continue
    echo "Pulling $model ..."
    if ! ollama pull "$model"; then
        echo "warning: failed to pull $model" >&2
        PULL_FAILED=1
    fi
done <<< "$MODELS"
[ "$PULL_FAILED" -eq 0 ] || echo "warning: one or more Ollama models failed to pull; local LLM runs may fail until this is resolved." >&2

# ============================================================================
# Verify chromedriver / headless Chrome actually work end-to-end
# ============================================================================
log "Verifying chromedriver + headless Chrome (undetected-chromedriver mode, as used by the scanner)"
if "$VENV_DIR/bin/python" - <<'PYEOF'
from seleniumbase import SB

with SB(
    uc=True,
    headless=True,
    page_load_strategy="eager",
    chromium_arg=[
        "--disable-dev-shm-usage",
        "--ignore-certificate-errors",
        "--allow-insecure-localhost",
        "--allow-running-insecure-content",
    ],
) as sb:
    sb.open("about:blank")
    sb.driver.execute_script("document.title = 'chromedriver-check-ok';")
    title = sb.driver.title
    assert title == "chromedriver-check-ok", f"unexpected title: {title!r}"

print("chromedriver check: OK")
PYEOF
then
    echo "Chrome + chromedriver verified working."
else
    fail "chromedriver verification failed - see output above (common causes: missing Chrome runtime libs, or the sandbox environment lacking permissions undetected-chromedriver needs)"
fi

log "Install complete."
echo "Activate the venv with:  source $VENV_DIR/bin/activate"
echo "If Docker was just installed, log out and back in (or run 'newgrp docker') for group membership to take effect."
echo "Edit $REPO_ROOT/.env if you plan to use the remote LLM backend."
