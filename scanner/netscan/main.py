"""
Network scanner module.
Scans a list of subnets and creates Service records for all
detected HTTP(S) services.
"""

import threading
import logging
import nmap3
from pubsub import pub
import requests

from scanner.db.models import Service

logger = logging.getLogger('scanner.netscan')

class NetScanner(threading.Thread):
    def __init__(self, subnets: list[str]):
        super().__init__()
        self.subnets = subnets
        # TODO: implement abort mechanism

    def run(self):
        pub.sendMessage('netscanner.started')
        for subnet in self.subnets:
            self.scan_subnet(subnet)
        pub.sendMessage('netscanner.done')
        logger.info("NetScanner done")

    def scan_subnet(self, subnet: str):
        """Scan the given subnet and return a list of detected HTTP services as (host,port,https) tuples."""

        nmap = nmap3.NmapHostDiscovery()
        result = nmap.nmap_portscan_only(subnet)

        for host, data in result.items():
            if host in ['runtime', 'stats', 'task_results'] or data['state']['state'] != 'up':
                continue

            for port_info in data.get('ports', []):
                port = int(port_info['portid'])

                if self.test_http_service(host, port):
                    https = self.test_https_service(host, port)

                    if port != 8080:
                        continue  # Temporary: only scan this port for debugging
                    logger.info("Detected HTTP service at %s:%s (HTTPS: %s)", host, port, https)
                    # TODO: resuming from stored DB
                    Service.get_or_create(host=host, port=port, https=https)

        logger.debug("Discovered HTTP(S) services: %s", [s.url() for s in Service.select()])

    def test_http_service(self, host: str, port: int) -> bool:
        """Test if an HTTP service is running on the given host:port service."""

        try:
            response = requests.get(f"http://{host}:{port}/", timeout=5, allow_redirects=False, verify=False)
            return True
        except Exception as e:
            logger.debug("Failed to connect to %s:%s - %s", host, port, str(e))
            return False

    def test_https_service(self, host: str, port: int) -> bool:
        """
        Test if an HTTPS service is running on the given host:port service,
        ignoring certificate errors.
        """
        try:
            response = requests.get(f"https://{host}:{port}/", timeout=5, allow_redirects=False, verify=False)
            logger.debug("Detected HTTPS on %s:%s - %s", host, port, response.status_code)
            return True
        except Exception as e:
            logger.debug("Failed to connect to %s:%s - %s", host, port, str(e))
            return False
