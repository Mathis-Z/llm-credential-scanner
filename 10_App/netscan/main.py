"""
Network scanner module.
This should return a list of (host, port) pairs to be further enumerated by the next modules
"""

import sys
import logging
import http.client
import nmap3


class NetScanner:
    """This should later become a thread so it can run in the background while other modules are running"""

    def __init__(self):
        pass

    def scan_subnet(self, subnet: str) -> list[str]:
        """Scan the given subnet and return a list of detected HTTP endpoints as host:port strings."""
        nmap = nmap3.NmapHostDiscovery()
        result = nmap.nmap_portscan_only(subnet)
        endpoints = []

        for host, data in result.items():
            if host not in ['runtime', 'stats', 'task_results'] and data['state']['state'] == 'up':
                for port_info in data.get('ports', []):
                    endpoints.append(f"{host}:{port_info['portid']}")

        logging.debug("Discovered endpoints: %s", endpoints)

        return [ep for ep in endpoints if self.test_http_endpoint(ep)]

    def test_http_endpoint(self, endpoint: str) -> bool:
        """Test if an HTTP service is running on the given host:port endpoint."""

        host, port = endpoint.split(':')
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
    scanner = NetScanner()
    for endpoint in scanner.scan_subnet(sys.argv[1]):
        print(f"Found open port: {endpoint}")
