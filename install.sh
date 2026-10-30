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

# --- Runtime dependencies --------------------------------------------------

fail() {
    echo "✗ $*" >&2
    exit 1
}

# Distro packages such as python3-pyqt6 install for the system Python.
# A custom python3 earlier on PATH would miss them, so prefer /usr/bin/python3 for checks and launcher.
find_python() {
    if [ -x /usr/bin/python3 ]; then
        PYTHON=/usr/bin/python3
    else
        PYTHON="$(command -v python3 || true)"
    fi
}

missing_deps() {
    MISSING=()
    find_python
    if [ -z "$PYTHON" ]; then
        MISSING+=(python3 pyqt6 libmpv)
    else
        "$PYTHON" -c "import PyQt6.QtOpenGLWidgets" >/dev/null 2>&1 || MISSING+=(pyqt6)
        "$PYTHON" -c "import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library('mpv') else 1)" \
            >/dev/null 2>&1 || MISSING+=(libmpv)
    fi
    command -v ffprobe >/dev/null 2>&1 || MISSING+=(ffmpeg)
}

# Maps each missing dependency to this distro's package name.
# dnf and zypper resolve file paths and sonames, which survive package renames.
package_for() {
    case "$PM:$1" in
        apt:python3)    echo python3 ;;
        apt:pyqt6)      echo python3-pyqt6 ;;
        apt:libmpv)     if apt-cache show libmpv2 >/dev/null 2>&1; then echo libmpv2; else echo libmpv1; fi ;;
        apt:ffmpeg)     echo ffmpeg ;;
        dnf:python3)    echo python3 ;;
        dnf:pyqt6)      echo python3-pyqt6 ;;
        dnf:libmpv)     echo mpv-libs ;;
        dnf:ffmpeg)     echo /usr/bin/ffprobe ;;
        pacman:python3) echo python ;;
        pacman:pyqt6)   echo python-pyqt6 ;;
        pacman:libmpv)  echo mpv ;;
        pacman:ffmpeg)  echo ffmpeg ;;
        zypper:python3) echo python3 ;;
        zypper:pyqt6)   echo python3-PyQt6 ;;
        zypper:libmpv)  echo libmpv2 ;;
        zypper:ffmpeg)  echo /usr/bin/ffprobe ;;
    esac
}

install_deps() {
    PM=""
    for candidate in apt-get dnf pacman zypper; do
        if command -v "$candidate" >/dev/null 2>&1; then PM="${candidate%-get}"; break; fi
    done
    [ -n "$PM" ] || fail "Missing: ${MISSING[*]}. No supported package manager (apt, dnf, pacman, zypper) found; install them with your distro's tools, then run this script again."

    PKGS=()
    for dep in "${MISSING[@]}"; do PKGS+=("$(package_for "$dep")"); done
    case "$PM" in
        apt)    CMD=(apt-get install "${PKGS[@]}") ;;
        dnf)    CMD=(dnf install "${PKGS[@]}") ;;
        pacman) CMD=(pacman -S --needed "${PKGS[@]}") ;;
        zypper) CMD=(zypper install "${PKGS[@]}") ;;
    esac

    if [ "$EUID" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || fail "Missing: ${MISSING[*]}. Installing them needs root and sudo is not available. Ask an administrator to run: ${CMD[*]}"
        CMD=(sudo "${CMD[@]}")
        echo "Installing missing dependencies (${MISSING[*]}); sudo may ask for your password."
    else
        echo "Installing missing dependencies (${MISSING[*]})..."
    fi
    echo "+ ${CMD[*]}"
    "${CMD[@]}" || fail "Could not install: ${MISSING[*]}. Run this yourself, then run this script again: ${CMD[*]}"
}

missing_deps
if [ ${#MISSING[@]} -gt 0 ]; then
    install_deps
    missing_deps
    [ ${#MISSING[@]} -eq 0 ] || fail "Still missing after installing packages: ${MISSING[*]}. Package names may differ on this distro version; install them manually, then run this script again."
fi
echo "✓ Dependencies found for $PYTHON: PyQt6, libmpv, ffprobe"

# --- Install ----------------------------------------------------------------
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
exec "$PYTHON" "$INSTALL_DIR/EasyPlayer.py" "\$@"
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
