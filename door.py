import asyncio
import RPi.GPIO as gpio
import logging
import mmap
import os
import serial
import time

import utils

__all__ = ["Door"]

log = logging.getLogger("door")

class Door:
    def __init__(self, lock_serial_device, switch_pin):
        self.lock_serial_device = lock_serial_device
        self.switch_pin = switch_pin

        self.is_open = None
        self.on_open_change = None

        self.is_unlocked = False

        #self.baud_rate = 9600
        self.baud_rate = 9600
        self.port = None
        self.bytes_left = 0
        self.unlocked_until = 0

    def start(self):
        gpio.setmode(gpio.BOARD)
        gpio.setup(self.switch_pin, gpio.IN, pull_up_down=gpio.PUD_UP)

        utils.start_timer(self._poll, 0.5)

    def _poll(self):
        new_is_open = (gpio.input(self.switch_pin) == gpio.HIGH)

        if new_is_open != self.is_open:
            self.is_open = new_is_open

            utils.raise_event(self.on_open_change, new_is_open)

    def unlock(self, seconds):
        try:
            if seconds <= 0:
                log.warning("Invalid unlock timeout: %ss", seconds)
                return

            if seconds >= 30:
                log.error("Door unlock timeout too long: %ss", seconds)
                return

            now = time.time()

            if self.unlocked_until > now:
                log.warning("Door already unlocked")
                return

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

            self.is_unlocked = True
        except Exception as e:
            log.error("Failed to unlock door", exc_info=e)

    def _close_port(self):
        if self.port:
            asyncio.get_event_loop().remove_writer(self.port)
            try:
                self.port.close()
            except:
                pass
            self.port = None

            self.unlocked_until = 0
            self.is_unlocked = False

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
