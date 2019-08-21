import asyncio
import binascii
import logging
import serial_asyncio
import struct
import utils
from PIL import Image, ImageDraw

__all__ = ["Reader"]

log = logging.getLogger("reader")

class Reader:
    def __init__(self, settings):
        self.settings = settings
        self.queue = []

        self.on_tag_read = None
        self.on_button_change = None

    def start(self):
        asyncio.ensure_future(self._poll_task())

    def set_led(self, on):
        self._send_command(b"L\x01" if on else b"L\x00")

    def beep(self, notes):
        self._send_command(
            b"B"
            + b"".join(struct.pack("<hBB", *n) for n in notes))

    def draw(self, image):
        self._send_command(b"D" + image_to_bytes(image))

    def _sync(self):
        self.beep([])
        self.set_led(False)

        img = Image.new("1", (128, 64))
        draw = ImageDraw.Draw(img)
        draw.line([(10, 15), (15, 20), (25, 10)], fill=1, width=2)

        self.draw(img)

    def _send_command(self, cmd):
        self.queue.insert(
            0,
            cmd.replace(b"\\", b"\\\\").replace(b"\n", b"\\n") + b"\n")

    async def _poll_task(self):
        if not self.settings["PORT"]:
            return

        last_error = None
        while True:
            try:
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self.settings["PORT"],
                    baudrate=115200)

                self._sync()

                while True:
                    if len(self.queue) == 0:
                        await asyncio.sleep(0.020)

                    cmd = self.queue[-1] if len(self.queue) else b"P\n"

                    writer.write(cmd)
                    await writer.drain()

                    try:
                        response = await asyncio.wait_for(reader.readline(), 1)
                    except asyncio.TimeoutError as ex:
                        log.warn("READER: Timeout")
                        await asyncio.sleep(0.1)
                        self._sync()
                        continue

                    if len(self.queue):
                        self.queue.pop()

                    last_error = None

                    self._handle_event(response)

            except Exception as ex:
                msg = str(ex)
                if msg != last_error:
                    last_error = msg
                    log.error("Error: " + msg)

                await asyncio.sleep(1)

    def _handle_event(self, response):
        if len(response) < 2:
            return

        if response[0:1] == b"b" and len(response) == 3:
            utils.raise_event(self.on_button_change, response[1:2] == b"\x01")
        elif response[0:1] == b"r" and len(response) >= 6:
            uid = binascii.hexlify(response[1:-1])
            utils.raise_event(self.on_tag_read, uid)

def image_to_bytes(img):
    data = img.getdata(0)
    result = bytearray()

    for line in range(0, 8):
        for x in range(0, 128):
            byte = 0

            for y in range(line*8, line*8+8):
                byte >>= 1

                if data[y*img.width + x]:
                    byte |= 0x80

            result.append(byte)

    return bytes(result)