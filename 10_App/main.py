import logging
import click

from netscan import NetScanner
from webenum import WebEnumerator
from creds_tester import CredsTester

@click.command()
@click.argument("subnets")
@click.option("--log-level", "-L", default="INFO", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--max-webdrivers", default=3, help="Maximum number of concurrent WebDriver instances for credential testing")
def run(subnets, log_level, max_webdrivers):
    logging.basicConfig(level=getattr(logging, log_level.upper(), None), format='[%(asctime)s][%(levelname)s] %(message)s')

    subnets = [sub for sub in subnets.split(",") if sub.strip()]

    modules = [
        NetScanner(subnets),
        WebEnumerator(),
        CredsTester(max_webdrivers=max_webdrivers)
    ]

    for module in modules:
        module.start()

    logging.info("All modules started.")

    for module in modules:
        module.join()

if __name__ == '__main__':
    run() # pylint: disable=no-value-for-parameter
