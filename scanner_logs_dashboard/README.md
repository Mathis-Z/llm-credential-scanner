# Scanner Logs Dashboard

Small Flask dashboard to browse scan runs in `/tmp/scanner_logs` (scanner.db, logs, screenshots).

## Start

1. Install dependencies:

```bash
python -m pip install -r dashboard/requirements.txt
```

2. Run the dashboard:

```bash
python dashboard/app.py
```

By default it listens on `http://127.0.0.1:8089`.

### Use a different logs folder

Set `SCANNER_LOGS_DIR` before launching if your logs live elsewhere:

```bash
export SCANNER_LOGS_DIR=/tmp/scanner_logs
python dashboard/app.py
```

## SSH Port Forwarding (server -> local)

```bash
ssh -L 8089:localhost:8089 team1@172.20.8.231 -i nsip_2526
```

Then open `http://127.0.0.1:8089` in your browser.

## What you can view

- Runs list (left sidebar)
- Found credentials and login panels
- Extracted keywords
- Screenshots grouped by endpoint + credentials
- Scanner and docker logs (with fullscreen view)
