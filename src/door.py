import asyncio
import logging
import os
import serial
import time

import utils

__all__ = ["Door"]

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
    def __init__(self, lock_serial_device, switch_pin):
        super().__init__()

        import RPi.GPIO as gpio
        self.gpio = gpio

        self.lock_serial_device = lock_serial_device
        self.switch_pin = switch_pin

        self.baud_rate = 9600
        self.port = None
        self.bytes_left = 0
        self.unlocked_until = 0

    def start(self):
        self.gpio.setmode(self.gpio.BOARD)
        self.gpio.setup(self.switch_pin, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)

        self._poll()
        utils.Timer(self._poll, 0.5, True)

    def unlock(self, seconds):
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
                port=self.lock_serial_device,
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
        self._set_is_open(self.gpio.input(self.switch_pin) == self.gpio.HIGH)

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
    def __init__(self, mock):
        super().__init__()

        self.mock = mock

        self.unlock_id = 0

        self.mock.add_listener("c", lambda: self._set_is_open(False))
        self.mock.add_listener("o", lambda: self._set_is_open(True))

    def start(self):
        self.mock.log("Door started")

    def unlock(self, seconds):
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

if __name__ == "__main__":
    import logging.config
    logging.config.fileConfig("logging.ini")

    print("Testing Door")

    import settings

    def open_change(is_open):
        print("Door is {}.".format( "open" if is_open else "closed"))

        if not is_open:
            print("Unlocking the door!")
            door.unlock(5)

    door = Door(
        lock_serial_device=settings.DOOR_LOCK_SERIAL_DEVICE,
        switch_pin=settings.DOOR_SWITCH_PIN)
    door.on_open_change = open_change

    door.start()

    utils.run_event_loop()
