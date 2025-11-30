"""
Network scanner module.
This should return a list of (host, port) pairs to be further enumerated by the next modules
"""

import threading
import sys
import logging
import nmap3
from pubsub import pub
import requests


class NetScanner(threading.Thread):
    def __init__(self, subnets: str):
        super().__init__()
        self.subnets = subnets
        # TODO: implement abort mechanism

    def run(self):
        pub.sendMessage('netscanner.started')
        endpoints = []
        for subnet in self.subnets:
            endpoints.extend(self.scan_subnet(subnet))
        pub.sendMessage('netscanner.done')
        logging.info("NetScanner done")
        return endpoints

    def scan_subnet(self, subnet: str) -> list[(str, int, bool)]:
        """Scan the given subnet and return a list of detected HTTP endpoints as (host,port,https) tuples."""

        nmap = nmap3.NmapHostDiscovery()
        result = nmap.nmap_portscan_only(subnet)
        endpoints = []

        for host, data in result.items():
            if host in ['runtime', 'stats', 'task_results'] or data['state']['state'] != 'up':
                continue

            for port_info in data.get('ports', []):
                port = port_info['portid']

                if self.test_http_endpoint(host, port):
                    https = self.test_https_endpoint(host, port)

                    logging.info("Detected HTTP endpoint at %s:%s (HTTPS: %s)", host, port, https)

                    pub.sendMessage('netscanner.endpoint.detected', host=host, port=port_info['portid'], https=https)
                    endpoints.append((host, port, https))

        logging.debug("Discovered HTTP(S) endpoints: %s", endpoints)
        return endpoints

    def test_http_endpoint(self, host: str, port: int) -> bool:
        """Test if an HTTP service is running on the given host:port endpoint."""

        try:
            response = requests.get(f"http://{host}:{port}/", timeout=5, allow_redirects=False, verify=False)
            logging.debug("Detected HTTP on %s:%s - %s", host, port, response.status_code)
            return True
        except Exception as e:
            logging.debug("Failed to connect to %s:%s - %s", host, port, str(e))
            return False

    def test_https_endpoint(self, host: str, port: int) -> bool:
        """Test if an HTTPS service is running on the given host:port endpoint, ignoring certificate errors."""

        try:
            response = requests.get(f"https://{host}:{port}/", timeout=5, allow_redirects=False, verify=False)
            logging.debug("Detected HTTPS on %s:%s - %s", host, port, response.status_code)
            return True
        except Exception as e:
            logging.debug("Failed to connect to %s:%s - %s", host, port, str(e))
            return False


if __name__ == "__main__":
    scanner = NetScanner(sys.argv[1])
    for endpoint in scanner.run():
        print(f"Found HTTP(S) endpoint: {endpoint}")
