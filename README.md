# TouchPlayer

A lightweight, gesture-driven Wayland media player for Linux touchscreen laptops and 2-in-1 devices.

*TouchPlayer is a touch-first derivative forked from [EasyPlayer](https://github.com/kanehekili/EasyPlayer) by Kanehekili.*

---

## Why TouchPlayer?

Most desktop Linux media players are designed strictly for traditional mouse and keyboard setups. On modern touchscreen laptops running Wayland, pinch-to-zoom is typically unsupported, window controls are too small to tap reliably, and UI fails to accommodate touch interactions.

**TouchPlayer** reimagines the player experience with **native Wayland multi-touch ergonomics**, fluid gesture controls, client-side window management, and picture adjustments - all powered by the high-performance `libmpv` and Qt6 OpenGL engine.

---

## Key Features

### 👆 Multi-Touch Gestures (Native Wayland)
- **Continuous Pinch-to-Zoom:** Smooth two-finger pinch-to-zoom anchored directly at the midpoint between your fingers (from 100% up to 800% zoom with logarithmic scaling).
- **Boundary Clamping:** Visible video area is clamped to prevent panning into empty space when zoomed.
- **Two-Finger & One-Finger Pan:** Effortlessly slide two fingers across the screen to pan the video, or drag with one finger when zoomed in.
- **Double-Tap Reset:** Quickly double-tap the video surface with a finger or stylus to instantly reset zoom back to 100%.
- **Tap OSD Toggle:** Tap the video surface in fullscreen mode to smoothly toggle the on-screen display.

### 🪟 Touch-Friendly Window & Ergonomics
- **Wayland Window Dragging:** Custom top HeaderBar supports direct native Wayland window dragging (`startSystemMove()`) and double-tap to maximize/restore.
- **Large Touch Controls:** Window buttons (Minimize `—`, Maximize/Restore `□`/`❐`, Close `✕`) feature large `38x38px` touch targets with generous 12px gaps.
- **Frameless Translucent Shell:** Elegant 10px rounded corners with translucent backdrop matching modern desktop styling.
- **Middle-Elided Centered Title:** File and track names are cleanly centered in the header bar with smart middle-elision (`...`) and click-drag forwarding.

### 🎛️ Playback & Picture Controls
- **Single-File Playback:** Clean, immediate loading of chosen files without unwanted recursive folder scanning or accidental playlist auto-advancing.
- **Auto-Replay on EOF:** Pressing Play or Space at the end of a video automatically restarts playback from `00:00`.
- **Playback Speed Cycler:** Dedicated bottom-left touch button that alternates between `1x`, `1.5x`, and `2x` speeds with pitch preservation.
- **Color Temperature Slider:** Dedicated slider to adjust warmth and coolness between `5000K` and `9000K` via mpv's `@colortemp` video filter with lightness preservation.
- **Clamped Brightness Slider:** Touch slider clamped to `[-30, 30]` to prevent over-washing or total blackouts.
- **Smart Fullscreen OSD:** Dynamically borrows bottom transport and seeker bars into fullscreen with a comfortable **6-second auto-hide timeout** and drag-hold detection.

---

## Installation

### Recommended Option: **[GitHub Releases](https://github.com/notalanjoseph/TouchPlayer/releases)**

#### For Ubuntu / Debian / Linux Mint:
Download `touchplayer_*_all.deb` from the latest release. Install it using:

```bash
sudo apt install ./touchplayer_*_all.deb
```

#### For Arch/ Fedora/ openSUSE or any Linux:
Download `touchplayer-*.tar.gz` from the latest release, extract it. Run the user installer:

```bash
tar -xzf touchplayer-*.tar.gz
cd touchplayer-*
./install.sh --user
```

To install system-wide instead:
```bash
sudo ./install.sh
```

### Dev Option: Run from Source
You can clone the repository and run TouchPlayer directly without installation:

```bash
git clone https://github.com/notalanjoseph/TouchPlayer.git
cd TouchPlayer
python3 src/EasyPlayer.py /path/to/media.mp4
```

---

## Running TouchPlayer

Once installed, you can launch TouchPlayer from your application menu, file manager ("Open With..."), or terminal:

```bash
touchplayer /path/to/media.mp4
```

---

## Updating

To update TouchPlayer to a newer release:

- **If installed via `.deb` (Ubuntu / Debian / Linux Mint):**
  Download the new `.deb` file from the latest [GitHub Releases](https://github.com/notalanjoseph/TouchPlayer/releases) and install it:
  ```bash
  sudo apt install ./touchplayer_*_all.deb
  ```
  `apt` automatically upgrades the existing installation in place.

- **If installed via Universal Tarball (`.tar.gz`):**
  Download and extract the new release tarball, then run the installer:
  ```bash
  # If previously installed for current user:
  ./install.sh --user

  # If previously installed system-wide:
  sudo ./install.sh
  ```
  The installer cleanly overwrites the previous version.

---

## Uninstallation

To cleanly remove TouchPlayer from your system:

- **If installed via `.deb`:**
  ```bash
  sudo apt remove touchplayer
  ```
- **If installed via user script (`--user`):**
  ```bash
  ./uninstall.sh --user
  ```
- **If installed via system script (`sudo ./install.sh`):**
  ```bash
  sudo ./uninstall.sh
  ```

---

## Releasing

Use `bump-my-version` to bump the version, commit, and create the release tag:

```bash
bump-my-version bump patch   # or minor / major — bumps pyproject.toml, commits, and tags locally
git push
git push --follow-tags
```

`.github/workflows/release.yml` will automatically run verification tests, build the `.deb` package and universal tarball, generate SHA-256 checksums, and publish the GitHub Release with release notes.

---

## License & Credits

- **License:** GNU General Public License v2.0 or later ([GPL-2.0-or-later](LICENSE)).
- **Upstream Credits:** TouchPlayer is derived from [EasyPlayer](https://github.com/kanehekili/EasyPlayer) created by **Kanehekili**, incorporating `libmpv` and Qt6.
- <a href="https://www.flaticon.com/free-icons/rss-button" title="rss button icons">Rss button icons created by juicy_fish - Flaticon</a>
- <a href="https://www.flaticon.com/free-icons/vinyl-record" title="vinyl record icons">Vinyl record icons created by juicy_fish - Flaticon</a>
