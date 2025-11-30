# Testing Setup

(Work in progress)

The tests require multipass. You can install multipass from the snap store: `sudo snap install multipass --classic`.

For each app there is a setup script in `apps/` that deploys the app. Using the `StartupScript` helper, test cases can automatically run these setup scripts and wait for a certain output string that signals readiness. Using the `TestScanner` helper class, a test can then run the scanner and check if credentials are found for the app.

Since the app setup scripts can clutter your docker environment and interfere with each other, the entire test suite runs in a Multipass VM. The VM is set up automatically when the tests are executed.

To run the tests, execute `python3 tests/run_all.py` which will execute the pytest suite in the VM. Use `python tests/run_all.py -s --cli-log-level=info` to get logging output.
You can also run the pytest suite on your host machine with `pytest tests/tests.py` but this will mess with your docker environment. In particular, before each setup script, all docker networks and stopped containers are deleted:\
`sudo docker container prune -f`\
`sudo docker network prune -f`

This is to ensure that install scripts do not interfere with each other.

Note that the tests use timeouts to determine when the scanner did not find the credentials (waiting for it to complete would take too long). This means the tests can be flaky sometimes.
