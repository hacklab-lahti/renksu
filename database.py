import aiohttp
import asyncio
import csv
import datetime
import json
import logging
import os
import time

import utils

__all__ = [
    "STATUS_ACTIVE", "STATUS_INACTIVE", "STATUS_UNKNOWN",
    "Database"
]

log = logging.getLogger("database")

csv.register_dialect(
    "Renksu",
    skipinitialspace=True,
    lineterminator="\n")

ONE_DAY = 60 * 60 * 24

class MemberInfo:
    def __init__(self, id, name, phone_number, active_until, public_name):
        self.id = id
        self.name = name
        self.phone_number = phone_number
        self.active_until = active_until
        self.public_name = public_name

    def get_days_until_expiration(self):
        return int(((self.active_until - time.time()) // ONE_DAY) + 1)

    @property
    def display_name(self):
        return "{} (#{})".format(self.name, self.id)

    def get_public_name(self):
        return (self.public_name if self.public_name else "Joku jäsen")

    def __eq__(self, other):
        return (self.id == other.id and self.name == other.name
            and self.phone_number == other.phone_number
            and self.active_until == other.active_until
            and self.public_name == other.public_name)

class Database:
    def __init__(self, address, update_interval):
        self.address = address
        self.update_interval = update_interval

        self.file_name = "members.json"
        self.members = []

    def start(self):
        self.http_session = aiohttp.ClientSession()

        self._load_from_file()

        utils.start_timer(self._update, self.update_interval)

    async def _update(self, timeout=10):
        if "://" in self.address:
            async with self.http_session.get(self.address, timeout=timeout) as resp:
                self._update_database(json.loads(await resp.text()))
        else:
            with open(self.address, "r", encoding="utf-8") as f:
                self._update_database(csv.DictReader(f, dialect="Renksu"))

    def _update_database(self, data):
        if not data:
            return

        try:
            new_members = []

            for mdata in data:
                new_members.append(
                    MemberInfo(
                        int(mdata["id"]),
                        str(mdata["name"]),
                        str(mdata["phone_number"]),
                        int(time.mktime(time.strptime(mdata["active_until"], "%Y-%m-%d"))),
                        mdata.get("public_name", None) or None))

            if new_members != self.members:
                self.members = new_members

                log.debug("Database updated. Saving to file.")
                self._save_to_file()
        except Exception as e:
            log.error("Failed to deserialize database data. Database was not updated.", exc_info=e)

    def _load_from_file(self):
        if not os.path.exists(self.file_name):
            return

        try:
            with open(self.file_name, "r", encoding="utf-8") as f:
                json_str = f.read()

            self._update_database(json.loads(json_str))
        except Exception as e:
            log.error("Failed to load database", exc_info=e)

    def _save_to_file(self):
        try:
            temp_file_name = self.file_name + ".tmp"

            with open(temp_file_name, "w", encoding="utf-8") as f:
                f.write(json.dumps(list(map(lambda m: {
                    "id": m.id,
                    "name": m.name,
                    "phone_number": m.phone_number,
                    "active_until": time.strftime("%Y-%m-%d", time.gmtime(m.active_until)),
                    "public_name": m.public_name,
                }, self.members)), indent=True))

            os.rename(temp_file_name, self.file_name)
        except Exception as e:
            log.error("Failed to save database", exc_info=e)

    async def get_member_info(self, number):
        member = self._find_member(number)
        if member is not None:
            return member

        # Maybe the member has just been added, try to update with low timeout
        await self._update(timeout=2)

        return self._find_member(number)

    def _find_member(self, number):
        return next((m for m in self.members if m.phone_number == number), None)

if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)-15s %(name)s %(message)s", level=logging.DEBUG)

    print("Testing Database")

    db = Database(
        address="/home/hacklab/members.csv",
        update_interval=10)
    db.start()

    asyncio.get_event_loop().run_forever()
