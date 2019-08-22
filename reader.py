import asyncio
import binascii
import logging
import math
import simpleaudio
import serial_asyncio
import struct
import time
import utils
from PIL import Image, ImageDraw, ImageFont

__all__ = ["Reader"]

log = logging.getLogger("reader")

# otf2bdf -l "45 48_57" -p 40 -o dejavu.bdf /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
# >>> from PIL import BdfFontFile
# >>> b = BdfFontFile.BdfFontFile(open("dejavu.bdf", "rb"))
# >>> b.save("dejavu")

# beep format = [(freq is Hz, length in units of 10ms 0-255, duty cycle 0-255)]

def sequence(func):
    def wrapper(self, *args, **kwargs):
        async def async_wrapper():
            await func(self, *args, **kwargs)

            self.beep([])
            self.set_led(False)
            with self.draw():
                pass

        if self.current_seq:
            self.current_seq.cancel()
            self.beep([])

        self.current_seq = utils.run_background(async_wrapper())

    return wrapper

class Draw:
    def __init__(self, reader):
        self.reader = reader
        self.img = Image.new("1", (128, 64))
        self.draw = ImageDraw.Draw(self.img)

    def __enter__(self):
        return self.draw

    def __exit__(self, exception_type, *args):
        if not exception_type:
            self.reader.draw_image(self.img)

class BaseReader:
    def __init__(self):
        self.on_tag_read = None
        self.on_button_change = None

        self.current_seq = None

        self.font_large = ImageFont.load("res/dejavu.pil")

    def draw(self):
        return Draw(self)

    def _sad_sound(self):
        self.beep([(523, 20, 32), (0, 10, 0), (494, 60, 32)])

    @sequence
    async def show_error(self, msg, sound=False):
        if sound:
            self._sad_sound()

        with self.draw() as draw:
            draw.text((10, 10), msg, fill=1)

        await asyncio.sleep(1)

    @sequence
    async def show_membership_not_active(self, member):
        self._sad_sound()

        with self.draw() as draw:
            draw.text((10, 10), "not active!", fill=1)

        await asyncio.sleep(1)

    @sequence
    async def show_unlocked(self, member):
        ##self.beep([(600, 200, 128)] * 30)

        self.beep(
            [
                (924, 10, 128), (0, 10, 128),
                (1392, 10, 128), (0, 10, 128),
                (1852, 10, 128), (0, 10, 128),
                (2761, 10, 128), (0, 10, 128),
            ]
            + [(100, 200, 16)] * 30)

        with self.draw() as draw:
            draw.text((10, 10), "Hi, " + member.name, fill=1)

        print("ok")
        await asyncio.sleep(30)

    @sequence
    async def show_locked(self):
        self.beep([])

        with self.draw() as draw:
            draw.text((10, 10), "L O C K E D", fill=1)

        await asyncio.sleep(2)

    @sequence
    async def show_doorbell(self):
        #self.beep([(370, 100, 128), (380, 100, 10), (0, 20, 0), (294, 200, 128)])

        p1 = []
        p2 = []
        for i in range(128, 28, -1):
            p1.append((370, 2, i))
            p2.append((294, 2, i))

        self.beep(p1 + [(0, 20, 0)] + p2)

        for i in range(0, 6):

            with self.draw() as draw:
                text = "clock" if (i & 1) else "door"
                draw.text((10, 10), text, fill=1)

            self.set_led(not (i & 1))

            await asyncio.sleep(1)

class Reader(BaseReader):
    def __init__(self, settings):
        super().__init__()

        self.settings = settings
        self.queue = []

        self.prev_tag_read = None
        self.prev_tag_read_time = None

    def start(self):
        utils.run_background(self._poll_task())

    def set_led(self, on):
        self._send_command(b"L\x01" if on else b"L\x00")

    def beep(self, notes):
        self._send_command(
            b"B"
            + b"".join(struct.pack("<hBB", *n) for n in notes))

    def draw_image(self, image):
        data = image.getdata(0)
        encoded = bytearray()

        for line in range(0, 8):
            for x in range(0, 128):
                byte = 0

                for y in range(line*8, line*8+8):
                    byte >>= 1

                    if data[y*image.width + x]:
                        byte |= 0x80

                encoded.append(byte)

        self._send_command(b"D" + encoded)

    def _reset(self):
        self.queue = []
        self._send_command(b"R")

        with self.draw():
            pass

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

                self._reset()

                cur_cmd = None

                while True:
                    if len(self.queue) == 0:
                        await asyncio.sleep(0.020)

                    if not cur_cmd:
                        cur_cmd = self.queue.pop() if len(self.queue) else b"P\n"

                    if cur_cmd != b"P\n":
                        print("write", cur_cmd[:10])

                    writer.write(cur_cmd)
                    await writer.drain()

                    try:
                        response = await asyncio.wait_for(reader.readline(), 1)
                    except asyncio.TimeoutError as ex:
                        log.warn("READER: Timeout")
                        await asyncio.sleep(0.1)
                        self._reset()
                        continue

                    cur_cmd = None
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
            uid = binascii.hexlify(response[1:-1]).decode("utf-8")

            now = time.time()

            if uid and self.prev_tag_read == uid:
                if now < self.prev_tag_read_time + 1:
                    self.prev_tag_read_time = now
                    return

            self.prev_tag_read = uid
            self.prev_tag_read_time = now

            utils.raise_event(self.on_tag_read, uid)

class MockReader(BaseReader):
    def __init__(self, mock):
        super().__init__()

        self.mock = mock

        self.play_object = None

        self.mock.add_listener("b", self._button_press)
        self.mock.add_listener("t", self._tag_read)

    def start(self):
        pass

    def set_led(self, on):
        pass

    def beep(self, notes):
        if self.play_object:
            self.play_object.stop()
            self.play_object = None

        if len(notes) == 0:
            return

        RATE = 44100
        angle = 0
        data = bytearray()

        for (freq, length, duty) in notes:
            step = freq * 2 * math.pi / RATE

            for t in range(0, int(length * 0.005 * RATE)):
                sample = (math.sin(angle) + math.sin(angle * 3) / 3 + math.sin(angle * 5) / 5
                    + math.sin(angle * 7) / 7 + math.sin(angle * 9) / 9) * (duty / 128)
                isample = int(sample * ((2 << 14) - 1))
                angle += step

                data += struct.pack("<h", isample)

        self.play_object = simpleaudio.play_buffer(data, 1, 2, RATE)

    def draw_image(self, image):
        data = image.getdata(0)

        encoded = ""
        encoded += "┌" + "─" * 64 + "┐\n"

        for cy in range(0, 64, 4):
            encoded += "│"

            for cx in range(0, 128, 2):
                c = 0

                for x, y in [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]:
                    c >>= 1
                    if data[(cy + y)*image.width + (cx + x)]:
                        c |= 0x80

                encoded += chr(c | 0x2800)

            encoded += "│\n"

        encoded += "└" + "─" * 64 + "┘\n"

        self.mock.log("Displaying: \n" + encoded)

    def _button_press(self):
        async def simulate():
            self.mock.log("Reader button pressed")
            utils.raise_event(self.on_button_change, True)

            await asyncio.sleep(1)

            self.mock.log("Reader button released")
            utils.raise_event(self.on_button_change, False)

        utils.run_background(simulate())

    def _tag_read(self, uid):
        utils.raise_event(self.on_tag_read, uid)
