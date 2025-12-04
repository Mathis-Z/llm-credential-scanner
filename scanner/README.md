This folder contains the code of the web application scanner.

# Setup

Tested with Python 3.13.7

1. Create virtual environment and activate it

```bash
python3 -m venv .venv && source .venv/bin/activate
```

2. Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

3. Create `scanner/.env` file with `OPENROUTER_API_KEY=<your-api-key>`

4. Run main script and specify subnets/IPs to be scanned

```bash
python3 main.py 123.123.123.123/24
```

You can use `python3 main.py --help` to get a list of available options.
