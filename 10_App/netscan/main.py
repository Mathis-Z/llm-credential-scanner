"""
Network scanner module.
This should return a list of (host, port) pairs to be further enumerated by the next modules
"""

import threading
import sys
import logging
import http.client
import nmap3
from pubsub import pub


class NetScanner(threading.Thread):
    def __init__(self, subnets: str):
        super().__init__()
        self.subnets = subnets

    def run(self):
        endpoints = []
        for subnet in self.subnets:
            endpoints.extend(self.scan_subnet(subnet))
        pub.sendMessage('netscanner_done')
        return endpoints

    def scan_subnet(self, subnet: str):
        """Scan the given subnet and return a list of detected HTTP endpoints as host:port strings."""
        nmap = nmap3.NmapHostDiscovery()
        result = nmap.nmap_portscan_only(subnet)
        endpoints = []

        for host, data in result.items():
            if host in ['runtime', 'stats', 'task_results'] or data['state']['state'] != 'up':
                continue

            for port_info in data.get('ports', []):
                port = port_info['portid']

                if self.test_http_endpoint(host, port):
                    logging.info("Detected HTTP endpoint: %s:%s", host, port)
                    pub.sendMessage('netscanner_endpoint_detected', host=host, port=port_info['portid'])
                    endpoints.append((host, port))

        logging.debug("Discovered endpoints: %s", endpoints)
        return [ep for ep in endpoints if self.test_http_endpoint(ep[0], ep[1])]

    def test_http_endpoint(self, host: str, port: int) -> bool:
        """Test if an HTTP service is running on the given host:port endpoint."""

        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("GET", "/")
            response = conn.getresponse()
            logging.debug("HTTP %s on %s:%s - %s", response.status, host, port, response.reason)
            return True
        except Exception as e:
            logging.debug("Failed to connect to %s:%s - %s", host, port, str(e))
            return False
        finally:
            conn.close()


if __name__ == "__main__":
    scanner = NetScanner(sys.argv[1])
    for endpoint in scanner.run():
        print(f"Found HTTP endpoint: {endpoint}")
