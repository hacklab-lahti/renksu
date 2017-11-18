import asyncio
import logging
import os
import os.path
import serial
import time

import settings
import utils

__all__ = ["Modem"]

log = logging.getLogger("modem")

class Modem:
    def __init__(self, usb_id, usb_config_interface, default_country_prefix,
            mode_switch_usb_id=None, mode_switch_curse=None):
        self.usb_id = usb_id.lower()
        self.usb_config_interface = usb_config_interface
        self.default_country_prefix = default_country_prefix
        self.mode_switch_usb_id = mode_switch_usb_id
        self.mode_switch_curse = mode_switch_curse

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
        utils.start_timer(self._poll, 1)

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

        dev = self._find_device()
        if dev is None:
            raise Exception("Device not found")

        log.debug("Opening " + dev)

        self.prev_line_time = 0

        try:
            self.port = serial.Serial(
                port=dev,
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
        #log.debug("Got: " + line)

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

    def _find_device(self):
        USB_ROOT = "/sys/bus/usb/devices"

        for usbdev in os.listdir(USB_ROOT):
            usbdev_path = os.path.join(USB_ROOT, usbdev)

            usb_id = (
                "{0}:{1}".format(
                    utils.read_file_ignore_errors(os.path.join(usbdev_path, "idVendor")),
                    utils.read_file_ignore_errors(os.path.join(usbdev_path, "idProduct")))
                .lower())

            if usb_id == self.usb_id:
                tty_iface_path = os.path.join(usbdev_path,
                    "{0}:{1}".format(usbdev, self.usb_config_interface))

                if os.path.exists(tty_iface_path):
                    tty_name = next((
                        n
                        for n
                        in os.listdir(tty_iface_path)
                        if n.startswith("ttyUSB")), None)

                    if tty_name:
                        return "/dev/{0}".format(tty_name)
            elif usb_id == self.mode_switch_usb_id:
                os.system(self.mode_switch_curse)

        return None

if __name__ == "__main__":
    import logging.config
    logging.config.fileConfig("logging.ini")

    print("Testing Modem")

    import settings

    modem = Modem(
        usb_id=settings.MODEM_USB_ID,
        usb_config_interface=settings.MODEM_TTY_CONFIG_INTERFACE,
        default_country_prefix=settings.MODEM_DEFAULT_COUNTRY_PREFIX,
        mode_switch_usb_id=settings.MODEM_MODE_SWITCH_USB_ID,
        mode_switch_curse=settings.MODEM_MODE_SWITCH_CURSE)
    modem.on_ring_start = lambda num: print("Incoming call from {}".format(num))
    modem.on_ring_end = lambda: print("Incoming call ended.")
    modem.on_rssi = lambda rssi: print("RSSI: {}".format(rssi))

    modem.start()

    utils.run_event_loop()
