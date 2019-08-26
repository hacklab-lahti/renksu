import asyncio
import logging
import os
import serial
import time

import utils

log = logging.getLogger("door")

class BaseDoor:
    def __init__(self):
        self.is_unlocked = False
        self.on_unlocked_change = None

        self.is_open = False
        self.on_open_change = None

    def _set_is_unlocked(self, is_unlocked):
        if is_unlocked != self.is_unlocked:
            self.is_unlocked = is_unlocked
            utils.raise_event(self.on_unlocked_change, is_unlocked)

    def _set_is_open(self, is_open):
        if is_open != self.is_open:
            self.is_open = is_open
            utils.raise_event(self.on_open_change, is_open)

class Door(BaseDoor):
    def __init__(self, settings):
        super().__init__()

        self.settings = settings

        import RPi.GPIO as gpio
        self.gpio = gpio

        self.lock_serial_port = self.settings.get("lock_serial_port")
        self.sensor_gpio_pin = self.settings.getint("sensor_gpio_pin")

        self.baud_rate = 9600
        self.port = None
        self.bytes_left = 0
        self.unlocked_until = 0

    def start(self):
        self.gpio.setmode(self.gpio.BOARD)
        self.gpio.setup(self.sensor_gpio_pin, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)

        self._poll()
        utils.Timer(self._poll, 0.5, True)

    def unlock(self):
        seconds = self.settings.getint("unlock_time_seconds", fallback=10)

        try:
            if seconds <= 0:
                log.warning("Invalid unlock timeout: %ss", seconds)
                return False

            if seconds >= 30:
                log.error("Door unlock timeout too long: %ss", seconds)
                return False

            now = time.time()

            if self.unlocked_until > now:
                log.warning("Door already unlocked")
                return False

            self.unlocked_until = now + seconds

            # 1 byte of data = 10 bits on line (8 data, 1 start, 1 stop)
            self.bytes_left = int(self.baud_rate / 10 * seconds)

            self._close_port()

            self.port = serial.Serial(
                port=self.lock_serial_port,
                baudrate=self.baud_rate,
                timeout=0,
                write_timeout=0)

            asyncio.get_event_loop().add_writer(self.port, self._writer)
            self._writer()

            self._set_is_unlocked(True)

            return True
        except Exception as e:
            log.error("Failed to unlock door", exc_info=e)

            return False

    def lock(self):
        try:
            self._close_port()
        except Exception as e:
            log.error("Failed to lock door", exc_info=e)

    def _poll(self):
        self._set_is_open(self.gpio.input(self.sensor_gpio_pin) == self.gpio.HIGH)

    def _close_port(self):
        if self.port:
            asyncio.get_event_loop().remove_writer(self.port)
            try:
                self.port.close()
            except:
                pass
            self.port = None

            self.unlocked_until = 0
            self._set_is_unlocked(False)

    def _writer(self):
        try:
            if self.bytes_left <= 0:
                self._close_port()
                return

            nwrite = self.port.write(b"\x55" * min(self.bytes_left, 1024))
            self.bytes_left -= nwrite
        except Exception as e:
            log.error("Error in _writer", exc_info=e)

            self.open_until = 0

            try:
                self.port.close()
            except:
                pass

            self.port = None

class MockDoor(BaseDoor):
    def __init__(self, mock, settings):
        super().__init__()

        self.mock = mock
        self.settings = settings

        self.unlock_id = 0

        self.mock.add_listener("c", lambda: self._set_is_open(False))
        self.mock.add_listener("o", lambda: self._set_is_open(True))

    def start(self):
        self.mock.log("Door started")

    def unlock(self):
        seconds = self.settings.getint("unlock_time_seconds", fallback=10)

        if seconds <= 0:
            log.warning("Invalid unlock timeout: %ss", seconds)
            return False

        if seconds >= 30:
            log.error("Door unlock timeout too long: %ss", seconds)
            return False

        if self.is_unlocked:
            log.warning("Door already unlocked")
            return False

        self.unlock_id += 1
        unlock_id = self.unlock_id

        self.unlocked_until = time.time() + seconds

        async def unlock_async():
            self.mock.log("Door is unlocked")
            self._set_is_unlocked(True)

            await asyncio.sleep(seconds)

            if unlock_id != self.unlock_id:
                return

            self.mock.log("Door is locked")
            self._set_is_unlocked(False)

        asyncio.ensure_future(unlock_async())

        return True

    def lock(self):
        self.mock.log("Locking door immediately")
        self._set_is_unlocked(False)
        self.is_unlocked = False
