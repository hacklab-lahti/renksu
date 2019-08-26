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

        self.topic_prefix = self.settings.get("topic_prefix")
        self.light_status_topic = self.settings.get("light_status_topic", fallback=None)
        self.light_status_on = self.settings.get("light_status_on", fallback=None)

    def start(self):
        self.client = mqtt.Client()
        self.client.will_set(self.topic_prefix + "online", "0", 2, True)
        self.client.connect_async(self.settings.get("host"), self.settings.getint("port"), 60)
        if self.settings.get("username", fallback=None):
            self.client.username_pw_set(
                self.settings.get("username"),
                self.settings.get("password"))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.client.loop_start()

    def publish(self, topic, payload, retain=False):
        log.debug("send: {} {}{}".format(topic, payload, " (retain)" if retain else ""))

        try:
            self.client.publish(self.topic_prefix + topic, payload, 2, retain)
        except Exception as e:
            log.error("Failed to publish to MQTT: {} {}".format(topic, payload), exc_info=e)

    @threadsafe
    async def _on_connect(self, client, userdata, flags, rc):
        log.info("Connected to server")

        if self.light_status_topic:
            self.client.subscribe(self.light_status_topic)

        self.publish("online", "1", True)

    @threadsafe
    async def _on_message(self, client, userdata, msg):
        if isinstance(msg.payload, bytes):
            msg.payload = msg.payload.decode("utf-8")

        log.debug("recv: {} {}".format(msg.topic, msg.payload))

        if self.light_status_topic and msg.topic == self.light_status_topic:
            new_light_on = (msg.payload == self.light_status_on)

            if new_light_on != self.light_on:
                self.light_on = new_light_on

                log.debug("Light status: {}".format(self.light_on))

                utils.raise_event(self.on_light_on_change, new_light_on)
