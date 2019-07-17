# Extremely silly user interface for manual testing. Requires tmux because implementing an actual
# terminal UI is a lot of work.

import asyncio
import logging
import os
import subprocess
import sys

import renksu
import utils

log = logging.getLogger("MOCK")

FIFO_PATH = "/tmp/renksu_mock.fifo"

class MockInterface:
    def __init__(self):
        self.fifo = open(FIFO_PATH, "rb", 0)
        self.log("FIFO opened")

        self.listeners = {}

        asyncio.get_event_loop().add_reader(self.fifo, self._reader)

    def log(self, msg):
        log.info(msg)

    def add_listener(self, cmd, func):
        self.listeners[cmd] = func

    def _reader(self):
        data = self.fifo.read(1024)
        if len(data) == 0:
            asyncio.get_event_loop().remove_reader(self.fifo)
            log.info("FIFO closed")
            sys.exit(0)
            return

        cmd, *args = data.decode("utf-8").split()

        if not cmd in self.listeners:
            self.log("Unknown command: {}".format(cmd))

        self.listeners[cmd](*args)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "1":
        app = renksu.Renksu(MockInterface())
        app.start()

        utils.run_event_loop()
    else:
        if os.path.exists(FIFO_PATH):
            os.unlink(FIFO_PATH)
        os.mkfifo(FIFO_PATH, 0o600)
        subprocess.call([
            "tmux",
            "new-session", "venv/bin/python3 {} 1 || cat > /dev/null".format(sys.argv[0]), ";",
            "split-window", "cat > {}".format(FIFO_PATH), ";",
            "resize-pane", "-t", "1", "-y", "2"])