#!/bin/sh
set -e

Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &

exec python main.py --disable-menu