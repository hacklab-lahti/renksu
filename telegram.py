import aiohttp
import urllib
import logging
import settings

log = logging.getLogger("telegram")

class Telegram:
    def __init__(self):
        pass

    def message(self, text):
        try:
            text = urllib.parse.quote(text)
            url = "https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}&disable_notification={}".format(settings.TELEGRAM_BOT_TOKEN,settings.TELEGRAM_CHAT_ID,text,"true")

            self.http_session = aiohttp.ClientSession()
            async with self.http_session.get(url, timeout=10) as resp:
               log.debug("Telegram message sent, response from server: {}".format(await resp.text()))

        except:
            log.error("Failed to send Telegram message", exc_info=e)
