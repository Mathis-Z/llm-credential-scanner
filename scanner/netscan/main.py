"""
Network scanner module.
Scans a list of subnets and creates Service records for all
detected HTTP(S) services.
"""

import threading
import logging
import ipaddress
import nmap3
from pubsub import pub
import requests

from scanner.db.models import Service
from scanner.db import DBConnectionMixin

logger = logging.getLogger('scanner.netscan')

class NetScanner(DBConnectionMixin, threading.Thread):
    def __init__(self, subnets_or_ips: list[str], ports: str|None = None):
        super().__init__()
        self.subnets_or_ips = subnets_or_ips
        self.ports = ports
        # TODO: implement abort mechanism

    def run_with_db(self):
        pub.sendMessage('netscanner.started')
        for subnet_or_ip in self.subnets_or_ips:
            self.scan_subnet_or_ip(subnet_or_ip)
        pub.sendMessage('netscanner.done')
        logger.info("NetScanner done")

    def scan_host(self, host: str):
        """Scan a single host."""
        logger.debug("Scanning host %s", host)
        ports_argument = f'-p{self.ports}' if self.ports else ''

        nmap = nmap3.NmapHostDiscovery()
        result = nmap.nmap_portscan_only(host, args=ports_argument)

        detected_services = []
        for h, data in result.items():
            if h in ['runtime', 'stats', 'task_results'] or data['state']['state'] != 'up':
                continue

            for port_info in data.get('ports', []):
                port = int(port_info['portid'])
                logger.debug("Testing %s:%s", h, port)

                if self.test_http_service(h, port):
                    https = self.test_https_service(h, port)

                    logger.info("Detected HTTP service at %s:%s (HTTPS: %s)", h, port, https)
                    # TODO: resuming from stored DB
                    Service.get_or_create(host=h, port=port, https=https)
                    detected_services.append("%s://%s:%s" % ('https' if https else 'http', h, port))

        if len(detected_services) > 0:
            logger.debug("Discovered HTTP(S) services on %s: %s", host, detected_services)
        else:
            logger.debug("No services detected on %s", host)

    def scan_subnet_or_ip(self, subnet_or_ip: str):
        """Scan the given subnet one host at a time"""
        for h in ipaddress.ip_network(subnet_or_ip):
            self.scan_host(str(h))

    def test_http_service(self, host: str, port: int) -> bool:
        """Test if an HTTP service is running on the given host:port service."""

        url = f"http://{host}:{port}/"
        try:
            requests.get(url, timeout=5, allow_redirects=True, verify=False)
            return True
        except Exception:
            logger.debug("Failed to connect to %s", url)
            return False

    def test_https_service(self, host: str, port: int) -> bool:
        """
        Test if an HTTPS service is running on the given host:port service,
        ignoring certificate errors.
        """
        url = f"https://{host}:{port}/"
        try:
            response = requests.get(url, timeout=5, allow_redirects=False, verify=False)
            logger.debug("Detected HTTPS on %s:%s - %s", host, port, response.status_code)
            return True
        except Exception:
            logger.debug("Failed to connect to %s", url)
            return False
