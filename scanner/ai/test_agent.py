import asyncio
import subprocess
import time
from agent import answer_with_tools
import threading

def _printer(pipe, name):
    for line in iter(pipe.readline, ""):
        print(f"[{name}] {line}", end="")
    pipe.close()

def test_find_mailcow_credentials():
    # Start server as background process
    process = subprocess.Popen(
        ["python", "./scanner/ai/mcp-server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Optional debugging output
    # threading.Thread(target=_printer, args=(process.stdout, "stdout"), daemon=True).start()
    # threading.Thread(target=_printer, args=(process.stderr, "stderr"), daemon=True).start()

    # Give server time to start
    time.sleep(1)

    question = "What are the default credentials for Mailcow?"
    response = asyncio.run(answer_with_tools(question))

    # Kill server after tests
    process.terminate()
    process.wait(timeout=2)

    assert "admin" in response
    assert "moohoo" in response
