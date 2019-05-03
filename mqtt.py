import asyncio
import logging
import paho.mqtt.client as mqtt

import utils

log = logging.getLogger("mqtt")

main_event_loop = asyncio.get_event_loop()

def threadsafe(func):
    def wrapper(*args):
        try:
            asyncio.run_coroutine_threadsafe(func(*args), main_event_loop)
        except Exception as e:
            print("Thread exception", repr(e))

    return wrapper

class MqttClient:
    def __init__(self, settings):
        self.settings = settings
        self.light_on = None
        self.on_light_on_change = None

    def start(self):
        self.client = mqtt.Client()
        self.client.connect_async(self.settings["HOST"], self.settings["PORT"], 60)
        if self.settings["USERNAME"]:
            self.client.username_pw_set(self.settings["USERNAME"], self.settings["PASSWORD"])
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.client.loop_start()

    def publish(self, topic, payload, retain=False):
        try:
            self.client.publish(self.settings["TOPIC_PREFIX"] + topic, payload, 2, retain)
        except Exception as e:
            log.error("Failed to publish to MQTT: {} {}".format(topic, payload), exc_info=e)

    @threadsafe
    async def _on_connect(self, client, userdata, flags, rc):
        log.info("Connected to server")

        if self.settings["LIGHT_STATUS_TOPIC"]:
            self.client.subscribe(self.settings["LIGHT_STATUS_TOPIC"][0])

    @threadsafe
    async def _on_message(self, client, userdata, msg):
        if isinstance(msg.payload, bytes):
            msg.payload = msg.payload.decode("utf-8")

        log.debug("recv: {} {}".format(msg.topic, msg.payload))

        if self.settings["LIGHT_STATUS_TOPIC"] and msg.topic == self.settings["LIGHT_STATUS_TOPIC"][0]:
            new_light_on = (msg.payload == self.settings["LIGHT_STATUS_TOPIC"][1])

            if new_light_on != self.light_on:
                self.light_on = new_light_on

                utils.raise_event(self.on_light_on_change, new_light_on)
