Renksu physical access control system
=====================================

This is currently set up to work with a single door to a single hackerspace, therefore YMMV.

Setup
-----

(This assumes Raspbian)

Configure serial at /dev/ttyAMA0 with raspi-config, choose Interfacing options -> Serial, disable
login shell over serial, enable serial hardware.

Alternatively remove the console=serial0 entry from /boot/cmdline.txt.

Give the user permissions to the required devices and install required packages (as root). The list
of packages assumes a recent version of Raspbian, adjust accordingly.

    # usermod -G audio,dialout,gpio -a user
    # apt install sudo apt install python3-venv python3-dev espeak libasound2-dev libjpeg8-dev libopenjp2-7 libtiff5

Create virtual environment and install pip packages

    $ python3 -m venv venv
    $ venv/bin/pip install -r requirements.txt

Create settings.ini based on the example file, edit to taste and test:

    $ cp settings.ini.example settings.ini
    $ your_favorite_editor settings.ini
    $ ./run.sh

Edit renksu.service.example to set correct path and user and install (as root):

    # cp renksu.service.example /etc/systemd/system/renksu.service
    # systemctl enable renksu
