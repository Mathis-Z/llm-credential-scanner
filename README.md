# Team 1: LLM-Assisted Web Default-Credential Scanner

This repository contains a prototype security scanner for discovering web services on a network, enumerating endpoints, and testing likely default credentials with help from LLM-driven agents.

The project is organized around two runnable parts:

- `scanner/`: the scanning pipeline (network scan -> web enum -> keyword extraction -> credential search -> credential testing)
- `dashboard/`: a Flask UI for browsing scan artifacts (`scanner.db`, logs, screenshots)

## What It Does

For each target subnet/IP:

1. Discovers hosts/ports that expose HTTP(S) (`scanner/netscan/`)
2. Enumerates reachable paths and detects login pages (`scanner/webenum/`)
3. Extracts identifying keywords from selected endpoints (`scanner/ai/keyword_extractor.py`)
4. Searches the web using LLMs for likely default credentials (`scanner/ai/cred_searcher.py`)
5. Uses browser automation + LLM tool calls to test credentials (`scanner/ai/cred_tester.py`)

Results are stored in SQLite and artifacts are written to a run directory containing:

- `scanner.db`
- `scanner.log`
- `screenshots/` (credential test before/after states)

## Repository Layout

- `scanner/`: core scanner code, tests, DB models, AI modules
- `dashboard/`: Flask dashboard for viewing run outputs
- `artifacts/successful_scan/`: sample run artifacts
- `references/`: papers, notes, prompts, and related material
- `meetings/`: project notes and progress logs

## Requirements

- Linux/macOS environment (tested on Linux)
- Python (testing with 3.13.7)
- `nmap` available on the host (used via `python3-nmap`)
- Chrome/Chromium runtime for SeleniumBase headless browser tasks
- LLM access:
	- remote API: set `OPENAI_API_KEY` (used with OpenRouter-compatible base URL by default)
	- or local model mode (`USE_LOCAL_LLM=true`, e.g. Ollama)

## Quick Start

### 1) Set up scanner environment

```bash
cd scanner
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Create `scanner/.env`:

```env
OPENAI_API_KEY=your_api_key_here
# Optional
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# USE_LOCAL_LLM=false
```

### 2) Run a scan

From repository root:

```bash
python3 -m scanner.main "192.168.1.0/24"
```

Or scan specific hosts/subnets and ports:

```bash
python3 -m scanner.main "192.168.1.10,192.168.1.0/28" -p "80,443,8080" --max-webdrivers 3 --max-webenum-workers 4
```

### 3) Open dashboard

```bash
python3 -m pip install -r dashboard/requirements.txt
python3 dashboard/app.py
```

Then open `http://127.0.0.1:8089`.

If your artifacts live elsewhere:

```bash
export SCANNER_LOGS_DIR=/path/to/scan_artifacts
python3 dashboard/app.py
```

## Scanner CLI

Main entrypoint: `python3 -m scanner.main <subnets>`

Supported options:

- `-p, --ports`: comma-separated ports forwarded to nmap
- `-L, --log-level`: `DEBUG|INFO|WARNING|ERROR|CRITICAL`
- `--log-file`: log filename/path under artifacts dir
- `--max-webdrivers`: concurrent browser sessions for credential testing
- `--max-webenum-workers`: concurrent web enumeration workers
- `--artifacts-dir`: output directory for DB/logs/screenshots
- `--disable_llm_cache`: disable local LLM response caching

Run help:

```bash
python3 -m scanner.main --help
```

## Artifacts and Data Model

Each run writes to an artifacts directory (default: `scan_artifacts/` relative to current working directory):

- `scanner.db`:
	- `service` table: discovered web services and candidate credentials
	- `endpoint` table: enumerated paths, login flags, extracted keywords, tested/working credentials
- `scanner.log`: scanner logs and status summaries
- `screenshots/`: saved around login attempts

The dashboard can:

- list runs
- inspect discovered services/endpoints
- show found credentials/login panels
- group screenshots by endpoint and credential attempt
- view scanner/docker logs

## Testing

Integration tests are under `scanner/tests/` and rely on containerized vulnerable applications.

Important:

- Test scripts may stop/kill running Docker containers.
- Test artifacts are created under `/tmp/scan_artifacts` by default.

### How the Docker Compose test setup works

The integration runner (`scanner/tests/tests.py`) executes a list of application test cases. For each app:

1. A Docker Compose stack is started from `scanner/tests/test-network/<app>/docker-compose.yml`.
2. The test waits until the target login page is reachable and a password field is present.
3. The scanner is run against that app target (`python -m scanner.main ...`) with a dedicated artifacts directory.
4. Assertions are collected (credentials found, credentials verified, login panel found, endpoint count).
5. The Compose stack is torn down (`docker compose down -v --remove-orphans`), with a force-kill fallback if needed.

The startup helper also prunes containers/networks before runs to reduce leftover-state issues.

Run tests:

```bash
python3 -m scanner.tests.tests --keep
```

Useful flags:

- `--select app1,app2`: run only selected apps
- `--kill-containers`: clean running containers before test execution
- `-L, --log-level`: set test/scanner logging verbosity

### Historical integration results

Collected integration test summaries are stored in:

- `artifacts/integration-tests-results/`

These files track results across project development iterations. The newest report is:

- `artifacts/integration-tests-results/11_02_2026_even_more_improved_cred_tester.txt`

## Safety Notes

- Use only on assets/networks you are explicitly authorized to test.
- Aggressive credential testing can trigger lockouts/rate limits.
- Web-search-based LLM steps should be treated as untrusted input.
- Keep API keys in `.env`; do not commit secrets.

## Current Status

This is an active prototype with evolving heuristics and test coverage.

Helpful project docs:

- `idea.md`
- `scanner/structure.md`
- `scanner/README.md`
- `dashboard/README.md`
