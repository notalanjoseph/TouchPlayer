#!/bin/bash
set -e

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [ -d "$REPO_DIR/src" ]; then
    SRC_DIR="$REPO_DIR/src"
elif [ -f "$REPO_DIR/EasyPlayer.py" ]; then
    SRC_DIR="$REPO_DIR"
else
    echo "Error: Cannot locate TouchPlayer source directory."
    exit 1
fi

if [ "$1" == "--user" ] || [ "$EUID" -ne 0 ]; then
    PREFIX="${HOME}/.local"
    INSTALL_DIR="${PREFIX}/share/touchplayer"
    BIN_DIR="${PREFIX}/bin"
    APP_DIR="${PREFIX}/share/applications"
    echo "Installing TouchPlayer locally for user ($USER)..."
else
    PREFIX="/usr"
    INSTALL_DIR="/opt/touchplayer"
    BIN_DIR="/usr/local/bin"
    APP_DIR="/usr/share/applications"
    echo "Installing TouchPlayer system-wide..."
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DIR"

# Copy python sources, icons, and libmpv binding
cp -r "$SRC_DIR"/*.py "$INSTALL_DIR/"
cp -r "$SRC_DIR"/icons "$INSTALL_DIR/"
cp -r "$SRC_DIR"/lib "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/EasyPlayer.py"

# Launcher wrapper script
cat << EOF > "$BIN_DIR/touchplayer"
#!/bin/bash
exec python3 "$INSTALL_DIR/EasyPlayer.py" "\$@"
EOF
chmod +x "$BIN_DIR/touchplayer"

# Desktop Entry
cat << EOF > "$APP_DIR/TouchPlayer.desktop"
[Desktop Entry]
Encoding=UTF-8
Version=1.0
Type=Application
Exec=$BIN_DIR/touchplayer %f
Name=TouchPlayer
GenericName=TouchPlayer
Comment=Gesture-driven Wayland media player
Icon=$INSTALL_DIR/icons/icon.png
NoDisplay=false
Terminal=false
StartupWMClass=TouchPlayer
Categories=AudioVideo;Player;Video;Qt;
MimeType=image/png;image/jpeg;image/bmp;image/gif;image/webp;image/tiff;video/dv;video/mpeg;video/x-mpeg;video/msvideo;video/quicktime;video/x-anim;video/x-avi;video/x-ms-asf;video/x-ms-wmv;video/x-msvideo;video/x-nsv;video/x-flc;video/x-fli;video/x-flv;video/vnd.rn-realvideo;video/mp4;video/mp4v-es;video/mp2t;application/ogg;application/x-ogg;video/x-ogm+ogg;audio/x-vorbis+ogg;application/x-matroska;audio/x-matroska;video/x-matroska;video/webm;audio/webm;audio/x-mp3;audio/x-mpeg;audio/mpeg;audio/x-wav;audio/x-mpegurl;audio/x-scpls;audio/x-m4a;audio/x-ms-asf;audio/x-ms-asx;audio/x-ms-wax;application/vnd.rn-realmedia;audio/x-real-audio;audio/x-pn-realaudio;application/x-flac;audio/x-flac;audio/mp4;audio/amr;audio/amr-wb;x-content/video-dvd;
EOF

echo "✓ TouchPlayer installed successfully to $INSTALL_DIR"
echo "✓ Executable linked at $BIN_DIR/touchplayer"
echo "✓ Desktop launcher added to $APP_DIR/TouchPlayer.desktop"
if [ "$1" == "--user" ] || [ "$EUID" -ne 0 ]; then
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo "Note: Make sure ~/.local/bin is in your PATH."
    fi
fi
