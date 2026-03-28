# evaluate_external (Changeme)

Runs **Changeme** (ztgrace/changeme) against the Docker Compose app suites in:

- `scanner/tests/test-network/<App>/docker-compose.yml*`
- `scanner/tests/evaluation-network/<App>/docker-compose.yml*`

This is **scanner-independent** (stdlib-only Python).

## Prereqs

- `python3`
- Docker + `docker compose`
- Network access to pull images (`redis`, `ztgrace/changeme`, and app images)

Notes:
- Changeme runs in Docker with `--network host`, so targets are `127.0.0.1`.
- On SELinux systems (Fedora/RHEL), the script mounts artifacts with `:Z` so the container can write `results.csv`.

## Usage

Show help:

```bash
python3 evaluate_external/evaluate_changeme.py --help
```

Run the test-network suite:

```bash
python3 evaluate_external/evaluate_changeme.py
```

Run only evaluation-network:

```bash
python3 evaluate_external/evaluate_changeme.py --evaluation
```

Run **both** suites in one go:

```bash
python3 evaluate_external/evaluate_changeme.py --both
```

Run a single service and keep artifacts/logs:

```bash
python3 evaluate_external/evaluate_changeme.py -s Grafana --keep -L DEBUG
```

Optional flags:
- `--kill-containers`: kills *all* running Docker containers before starting
- `--threads`, `--timeout`, `--delay`: passed to Changeme
- `--protocols`: e.g. `http`
- `-s/--select` and `-x/--exclude`: comma-separated service name filters

Artifacts are written under `/tmp/evaluate_artifacts/` (one folder per service run).
