import logging, logging.config
logging.config.fileConfig("logging.ini")

import asyncio
import sys
import time

import database
import door
import modem
import mqtt
import reader
import settings
import speaker
import telegram
import utils

log = logging.getLogger("renksu")
audit_log = logging.getLogger("audit")

class Renksu:
    def __init__(self, mock=None):
        self.db = database.Database(
            address=settings.DATABASE_ADDRESS,
            update_interval=settings.DATABASE_UPDATE_INTERVAL_SECONDS)

        #self.speaker = (
        #    speaker.MockSpeaker(mock) if mock
        #    else speaker.Speaker(["ding", "dong", "bleep"]))
        self.speaker = speaker.Speaker(["ding", "dong", "bleep"])

        self.telegram = (
            telegram.MockTelegram(mock) if mock
            else telegram.Telegram(settings.TELEGRAM))

        self.modem = (
            modem.MockModem(
                mock,
                default_country_prefix=settings.MODEM_DEFAULT_COUNTRY_PREFIX) if mock
            else modem.Modem(
                usb_id=settings.MODEM_USB_ID,
                usb_config_interface=settings.MODEM_TTY_CONFIG_INTERFACE,
                default_country_prefix=settings.MODEM_DEFAULT_COUNTRY_PREFIX,
                mode_switch_usb_id=settings.MODEM_MODE_SWITCH_USB_ID,
                mode_switch_curse=settings.MODEM_MODE_SWITCH_CURSE))

        self.modem.on_ring_start = self.ring_start
        self.modem.on_ring_end = self.ring_end
        #self.modem.on_rssi = lambda rssi: log.debug("RSSI: %s", rssi)

        self.door = (
            door.MockDoor(mock) if mock
            else door.Door(
                lock_serial_device=settings.DOOR["LOCK_SERIAL_DEVICE"],
                switch_pin=settings.DOOR["SWITCH_PIN"]))
        self.door.on_open_change = self.door_open_change

        self.reader = reader.Reader(settings=settings.READER)
        self.reader.on_button_change = self.doorbell_button_change

        self.last_unlocked_by = None
        self.last_opened_at = None

        self.say_after_open_text = None
        self.say_after_open_time = 0

        self.mqtt = mqtt.MqttClient(settings.MQTT)
        self.mqtt.on_light_on_change = self.light_on_change

        self.presence_timer = None
        self.presence_members = {}
        self.presence = None

    def start(self):
        log.info("Starting up")

        self.mqtt.start()
        self.db.start()
        self.door.start()
        self.modem.start()
        self.reader.start()

    async def ring_doorbell(self):
        self.speaker.play("ding")
        await asyncio.sleep(1)
        self.speaker.play("dong")

    def doorbell_button_change(self, pushed):
        if pushed:
            async def blink():
                self.reader.set_led(True)
                await asyncio.sleep(0.2)
                self.reader.set_led(False)

            asyncio.ensure_future(blink())

        self.speaker.play("ding" if pushed else "dong")

    def say_after_open(self, text):
        self.say_after_open_text = text
        self.say_after_open_time = time.time()

    async def ring_start(self, number):
        audit_log.info("Incoming call from %s", number)

        if number is None:
            self.mqtt.publish("ring/hidden_number", None)

            audit_log.info("-> Hidden number!")
            asyncio.ensure_future(self.ring_doorbell())
            self.telegram.message("\U0001F514 Joku soitti ovikelloa piilotetusta numerosta.")
            return

        member = await self.db.get_member_info(number)

        if member is None:
            self.mqtt.publish("ring/number_not_in_database", None)

            audit_log.info("-> Number not in database!")
            asyncio.ensure_future(self.ring_doorbell())
            self.telegram.message("\U0001F514 Joku soitti ovikelloa numerosta, joka ei ole jäsenrekisterissä.")
            return

        await self.maybe_unlock_for_member(member)

    async def maybe_unlock_for_member(self, member):
        now = time.time()

        days_left = member.get_days_until_expiration()

        audit_log.info("Membership days left: {}".format(days_left))

        if days_left <= 0:
            if (settings.MEMBERSHIP_GRACE_PERIOD_DAYS
                    and -days_left < settings.MEMBERSHIP_GRACE_PERIOD_DAYS):
                self.say_after_open("Membership expired. Days of grace period remaining: {}".format(
                    settings.MEMBERSHIP_GRACE_PERIOD_DAYS + days_left))
            else:
                audit_log.info("-> Not an active member!")
                asyncio.ensure_future(self.ring_doorbell())

                self.mqtt.publish("ring/member_not_active", member.get_public_name())

                self.telegram.message("\U000026D4 {} soitti ovikelloa, koska tilankäyttöoikeus ei ole voimassa."
                    .format(member.get_public_name()))

                return
        else:
            if (settings.MEMBERSHIP_REMAINING_MESSAGE_DAYS
                    and days_left <= settings.MEMBERSHIP_REMAINING_MESSAGE_DAYS):
                self.say_after_open("Days remaining: {}".format(days_left))

        self.mqtt.publish("ring/unlocked", member.get_public_name())

        audit_log.info("Opening door for %s", member.display_name)

        last_presence = self.presence_members.get(member.id, 0)
        if now - last_presence >= settings.PRESENCE["PRESENCE_TIMEOUT_SECONDS"]:
            self.presence_members[member.id] = now
            self.telegram.message("\U0001F6AA {} avasi oven.".format(member.get_public_name()))

        self.last_unlocked_by = member
        self.door.unlock(settings.DOOR["PHONE_OPEN_TIME_SECONDS"])

        self.speaker.play("bleep")

        await asyncio.sleep(2)

        self.modem.hangup()

    def ring_end(self):
        log.info("Incoming call ended.")

    def door_open_change(self, is_open):
        now = time.time()

        if is_open:
            self.last_opened_at = now

            if self.door.is_unlocked:
                audit_log.info("Door opened while unlocked by %s.",
                    self.last_unlocked_by.display_name)
            else:
                audit_log.info("Door opened manually.")

                if not self.presence:
                    self.telegram.message("\U0001F5DD Joku avasi oven manuaalisesti")

            if self.say_after_open_text and (time.time() - self.say_after_open_time) < 30:
                self.speaker.say(self.say_after_open_text, delay=3)
                self.say_after_open_text = None
        else:
            audit_log.info("Door closed.")

            if (self.door.is_unlocked
                    and self.last_opened_at
                    and now - self.last_opened_at >= settings.DOOR["RELOCK_DEBOUNCE_TIMEOUT_SECONDS"]):
                audit_log.info("Relocking")
                self.door.lock()

        self.mqtt.publish("door_open", "1" if is_open else "0", True)

        self.update_presence()

    def light_on_change(self, light_on):
        if light_on and not self.presence:
            self.telegram.message("\U0001F4A1 Valot päällä, labi ei olekaan tyhjillään")

        self.update_presence()

    def update_presence(self):
        new_presence = self.mqtt.light_on or self.door.is_open

        if self.presence_timer:
            self.presence_timer.cancel()

        if new_presence != self.presence:
            def set_presence():
                self.presence = new_presence

                self.mqtt.publish("presence", "1" if self.presence else "0", True)

                if not self.presence:
                    self.presence_members.clear()
                    self.telegram.message("\U0001F4A4 Labi tyhjillään")

            delay = 0 if self.presence is None or new_presence else settings.PRESENCE["LEAVE_DELAY_SECONDS"]
            self.presence_timer = utils.Timer(set_presence, delay)

if __name__ == "__main__":
    app = Renksu()
    app.start()

    utils.run_event_loop()
