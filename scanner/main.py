import logging
import logging.config
import click

from scanner.netscan import NetScanner
from scanner.webenum import WebEnumerator
from scanner.ai import CredSearcher, CredTester, KeywordExtractor


def configure_logging(log_level="INFO"):
    """Configure logging for the scanner application. Excludes logs from other modules."""
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "scanner_only": {
                "()": lambda: logging.Filter("scanner")
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "filters": ["scanner_only"],
                "formatter": "default",
            }
        },
        "formatters": {
            "default": {
                "format": "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
            }
        },
        "root": {
            "level": log_level.upper(),
            "handlers": ["console"]
        }
    })

logger = logging.getLogger("scanner.main")

@click.command()
@click.argument("subnets")
@click.option("--ports", "-p", default="-", help="Comma-separated list of ports to scan; forwarded to nmap (default: all ports)")
@click.option("--log-level", "-L", default="INFO", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--max-webdrivers", default=1, help="Maximum number of concurrent WebDriver instances for credential testing")
def run(subnets, ports, log_level="INFO", max_webdrivers=1):
    configure_logging(log_level)
    logger.debug("Starting scanner")

    subnets = [sub for sub in subnets.split(",") if sub.strip()]

    modules = [
        NetScanner(subnets, ports),
        WebEnumerator(),
        KeywordExtractor(),
        CredSearcher(),
        CredTester(),
    ]

    for module in modules:
        module.start()

    logger.info("All modules started.")

    for module in modules:
        module.join()

    logger.info("Scanner exiting.")

if __name__ == '__main__':
    run() # pylint: disable=no-value-for-parameter
