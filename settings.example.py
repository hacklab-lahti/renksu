# USB ID of 3G modem in modem mode
MODEM_USB_ID = "12d1:151d"

# Which USB configuration and interface correspond to the TTY on the modem
MODEM_TTY_CONFIG_INTERFACE = "1.3"

# Assume this country prefix for phone numbers that don't have one
MODEM_DEFAULT_COUNTRY_PREFIX = "+358"

# USB ID of 3G mode in non-modem mode
MODEM_MODE_SWITCH_USB_ID = "12d1:151a"

# Full command line to usb_modeswitch to run when modem is in non-modem mode
MODEM_MODE_SWITCH_CURSE = "sudo /usr/sbin/usb_modeswitch -v 12d1 -p 151a -i 2 --message-content 55534243123456780000000000000011062000000101000100000000000000"


# Settings for door lock/sensor
DOOR = {
    # Serial device for the door unlock relay
    "LOCK_SERIAL_DEVICE": "/dev/ttyAMA0",

    # GPIO pin address
    "SWITCH_PIN": 12,

    # How long to keep door open when called
    "PHONE_OPEN_TIME_SECONDS": 10,

    # If the door is opened for this long, the lock is locked when it closes
    "RELOCK_DEBOUNCE_TIMEOUT_SECONDS": 3,
}


# File path or URL to member database
DATABASE_ADDRESS = "/home/hacklab/members.csv"

# How often to poll the database
DATABASE_UPDATE_INTERVAL_SECONDS = 10


# Audible message of membership about to expire if only this many days left (0 = disabled)
MEMBERSHIP_REMAINING_MESSAGE_DAYS = 7

# Let people in if their membership expired less than this many days ago (0 = disabled)
MEMBERSHIP_GRACE_PERIOD_DAYS = 7


# Telegram client settings
TELEGRAM = {
    # Bot token
    "BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",

    # Chat ID ("-1234567890") or supergroup username ("@groupname")
    "CHAT_ID": "-1234567890",
}


# MQTT server settings
MQTT = {
    # Server address
    "HOST": "mqtt-server",

    # Server port
    "PORT": 5001,

    # Username (None if authentication is not needed)
    "USERNAME": "renksu",

    # Password
    "PASSWORD": "hunter2",

    # Prefix for outgoing messages
    "TOPIC_PREFIX": "renksu/",

    # Topic and "on" value for light status input topic
    "LIGHT_STATUS_TOPIC": ("something_else/light_status", "True"),
}


# Settings for presence tracking
PRESENCE = {
    # Delay before considering space empty after lights are off and door closed
    "LEAVE_DELAY_SECONDS": 60,

    # Presence timeout for re-sending the "Door opened by" messages
    "PRESENCE_TIMEOUT_SECONDS": 8 * 60 * 60,
}


# Settings for RFID reader/doorbell
READER = {
    # Serial port (preferably use /dev/serial/by-id/)
    "PORT": "/dev/serial/by-id/whatever"
}