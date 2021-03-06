import os.path
import logging, logging.config
logging.config.fileConfig(os.path.dirname(__file__) + "/../logging.ini")

import asyncio
import configparser
import sys
import time

import database
import door
import modem
import mqtt
import reader
import speaker
import telegram
import utils

log = logging.getLogger("renksu")
audit_log = logging.getLogger("audit")

class Renksu:
    def __init__(self, mock=None):
        def mocked(name):
            return mock and mock.is_mocked(name)

        self.settings = configparser.ConfigParser(allow_no_value=True)
        self.settings.read(utils.basedir() + "../settings.ini")

        self.db = database.Database(settings=self.settings["database"])

        self.speaker = speaker.Speaker(["doorbell", "bleep"])

        self.telegram = (
            telegram.MockTelegram(mock)
            if mocked("telegram")
            else telegram.Telegram(self.settings["telegram"]))

        self.modem = (
            modem.MockModem(mock, self.settings["modem"])
            if mocked("modem")
            else modem.Modem(self.settings["modem"]))

        self.modem.on_ring_start = self.ring_start
        self.modem.on_ring_end = self.ring_end

        self.door = (
            door.MockDoor(mock, self.settings["door"])
            if mocked("door")
            else door.Door(self.settings["door"]))
        self.door.on_open_change = self.door_open_change
        self.door.on_unlocked_change = self.door_unlocked_change

        self.reader = (
            reader.MockReader(mock)
            if mocked("reader")
            else reader.Reader(self.settings["reader"]))
        self.reader.on_tag_read = self.tag_read
        self.reader.on_button_change = self.doorbell_button_change

        self.last_unlocked_by = None
        self.last_opened_at = None

        self.say_after_open_text = None
        self.say_after_open_time = 0

        self.mqtt = mqtt.MqttClient(self.settings["mqtt"])
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

    def doorbell_button_change(self, pushed):
        if pushed and not self.door.is_unlocked:
            self.reader.show_doorbell()
            self.speaker.play("doorbell")
            self.mqtt.publish("doorbell", None)

    def say_after_open(self, text):
        self.say_after_open_text = text
        self.say_after_open_time = time.time()

    async def tag_read(self, uid):
        #print("Tag read: aaa ", uid)

        if not uid:
            return

        audit_log.info("RFID tag read")

        member = await self.db.get_member_by_tag_id(uid)

        if member is None:
            audit_log.info("-> Tag not in database")

            self.mqtt.publish("reader/unknown_tag", None)

            if not self.door.is_unlocked:
                self.reader.show_unknown("Unknown tag", sound=True)

            return

        await self.maybe_unlock_for_member(member, "tag")

    async def ring_start(self, number):
        audit_log.info("Incoming call from %s", number)

        if number is None:
            audit_log.info("-> Hidden number")

            self.mqtt.publish("ring/hidden_number", None)
            self.reader.show_unknown("Hidden number")

            self.speaker.play("doorbell")
            self.telegram.message("\U0001F514 Joku soitti ovikelloa piilotetusta numerosta.")
            return

        member = await self.db.get_member_by_number(number)

        if member is None:
            audit_log.info("-> Number not in database")

            self.mqtt.publish("ring/number_not_in_database", None)
            self.reader.show_unknown("Unknown number")

            self.speaker.play("doorbell")
            self.telegram.message("\U0001F514 Joku soitti ovikelloa numerosta, joka ei ole jäsenrekisterissä.")
            return

        await self.maybe_unlock_for_member(member, "phone")

        await asyncio.sleep(2)

        self.modem.hangup()

    async def maybe_unlock_for_member(self, member, method):
        now = time.time()

        days_left = member.get_days_until_expiration()

        audit_log.info("Membership days left: {}".format(days_left))

        presence_timeout = self.settings.getint("presence", "timeout_seconds", fallback=0)
        grace_period = self.settings.getint("membership", "grace_period_days", fallback=0)
        remaining_message_days = self.settings.getint("membership", "remaining_message_days", fallback=0)

        if days_left < 0:
            if grace_period and -days_left < grace_period:
                self.say_after_open("Membership expired. Days of grace period remaining: {}".format(
                    grace_period + days_left))
            else:
                audit_log.info("-> Not an active member!")
                #asyncio.ensure_future(self.ring_doorbell())

                self.mqtt.publish("ring/member_not_active", member.get_public_name())

                #self.telegram.message("\U000026D4 {} soitti ovikelloa, koska tilankäyttöoikeus ei ole voimassa."
                #    .format(member.get_public_name()))

                self.reader.show_membership_not_active(member)

                return
        else:
            if remaining_message_days and days_left <= remaining_message_days:
                self.say_after_open("Days remaining: {}".format(days_left))

        self.mqtt.publish("ring/unlocked", member.get_public_name())

        audit_log.info("Opening door for %s", member.display_name)

        last_presence = self.presence_members.get(member.id, 0)
        if now - last_presence >= presence_timeout:
            self.presence_members[member.id] = now
            self.telegram.message("\U0001F6AA {} avasi oven.".format(member.get_public_name()))

        if not self.door.unlock():
            return

        self.last_unlocked_by = member

        self.speaker.play("bleep")

        self.reader.show_unlocked(member, self.door.unlocked_until, method)

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

        self.mqtt.publish("door_open", "1" if is_open else "0", True)

        self.update_presence()

    def door_unlocked_change(self, is_unlocked):
        if is_unlocked:
            audit_log.info("Door unlocked.")
        else:
            audit_log.info("Door locked.")

            self.reader.show_locked()

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

            delay = (
                0
                if self.presence is None or new_presence
                else self.settings.getint("presence", "leave_delay_seconds", fallback=0))

            self.presence_timer = utils.Timer(set_presence, delay)

if __name__ == "__main__":
    app = Renksu()
    app.start()

    utils.run_event_loop()
