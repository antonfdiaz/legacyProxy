#!/bin/bash
cd $(dirname $0)
nuitka --standalone --macos-create-app-bundle --macos-app-icon=./images/lpbigsur.png --include-data-dir=./js=js --include-data-dir=./html=html --include-data-dir=./css=css --include-data-dir=./images=images main.py