import asyncio
import serial_asyncio

__all__ = ["Reader"]

class Reader:
    def __init__(self, settings):
        self.settings = settings
        self.queue = []

    def start(self):
        asyncio.ensure_future(self._poll_task())

    def set_led(self, on):
        self._send_command(b"L\x01" if on else b"L\x00")

    def beep(self, notes):


    def _send_command(self, cmd):
        self.queue.insert(0, cmd.replace("\\", "\\\\").replace("\n", "\\n") + b"\n")

    async def _poll_task(self):
        while True:
            try:
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self.settings["PORT"],
                    baudrate=115200)

                while True:
                    cmd = self.queue[-1] if len(self.queue) else b"P\n"

                    writer.write(cmd)
                    await writer.drain()

                    try:
                        response = await asyncio.wait_for(reader.readline(), 0.1)
                    except asyncio.TimeoutError as ex:
                        print("READER: Timeout")
                        continue

                    if len(self.queue):
                        self.queue.pop()

                    if response != b"p\n":
                        if response == b'b\x01\n':
                            self.set_led(True)
                        elif response == b'b\x00\n':
                            self.set_led(False)

            except Exception as ex:
                print("READER: Failed to open port")
                await asyncio.sleep(1)
