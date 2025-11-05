import click

from netscan import NetScanner
from webenum import WebEnumerator

@click.command()
@click.argument("subnets")
def run(subnets):
    subnets = [sub for sub in subnets.split(",") if sub.strip()]
    endpoints = []

    for subnet in subnets:
        scanner = NetScanner()
        endpoints.extend(scanner.scan_subnet(subnet))

    print("All subnets scanned")
    for endpoint in endpoints:
        print(endpoint)

    for endpoint in endpoints:
        enumerator = WebEnumerator()
        login_panels = enumerator.find_login_panels(endpoint)
        for panel in login_panels:
            print(f"Found login panel: {panel}")

if __name__ == '__main__':
    run()
