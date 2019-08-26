import asyncio
import aiohttp
import logging
import urllib
import time

log = logging.getLogger("telegram")

class Telegram:
    def __init__(self, settings):
        self.settings = settings
        self.started = time.time()

    def message(self, text):
        asyncio.ensure_future(self._message(text))

    async def _message(self, text):
        if time.time() - self.started < 10:
            log.info("Ignoring Telegram message (just started): {}".format(text))
            return

        try:
            text = urllib.parse.quote(text)
            url = ("https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}&disable_notification={}"
                .format(self.settingsget("bot_token"), self.settings.get("chat_id"), text, "true"))

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    log.debug("Telegram message sent, response from server: {}".format(await resp.text()))
        except:
            log.error("Failed to send Telegram message", exc_info=e)

class MockTelegram:
    def __init__(self, mock):
        self.mock = mock

    def message(self, text):
        self.mock.log("Sending to Telegram: {}".format(text))
