import logging
import time
import logging.config
import click

from scanner.netscan import NetScanner
from scanner.webenum import WebEnumerator
from scanner.ai import CredSearcher, CredTester, KeywordExtractor
from scanner.settings import Settings
from scanner.db import init_db, Endpoint, Service
from tabulate import tabulate


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
@click.option("--ports", "-p", default=None, help="Comma-separated list of ports to scan; forwarded to nmap")
@click.option("--log-level", "-L", default="INFO", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--max-webdrivers", default=1, help="Maximum number of concurrent WebDriver instances for credential testing")
@click.option("--db-path", default=None, help="Path to the SQLite database file")
def main_cmd(subnets, ports, log_level, max_webdrivers, db_path):
    run(subnets, ports, log_level, max_webdrivers, db_path)

def run(subnets, ports, log_level, max_webdrivers, db_path):
    Settings().configure_cli_arguments(db_path=db_path, max_webdrivers=max_webdrivers)
    configure_logging(log_level)
    init_db()

    start_time = time.time()
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

    logger.info("All modules completed.")
    print_scan_summary(start_time)


def print_scan_summary(start_time):
    summary = "\n" + "=" * 30 + " Scan Summary " + "=" * 30 + "\n"

    endpoints_with_default_creds = Endpoint.select().where(Endpoint.working_credentials != '')
    if endpoints_with_default_creds.count() > 0:
        summary += "Endpoints with default credentials found:\n"
        for endpoint in endpoints_with_default_creds:
            summary += f"- {endpoint.url()} | Credentials: {endpoint.working_credentials}\n"
    else:
        summary += "No endpoints with default credentials found.\n"

    services = Service.select()
    summary += f"\nTotal services scanned: {services.count()}\n"

    service_data = []
    for service in Service.select():
        service_data.append([
            service.url(),
            len(service.endpoints),
            service.credentials if service.credentials else 'Unknown or N/A'
        ])

    summary += tabulate(
        service_data,
        headers=['Service URL', 'Endpoints', 'Potential Default Credentials'],
        tablefmt='grid'
    ) + "\n"

    summary += f"Total scan duration: {time.time() - start_time:.2f} seconds\n"
    logger.info(summary)


if __name__ == '__main__':
    main_cmd() # pylint: disable=no-value-for-parameter
