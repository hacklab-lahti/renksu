import asyncio
import logging
import os, os.path
import simpleaudio
import subprocess
import tempfile
import time
import threading

log = logging.getLogger("speaker")

class Speaker:
    def __init__(self, sounds):
        self.sounds = {}
        self.playing = {}

        for name in sounds:
            filename = "res/{}.wav".format(name)

            if not os.path.exists(filename):
                continue

            self.sounds[name] = simpleaudio.WaveObject.from_wave_file(filename)

    def play(self, name):
        if name not in self.sounds:
            return

        if name in self.playing:
            self.playing[name].stop()

        self.playing[name] = self.sounds[name].play()

    def say(self, text, delay=0):
        t = threading.Thread(target=self._say_thread, args=(text, delay))
        t.start()

    def _say_thread(self, text, delay):
        try:
            fd, path = tempfile.mkstemp(".wav")

            subprocess.run(
                ["pico2wave", "--wave=" + path, text],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)

            time.sleep(delay)

            subprocess.run(
                ["aplay", path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
        except Exception as e:
            log.error("Failed to run TTS", exc_info=e)
        finally:
            if os.path.exists(path):
                os.unlink(path)

class MockSpeaker:
    def __init__(self, mock):
        self.mock = mock

    def play(self, name):
        self.mock.log("Playing sound: {}".format(name))

    def say(self, text, delay=0):
        async def say_async():
            await asyncio.sleep(delay)
            self.mock.log("Text-to-speech: {}".format(text))

        asyncio.ensure_future(say_async())

if __name__ == "__main__":
    speaker = Speaker()
    speaker.say("Four days remaining")