import threading
from pubsub import pub
from .direnum import DirectoryEnumerator


class WebEnumerator(threading.Thread):
    def __init__(self):
        super().__init__()
        self.dir_enumerator = None
        self.netscan_done = False
        pub.subscribe(self.on_endpoint_detected, 'netscanner_endpoint_detected')
        pub.subscribe(self.on_netscan_done, 'netscanner_done')

    def run(self):
        while not self.netscan_done:
            threading.Event().wait(1)

        self.dir_enumerator.join()
        pub.sendMessage('webenum_done')

    def on_endpoint_detected(self, host, port):
        base_url = f"http://{host}:{port}"
        if self.dir_enumerator is None:
            self.dir_enumerator = DirectoryEnumerator(base_url, workers=5)
            self.dir_enumerator.start()
        else:
            self.dir_enumerator.add_base_url(base_url)

    def on_netscan_done(self):
        self.netscan_done = True
