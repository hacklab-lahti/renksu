import asyncio
import binascii
import logging
import math
import re
import simpleaudio
import serial_asyncio
import struct
import time
import utils
from PIL import Image, ImageDraw, ImageFont

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

def load_icons(file, size, names):
    source = Image.open(file)
    source.load()

    return {
        name:source.crop((i * size, 0, (i + 1) * size, size))
        for i, name
        in enumerate(names)
    }

def mml(mml):
    NOTES = { "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11 }
    r = []
    octave = 0

    for m in re.finditer(r"(\s+)|([A-ZR])(#?)(\d+)|([<>])|(O\d+)|(.)", mml):
        _, n_name, n_sharp, n_len, o_adjust, o_set, error = m.groups()

        if n_name == "R":
            r.append((0, int(n_len), 0))
        elif n_name:
            semitone = (octave * 12) + NOTES[n_name] + (1 if n_sharp else 0) + 3
            freq = int(2 ** (semitone / 12) * 440)

            r.append((freq, int(n_len), 128))
        elif o_adjust:
            octave += (-1 if o_adjust == "<" else 1)
        elif o_set:
            octave = int(o_set)
        elif error:
            log.warn("Invalid MML string: %s", mml)
            return []

    return r

class Draw:
    def __init__(self, reader):
        self.reader = reader
        self.img = Image.new("1", (128, 64))
        self.draw = ImageDraw.Draw(self.img)
        setattr(self.draw, "paste", self.img.paste)

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

        self.font = ImageFont.load(utils.basedir() + "res/spleen.pil")

        self.icons20 = load_icons(utils.basedir() + "res/icons-20.png", 20, [
            "enter_0", "enter_1", "enter_2", "enter_3", "enter_4",
            "tag", "phone", "lock", "x", "error", "unknown",
        ])

        self.icons40 = load_icons(utils.basedir() + "res/icons-40.png", 40, [
            "bell_0", "bell_1", "bell_2", "bell_3",
            "unlocked", "locked",
        ])

    def draw(self):
        return Draw(self)

    def _sad_sound(self):
        self.beep([(523, 20, 32), (0, 10, 0), (494, 60, 32)])

    @sequence
    async def show_unknown(self, msg, sound=False):
        if sound:
            self.beep(mml("A#20 R10 A60"))

        with self.draw() as draw:
            draw.paste(self.icons20["unknown"], (0, 2))

            draw.text((25, 0), msg.replace(" ", "\n"), fill=1, font=self.font)

        await asyncio.sleep(5)

    @sequence
    async def show_membership_not_active(self, member):
        self.beep(mml("A#20 R10 A60"))

        expires = time.strftime("%Y-%m-%d", time.localtime(member.active_until))

        with self.draw() as draw:
            draw.paste(self.icons20["error"], (0, 4))

            draw.text((24, 2), "Expired", fill=1, font=self.font)
            draw.text((0, 30), expires, fill=1, font=self.font)

        await asyncio.sleep(5)

    @sequence
    async def show_unlocked(self, member, unlocked_until, method):
        is_expired = (member.get_days_until_expiration() < 0)
        expires = time.strftime("%Y-%m-%d", time.localtime(member.active_until))

        start = time.time()
        buzz = [(440, 200, 16)] * math.ceil(unlocked_until - start)
        if is_expired:
            self.beep(mml("A#10 R10 A#10 R10 A#10 R50 A#10 R10 A#10 R10 A#10") + buzz)
        else:
            self.beep(mml("A#10 R10 > F10 R10 A#10 R10 > F10") + buzz)

        self.set_led(True)

        i = 0
        while time.time() < unlocked_until:
            with self.draw() as draw:
                draw.paste(self.icons20[method], (0, 4))

                draw.text((24, 2), member.public_name or member.name, fill=1, font=self.font)

                if is_expired and (i % 10) < 5:
                    draw.rectangle((0, 28, 128, 48), fill=1)
                    draw.text((0, 26), expires, fill=0, font=self.font)
                else:
                    draw.text((0, 26), expires, fill=1, font=self.font)

                w = int((unlocked_until - time.time()) / ((unlocked_until - start) or 1) * 128)
                draw.rectangle((0, 56, w, 63), fill=1)
                draw.rectangle((0, 56, 127, 63), outline=1, width=1)

            await asyncio.sleep(0.1)

            i += 1

        self.set_led(False)

        self.show_locked()

    @sequence
    async def show_locked(self):
        self.beep([
            (1852, 5, 32),
            (0, 10, 0),
            (924, 5, 32),
        ])

        for _ in range(3):
            with self.draw() as draw:
                draw.paste(self.icons40["locked"], (64 - 20, 32 - 20))

            await asyncio.sleep(0.5)

            with self.draw() as draw:
                pass

            await asyncio.sleep(0.5)

    @sequence
    async def show_doorbell(self):
        self.beep(
            [
                (1852, 10, 128), (0, 10, 128),
                (1392, 10, 128), (0, 10, 128),
                (1852, 10, 128), (0, 10, 128),
                (1392, 10, 128), (0, 100, 128),
            ] * 2)

        for i in range(0, 8):
            with self.draw() as draw:
                draw.paste(self.icons40["bell_{}".format(i % 4)], (64 - 20, 32 - 20))

            self.set_led((i % 4) < 2)

            await asyncio.sleep(0.25)

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
        if not self.settings.get("serial_port", fallback=None):
            return

        last_error = None
        while True:
            try:
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self.settings.get("serial_port", fallback=None),
                    baudrate=115200)

                self._reset()

                cur_cmd = None

                while True:
                    if len(self.queue) == 0:
                        await asyncio.sleep(0.020)

                    if not cur_cmd:
                        cur_cmd = self.queue.pop() if len(self.queue) else b"P\n"

                    #if cur_cmd != b"P\n":
                    #    print("write", cur_cmd[:10])

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

                    await asyncio.sleep(0.001)

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

                encoded += chr(c + 0x2800)

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
