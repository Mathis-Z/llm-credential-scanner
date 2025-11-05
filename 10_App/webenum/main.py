import sys
from .direnum import DirectoryEnumerator


class WebEnumerator:
    def __init__(self):
        pass

    def find_login_panels(self, endpoint: str) -> list[str]:
        panels = []

        #TODO: handle https
        denum = DirectoryEnumerator(f"http://{endpoint}", panels.append, workers=5)
        denum.run()

        return panels



if __name__ == "__main__":
    enumerator = WebEnumerator()
    enumerator.find_login_panels(sys.argv[1])
