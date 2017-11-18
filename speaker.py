import logging
import os
import subprocess

log = logging.getLogger("speaker")

class Speaker:
    def __init__(self):
        pass

    def play(self, name):
        filename = "{}.wav".format(name)

        if not os.path.exists(filename):
            return

        try:
            subprocess.Popen(
                ["aplay", filename],
                stdin=None,
                stdout=None,
                stderr=None,
                close_fds=True)
        except:
            log.error("Failed to play audio", exc_info=e)
