import logging, logging.config
logging.config.fileConfig("logging.ini")

import asyncio

import database
import door
import modem
import settings
import speaker
import time
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

        self.say_after_open_text = None
        self.say_after_open_time = 0

    def start(self):
        log.info("Starting up")

        self.db.start()
        self.door.start()
        self.modem.start()

    def ring_doorbell(self):
        self.speaker.play("doorbell")

    def say_after_open(self, text):
        self.say_after_open_text = text
        self.say_after_open_time = time.time()

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

        days_left = member.get_days_until_expiration()

        audit_log.info("Membership days left: {}".format(days_left))

        if days_left <= 0:
            if (settings.MEMBERSHIP_GRACE_PERIOD_DAYS
                    and -days_left < settings.MEMBERSHIP_GRACE_PERIOD_DAYS):
                self.say_after_open("Membership expired. {} days of grace period remaining.".format(
                    settings.MEMBERSHIP_GRACE_PERIOD_DAYS + days_left))
            else:
                self.ring_doorbell()
                audit_log.info("-> Not an active member!")
                return
        else:
            if (settings.MEMBERSHIP_REMAINING_MESSAGE_DAYS
                    and days_left <= settings.MEMBERSHIP_REMAINING_MESSAGE_DAYS):
                self.say_after_open("{} days remaining.".format(days_left))

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

            if self.say_after_open_text and (time.time() - self.say_after_open_time) < 30:
                self.speaker.say(self.say_after_open_text, delay=4)
                self.say_after_open_text = None
        else:
            audit_log.info("Door closed.")

app = Renksu()
app.start()

utils.run_event_loop()
