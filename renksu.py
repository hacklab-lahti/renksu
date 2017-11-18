import logging, logging.config
logging.config.fileConfig("logging.ini")

import asyncio

import database
import door
import modem
import settings
import speaker
import utils

log = logging.getLogger("renksu")
audit_log = logging.getLogger("audit")

class Renksu:
    def __init__(self):
        self.db = database.Database(
            address=settings.DATABASE_ADDRESS,
            update_interval=settings.DATABASE_UPDATE_INTERVAL_SECONDS)

        self.speaker = speaker.Speaker()

        self.modem = modem.Modem(
            usb_id=settings.MODEM_USB_ID,
            usb_config_interface=settings.MODEM_TTY_CONFIG_INTERFACE,
            default_country_prefix=settings.MODEM_DEFAULT_COUNTRY_PREFIX,
            mode_switch_usb_id=settings.MODEM_MODE_SWITCH_USB_ID,
            mode_switch_curse=settings.MODEM_MODE_SWITCH_CURSE)

        self.modem.on_ring_start = self.ring_start
        self.modem.on_ring_end = self.ring_end
        #self.modem.on_rssi = lambda rssi: log.debug("RSSI: %s", rssi)

        self.door = door.Door(
            lock_serial_device=settings.DOOR_LOCK_SERIAL_DEVICE,
            switch_pin=settings.DOOR_SWITCH_PIN)
        self.door.on_open_change = self.door_open_change

        self.last_unlocked_by = None

    def start(self):
        log.info("Starting up")

        self.db.start()
        self.door.start()
        self.modem.start()

    def ring_doorbell(self):
        self.speaker.play("doorbell")

    async def ring_start(self, number):
        audit_log.info("Incoming call from %s", number)

        if number is None:
            self.ring_doorbell()
            audit_log.info("-> Unknown number!")
            return

        member = await self.db.get_member_info(number)

        if member is None:
            self.ring_doorbell()
            audit_log.info("-> Number not in database!")
            return

        if not member.is_active:
            self.ring_doorbell()
            audit_log.info("-> Not an active member!")
            return

        audit_log.info("Opening door for %s", member.display_name)

        self.last_unlocked_by = member
        self.door.unlock(settings.DOOR_PHONE_OPEN_TIME_SECONDS)

        self.modem.hangup()

        self.speaker.play("bleep")

    def ring_end(self):
        log.info("Incoming call ended.")

    def door_open_change(self, is_open):
        if is_open:
            if self.door.is_unlocked:
                audit_log.info("Door opened while unlocked by %s.",
                    self.last_unlocked_by.display_name)
            else:
                audit_log.info("Door opened manually.")
        else:
            audit_log.info("Door closed.")

app = Renksu()
app.start()

utils.run_event_loop()
