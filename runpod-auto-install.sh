#!/bin/bash
# RunPod bootstrap for the LLM credential scanner.
#
# Deployment model this script assumes: the repo lives on a shared network
# volume (typically mounted at /workspace) that multiple pods read the same
# code from concurrently to run the test suite in parallel. This script never
# copies or moves that repo - it always operates on it in place. Everything
# that needs pod-local scratch space (the venv, Ollama's models, Docker's
# image storage, pyenv's from-source Python build) is written to the pod's
# own local disk (i.e. under $HOME, not under the repo/workspace), so
# multiple pods running this concurrently never collide on the same files.
#
# Installs system dependencies (Google Chrome, Docker, nmap, Ollama),
# provisions Python 3.14 (via pyenv), creates a pod-local venv, installs
# Python dependencies, pulls the Ollama models configured in
# scanner/settings.py, and smoke-tests that headless Chrome + chromedriver
# actually work end-to-end.
#
# Usage: ./runpod-auto-install.sh   (run from the repo root as a normal sudo-capable user)
#        ./runpod-auto-install.sh --remote <OPENAI_API_KEY>
#            Skips every component that's only needed for local LLM inference
#            (Ollama install/service, GPU-detection package, model pulls) and
#            auto-creates .env with the given OPENAI_API_KEY instead.
#
# Safe to re-run: every step checks whether it's already done before acting.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_DIR="$REPO_ROOT/scanner"

log() { echo -e "\n=== $* ===\n"; }
fail() { echo "error: $*" >&2; exit 1; }

if [ ! -f "$SCANNER_DIR/requirements.txt" ]; then
    fail "scanner/requirements.txt not found - run this script from a cloned repo checkout"
fi

if [ "$(id -u)" -eq 0 ]; then
    DEPLOY_USER="${DEPLOY_USER:-deploy}"
    log "Running as root - creating non-root user '$DEPLOY_USER' and switching to it"

    if ! id -u "$DEPLOY_USER" &>/dev/null; then
        adduser --disabled-password --gecos "" "$DEPLOY_USER"
    fi

    apt-get update -y &>/dev/null || true
    apt-get install -y sudo &>/dev/null || true
    usermod -aG sudo "$DEPLOY_USER"
    echo "$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$DEPLOY_USER"
    chmod 440 "/etc/sudoers.d/90-$DEPLOY_USER"

    # The repo is shared across pods (e.g. on a network volume) - it's used in
    # place, never copied or chowned, so concurrent pods never fight over it
    # or over a uid that may differ from pod to pod.
    SCRIPT_PATH="$REPO_ROOT/$(basename "${BASH_SOURCE[0]}")"
    exec su - "$DEPLOY_USER" -c "$(printf '%q ' "$SCRIPT_PATH" "$@")"
fi

# Pod-local venv, deliberately kept off the shared repo path so multiple pods
# running this script concurrently against the same repo each get their own.
VENV_DIR="$HOME/.venvs/llm-credential-scanner"

REMOTE_MODE=0
OPENAI_KEY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --remote)
            [ -n "${2:-}" ] || fail "--remote requires an OPENAI_API_KEY argument"
            REMOTE_MODE=1
            OPENAI_KEY="$2"
            shift 2
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

(apt-get update && apt-get install -y sudo) &>/dev/null || true

command -v sudo &>/dev/null || fail "sudo is required"

log "Updating apt package lists"
sudo apt-get update -y

log "Installing base system packages"
sudo apt-get install -y \
    curl wget git ca-certificates gnupg lsb-release software-properties-common \
    build-essential nmap zstd pciutils

# ============================================================================
# Google Chrome
#
# Deliberately NOT the snap-packaged 'chromium-browser' Ubuntu ships by default:
# snap's AppArmor confinement is a known source of intermittent "tab crashed"
# errors under Selenium/undetected-chromedriver automation. Real Google Chrome
# avoids that entirely. Installed via a direct .deb download rather than
# adding Google's apt repo, since that's simpler and doesn't touch apt sources.
# ============================================================================
log "Installing Google Chrome"
if ! command -v google-chrome &>/dev/null; then
    CHROME_DEB="$(mktemp -t google-chrome-stable_current_amd64.XXXXXX.deb)"
    wget -q -O "$CHROME_DEB" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt-get install -y "$CHROME_DEB" || sudo apt-get install -y -f
    rm -f "$CHROME_DEB"
else
    echo "google-chrome already installed: $(google-chrome --version)"
fi

# Headless Chrome runtime libraries that are often missing on minimal server images.
# The ALSA package was renamed libasound2 -> libasound2t64 as part of Ubuntu 24.04's
# time_t transition, so older releases (or non-Ubuntu bases) still use the old name.
ALSA_PKG="libasound2t64"
apt-cache show libasound2t64 &>/dev/null || ALSA_PKG="libasound2"
sudo apt-get install -y \
    libnss3 libatk-bridge2.0-0 libgtk-3-0 libxss1 "$ALSA_PKG" libgbm1 \
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
sudo systemctl enable --now docker 2>/dev/null || sudo service docker start 2>/dev/null || echo "warning: couldn't start docker via systemctl/service (no init system running, e.g. inside a container) - start the docker daemon yourself before running scanner tests."

# ============================================================================
# Ollama (skipped in --remote mode - local LLM inference isn't used)
# ============================================================================
if [ "$REMOTE_MODE" -eq 1 ]; then
    log "Skipping Ollama install (--remote mode)"
else
    log "Installing Ollama"
    if ! command -v ollama &>/dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        echo "ollama already installed: $(ollama --version)"
    fi
    sudo systemctl enable --now ollama 2>/dev/null || true
fi

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
else
    if ! command -v pyenv &>/dev/null && [ ! -x "$HOME/.pyenv/bin/pyenv" ]; then
        # Official install method per https://github.com/pyenv/pyenv#automatic-installer
        log "pyenv not found - installing it via the official pyenv.run installer"

        # pyenv builds Python from source, so it needs the standard build dependencies.
        sudo apt-get install -y \
            libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
            llvm libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
            libffi-dev liblzma-dev

        curl -fsSL https://pyenv.run | bash || fail "pyenv installation failed"
    fi

    log "Using pyenv to install Python 3.14"
    export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
    export PATH="$PYENV_ROOT/bin:$PATH"
    command -v pyenv &>/dev/null || fail "pyenv installed to $PYENV_ROOT but '$PYENV_ROOT/bin/pyenv' isn't on PATH"
    eval "$(pyenv init -)"

    pyenv update 2>/dev/null || true
    LATEST_314=$(pyenv install --list | grep -E '^\s*3\.14\.[0-9]+$' | tail -1 | xargs)
    if [ -z "$LATEST_314" ]; then
        fail "pyenv doesn't know about any 3.14.x release yet. Run 'pyenv update' and re-run this script."
    fi
    pyenv install -s "$LATEST_314"
    PYTHON_BIN="$PYENV_ROOT/versions/$LATEST_314/bin/python3.14"
    [ -x "$PYTHON_BIN" ] || fail "pyenv reported installing $LATEST_314 but $PYTHON_BIN doesn't exist"

    INSTALLED_VERSION="$("$PYTHON_BIN" --version | awk '{print $2}')"
    case "$INSTALLED_VERSION" in
        3.14.*) ;;
        *) fail "expected Python 3.14.x, but $PYTHON_BIN reports $INSTALLED_VERSION" ;;
    esac
    echo "Installed via pyenv: $PYTHON_BIN ($INSTALLED_VERSION)"
fi

# ============================================================================
# venv + Python dependencies
# ============================================================================
log "Creating virtualenv at $VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"
"$PYTHON_BIN" -m venv "$VENV_DIR" || fail "venv creation failed - is the venv module installed for this interpreter?"

log "Installing Python dependencies (this pulls torch/sentence-transformers, may take a while)"
# Some cloud GPU base images (e.g. RunPod's PyTorch templates) set PIP_CONSTRAINT
# (or ship a global /etc/pip.conf constraint) pinning torch to whatever CUDA build
# they preinstalled. That constraint leaks into this fresh venv too and conflicts
# with the torch pin in requirements.txt, so it's explicitly discarded here.
if [ -n "${PIP_CONSTRAINT:-}" ]; then
    echo "Ignoring inherited PIP_CONSTRAINT=$PIP_CONSTRAINT for this install"
fi
env -u PIP_CONSTRAINT PIP_CONFIG_FILE=/dev/null "$VENV_DIR/bin/pip" install --upgrade pip
env -u PIP_CONSTRAINT PIP_CONFIG_FILE=/dev/null "$VENV_DIR/bin/pip" install -r "$SCANNER_DIR/requirements.txt" || fail "pip install failed"

# ============================================================================
# .env
# ============================================================================
if [ "$REMOTE_MODE" -eq 1 ]; then
    log "Writing .env for remote LLM use"
    [ -f "$REPO_ROOT/.env" ] || [ ! -f "$REPO_ROOT/example.env" ] || cp "$REPO_ROOT/example.env" "$REPO_ROOT/.env"
    touch "$REPO_ROOT/.env"
    if grep -q '^OPENAI_API_KEY=' "$REPO_ROOT/.env" 2>/dev/null; then
        sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=$OPENAI_KEY|" "$REPO_ROOT/.env"
    else
        echo "OPENAI_API_KEY=$OPENAI_KEY" >> "$REPO_ROOT/.env"
    fi
    echo ".env written with the provided OPENAI_API_KEY."
elif [ ! -f "$REPO_ROOT/.env" ] && [ -f "$REPO_ROOT/example.env" ]; then
    cp "$REPO_ROOT/example.env" "$REPO_ROOT/.env"
    echo ".env created from example.env - edit it to add a real OPENAI_API_KEY if you plan to use the remote LLM backend (not needed for USE_LOCAL_LLM=true)."
fi

# ============================================================================
# Pull the Ollama models scanner/settings.py is configured to use
# (skipped in --remote mode - local LLM inference isn't used)
# ============================================================================
if [ "$REMOTE_MODE" -eq 1 ]; then
    log "Skipping Ollama model pulls (--remote mode)"
else
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
fi

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
if [ "$REMOTE_MODE" -eq 0 ]; then
    echo "Edit $REPO_ROOT/.env if you plan to use the remote LLM backend."
fi
