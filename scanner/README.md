This folder contains the code of the web application scanner.

# Setup

Make sure to install nmap and chrome.

Tested with Python 3.13.7.
From project root, not from scanner/:

1. Create virtual environment and activate it

```bash
python3 -m venv scanner/.venv && source scanner/.venv/bin/activate
```

2. Install dependencies

```bash
python3 -m pip install -r scanner/requirements.txt
```

3. (Create `scanner/.env` file with `OPENROUTER_API_KEY=<your-api-key>`)

4. Run main script and specify subnets/IPs to be scanned

```bash
python3 -m scanner.main 123.123.123.123/24
```

You can use `python3 -m scanner.main --help` to get a list of available options.

# Notes

When running Ollama, you should probably increase the context window by setting `export OLLAMA_CONTEXT_LENGTH=16000` before running `ollama serve`
Make sure to install a recent version of Ollama (tested with 0.18.3) to support the qwen3.5 models.
Also pull the models you want to use.
