#!/bin/bash

if [ "$1" == "--user" ] || [ "$EUID" -ne 0 ]; then
    PREFIX="${HOME}/.local"
    INSTALL_DIR="${PREFIX}/share/touchplayer"
    BIN_DIR="${PREFIX}/bin"
    APP_DIR="${PREFIX}/share/applications"
    echo "Uninstalling TouchPlayer from user directory ($USER)..."
else
    PREFIX="/usr"
    INSTALL_DIR="/opt/touchplayer"
    BIN_DIR="/usr/local/bin"
    APP_DIR="/usr/share/applications"
    echo "Uninstalling TouchPlayer system-wide..."
fi

rm -rf "$INSTALL_DIR"
rm -f "$BIN_DIR/touchplayer"
rm -f "$APP_DIR/TouchPlayer.desktop"

echo "✓ TouchPlayer uninstalled successfully."
