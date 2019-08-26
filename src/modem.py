import asyncio
import logging
import os
import os.path
import serial
import time

import utils

log = logging.getLogger("modem")

class Modem:
    def __init__(self, settings):
        self.serial_port = settings.get("serial_port")
        self.default_country_prefix = settings.get("default_country_prefix")
        self.mode_switch_usb_id = settings.get("mode_switch_usb_id")
        self.mode_switch_command = settings.get("mode_switch_command")

        self.on_rssi = None
        self.ringing = False
        self.incoming_number = None
        self.on_ring_start = None
        self.on_ring_end = None

        self.poll_interval = 10
        self.prev_line_time = 0
        self.rx_buf = b""
        self.port = None

        self.ring_timeout = 8
        self.prev_ring_time = 0

    def start(self):
        utils.Timer(self._poll, 1, True)

    def hangup(self):
        if self.ringing:
            self._write_ignore_errors("ATH")

    def _poll(self):
        if self.prev_line_time < time.time() - self.poll_interval:
            if not self.port:
                self._open_port()
            else:
                self._write_ignore_errors("AT")

        if self.ringing and self.prev_ring_time < time.time() - self.ring_timeout:
            self._ring_end()

    def _write_ignore_errors(self, line):
        line = (line + "\r\n").encode("ascii")

        try:
            self.port.write(line)
        except Exception as e:
            log.debug("Write error", exc_info=e)

            self._close_port()

    def _close_port(self):
        self._ring_end()

        if self.port:
            asyncio.get_event_loop().remove_reader(self.port)
            self.port.close()

            self.port = None

    def _open_port(self):
        self._close_port()

        if not self._device_present():
            raise Exception("Device not found")

        log.debug("Opening " + self.serial_port)

        self.prev_line_time = 0

        try:
            self.port = serial.Serial(
                port=self.serial_port,
                baudrate=9600,
                dsrdtr=True,
                rtscts=True,
                timeout=0,
                write_timeout=0)
        except Exception as e:
            log.debug("Failed to open port", exc_info=e)
            return

        self._write_ignore_errors("AT")
        self._write_ignore_errors("AT+CLIP=1")

        asyncio.get_event_loop().add_reader(self.port, self._reader)

    def _reader(self):
        try:
            self.rx_buf += self.port.read(1024)

            while True:
                p = self.rx_buf.find(ord(b"\n"))

                if p == -1:
                    break

                line = self.rx_buf[0:p].strip()
                self.rx_buf = self.rx_buf[p+1:]

                self.prev_line_time = time.time()

                if line:
                    try:
                        self._process_line(line.decode("ascii", "ignore"))
                    except:
                        log.error("Error processing modem line: " + str(line))
        except Exception as e:
            log.debug("Uncaught error in _reader", exc_info=e)

            self._close_port()

    def _process_line(self, line):
        if line.startswith("^RSSI:"):
            rssi = int(line.split(":")[1].strip())

            if self.on_rssi:
                self.on_rssi(rssi)
        elif line.startswith("+CLIP:"):
            number = line.split(":")[1].strip().split(",")[0].strip(" \"")
            if number:
                if number.startswith("0"):
                    number = self.default_country_prefix + number[1:]
            else:
                number = None

            if not self.ringing or number != self.ringing_number:
                self.ringing = True
                self.ringing_number = number

                utils.raise_event(self.on_ring_start, number)

            self.prev_ring_time = time.time()
        elif line.startswith("^CEND:"):
            if self.ringing:
                self._ring_end()

    def _ring_end(self):
        if not self.ringing:
            return

        self.ringing = False
        self.ringing_number = None

        utils.raise_event(self.on_ring_end)

    def _device_present(self):
        if os.path.exists(self.serial_port):
            return True

        USB_ROOT = "/sys/bus/usb/devices"

        for usbdev in os.listdir(USB_ROOT):
            usbdev_path = os.path.join(USB_ROOT, usbdev)

            usb_id = (
                "{0}:{1}".format(
                    utils.read_file_ignore_errors(os.path.join(usbdev_path, "idVendor")),
                    utils.read_file_ignore_errors(os.path.join(usbdev_path, "idProduct")))
                .lower())

            if usb_id == self.mode_switch_usb_id:
                log.info("Attempting USB mode switch")

                os.system(self.mode_switch_command)

        return False

class MockModem:
    def __init__(self, mock, settings):
        self.mock = mock
        self.default_country_prefix = settings.get("default_country_prefix")

        self.on_rssi = None
        self.ringing = False
        self.incoming_number = None
        self.on_ring_start = None
        self.on_ring_end = None

        self.mock.add_listener("r", self._ring)
        self.mock.add_listener("h", self._ring_end)

    def start(self):
        self.mock.log("Modem started")

    def hangup(self):
        if self.ringing:
            self.mock.log("Modem hanged up")

    def _ring(self, number=None):
        if number and number.startswith("0"):
            number = self.default_country_prefix + number[1:]

        if not self.ringing or number != self.ringing_number:
            self.ringing = True
            self.ringing_number = number

            utils.raise_event(self.on_ring_start, number)

    def _ring_end(self):
        if not self.ringing:
            return

        self.ringing = False
        self.ringing_number = None

        utils.raise_event(self.on_ring_end)
