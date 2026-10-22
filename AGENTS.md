# AGENTS.md

## Project Overview
**TouchPlayer** is a lightweight, gesture-driven media player (PyQt6 + libmpv + OpenGL) built natively for **Wayland touchscreen laptops and 2-in-1 devices**, derived from **EasyPlayer**.

All architectural decisions, UI layouts, and event handling prioritize **touchscreen ergonomics, low-latency gesture response, and native Wayland integration**.

---

## Key Platform & Environment Rules

1. **Native Wayland Execution (Strict):**
   - **Never force `QT_QPA_PLATFORM=xcb`** on Wayland sessions.
   - Upstream EasyPlayer had a heuristic forcing `xcb` on GTK desktops. TouchPlayer disables that override so Qt6 runs natively under Wayland.
   - Native Wayland is required for reliable, low-latency multi-touch `QTouchEvent` delivery without XWayland translation artifacts.

2. **Qt6 Multi-Touch Event Handling:**
   - Widgets consuming touch must have `self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)`.
   - Event types are scoped as `QtCore.QEvent.Type.TouchBegin`, `TouchUpdate`, `TouchEnd`, `TouchCancel`.
   - Touch point states use `QtGui.QEventPoint.State` (e.g. `QtGui.QEventPoint.State.Released`).
   - Active touch points must be filtered by `p.state() != QtGui.QEventPoint.State.Released`.

3. **Touch-Friendly Window Design (HeaderBar & Controls):**
   - Window control buttons (Minimize `—`, Maximize/Restore `□`/`❐`, Close `✕`) are embedded directly into the top bar with large `38x38px` touch targets and generous 12px gaps.
   - Window dragging on Wayland is implemented via `windowHandle().startSystemMove()` on the toolbar and drag spacers.
   - Double-clicking or double-tapping the toolbar toggles Maximize/Restore.
   - Concentric 10px rounded corners with translucent backdrop (`WA_TranslucentBackground`).
   - Centered title with smart middle-elision (`ElidedTitleLabel`) that forwards window drag events.

4. **Single-File Playback Focus:**
   - Opening a file loads **strictly and exclusively** that file. Recursive directory scanning and playlist auto-advancing are completely bypassed.
   - When a video reaches EOF and the user unpauses (e.g. via Space or Play button), playback rewinds to `00:00:00` and replays.

---

## Touchscreen Gesture Architecture

- **`ZoomController` (`src/Player.py`):**
  - Canonical controller for both video (via `mpv.video_zoom` and `mpv.video_pan_{x,y}`) and still images (via `ImageOverlay`).
  - Zoom range: `1.0` (100%, no zoom) to `8.0` (800% max).
  - Zoom factor is logarithmic in mpv (`mpv.video_zoom = math.log2(factor)`).
  - Clamping: `_clampPan()` guarantees the visible video never pans outside the widget bounds. Clamping pan to 0 is automatic when `factor == 1.0`.
  - Methods:
    - `zoomAt(steps, mx, my)`: Wheel notch zooming.
    - `panBy(dx, dy)`: Relative panning in widget pixels.
    - `pinchZoom(ratio, mx, my, dx, dy)`: Continuous two-finger pinch-to-zoom anchored at gesture midpoint, with simultaneous translation.
    - `resetZoom()`: Resets factor to 1.0, centers pan to (0, 0), and updates both mpv and image overlay.

- **`Player` Touch Pipeline (`src/Player.py`):**
  - Inherits from `QOpenGLWidget`.
  - Overrides `event(e)` to process `QTouchEvent`.
  - **Two fingers:** Tracks distance and midpoint delta. Continuously updates zoom and pan via `zoomCtrl.pinchZoom(...)`.
  - **One finger (zoomed in):** Pans the zoomed view continuously via `zoomCtrl.panBy(...)`.
  - **One finger (not zoomed in):** Passes through to standard Qt mouse events for transport control, scrubbing, and OSD interaction.
  - **Double-tap on video surface:** Instantly resets zoom back to 100%.
  - **Single-tap (fullscreen):** Toggles OSD visibility on/off.

---

## Playback & Picture Control Systems

- **Speed Cycler:**
  - Dedicated bottom-left `btnSpeed` in `ui_BottomBar` alternates sequentially between `1x`, `1.5x`, and `2x` (`SPEED_OPTIONS = (1.0, 1.5, 2.0)`).
  - Pitch correction is maintained via mpv's default `scaletempo`.
  - Emits `speedChanged(float)` and observes `mpv.observe_property("speed")`.

- **Color Temperature (`ColorTempSlider` in `src/QtTools.py`):**
  - Range: `5000K` (warm) to `9000K` (cool), default `6500K` (neutral).
  - Managed via mpv video filter `@colortemp:colortemperature=temperature=<K>:pl=0.5`.
  - Filter is cleanly removed at default 6500K for zero processing overhead.

- **Brightness Control (`BrightnessSlider` in `src/QtTools.py`):**
  - Clamped to `[-30, 30]` (default 0) to avoid blown-out white or complete blackouts.

- **Fullscreen OSD (`OsdController` & `OsdOverlay` in `src/Osd.py`):**
  - Auto-hide timeout: **6 seconds** (`HIDE_DELAY_MS = 6000`).
  - Seamlessly borrows `ui_SeekerRow` and `ui_BottomBar` without widget duplication.
  - Monitors `MouseButtonRelease` to restart countdown from the moment of interaction release.
  - Re-checks at 1-second intervals while a touch or mouse button is actively held down.

---

## Non-Obvious Architecture & Gotchas (Crucial for AI & Contributors)

### 1. Wayland Client-Side Window Dragging (`startSystemMove`)
- **Quirk:** In native Wayland, manual coordinate window dragging via `self.move(x, y)` is impossible because the compositor controls window coordinates.
- **Solution:** Window moves MUST be delegated to the compositor via `windowHandle().startSystemMove()`. Any widget spanning the header (e.g. `DragSpacer`, `ElidedTitleLabel`, `toolbar`) must capture `LeftButton` press and trigger `startSystemMove()`.

### 2. OpenGL FBO Alpha Blending Limitation
- **Quirk:** `QOpenGLWidget` renders video via libmpv's `MpvRenderContext` directly into an OpenGL Framebuffer Object (FBO). Semi-transparent/translucent Qt widgets placed over the FBO will **not** blend cleanly with mpv frames (they render with dark or glitchy artifacts).
- **Solution:** Overlays like `OsdOverlay` must use opaque background stylesheets (e.g., solid or linear gradient) rather than translucent alpha over the video canvas.

### 3. Unified Bottom Bar Borrowing (Zero UI Duplication)
- **Quirk:** Do NOT instantiate separate fullscreen duplicates of the seeker, volume slider, speed button, or play buttons.
- **Solution:** `osdCtrl.takeWidgets(self.ui_SeekerRow, self.ui_BottomBar)` dynamically reparents existing windowed widgets into `OsdOverlay` upon entering fullscreen, and `osdCtrl.releaseWidgets()` returns them to `MainFrame._mainBox` upon returning to windowed mode. Any layout changes in `ui_BottomBar` automatically apply to both windowed and fullscreen OSD.

### 4. Synthetic Move Event Suppression (`_suppressWakeUntil`)
- **Quirk:** Showing/hiding the OSD or switching between `BlankCursor` and normal cursor causes Qt/Wayland to fire synthetic `MouseMove` events. Without suppression, hiding the OSD immediately triggers a `MouseMove`, waking it back up in an infinite loop.
- **Solution:** `OsdController` sets `self._suppressWakeUntil = time.time() + 0.35` in `show()` and `hide()`. Any wake events fired within 350ms of a state change are discarded.

### 5. MPV Thread Boundaries & Property Observers
- **Quirk:** MPV property observers (e.g., `_onMpvSpeed`, `_onMpvBrightness`, `_onMpvVolume`) run on MPV's background thread, not the Qt GUI thread.
- **Solution:** Never call UI widget methods directly from MPV observer callbacks. Always emit PyQt signals (`speedChanged`, `volumeChanged`, etc.), which automatically transition across the thread boundary via Qt's queued connection mechanism. Always guard with `if not self.closePending:` to avoid teardown crashes.

### 6. Mpv Filter Updates via Labeled Chains (`@colortemp`)
- **Quirk:** Appending filters generically to mpv's `vf` string causes stacking duplicates and leaks memory on continuous slider movement.
- **Solution:** Always label dynamic filters with `@name`: `self.mpv.command('vf', 'set', f'@colortemp:colortemperature=temperature={val}:pl=0.5')`. This replaces the filter in-place. Remove cleanly with `self.mpv.command('vf', 'remove', '@colortemp')` at neutral default.

### 7. FreeType Emoji Vertical Centering (`makeCenteredEmojiIcon`)
- **Quirk:** On Linux FreeType/FontConfig, drawing emoji glyphs (like 🌡️ or 🔊) directly as text or in standard `QIcon` results in severe vertical misalignment due to font ascender/descender metrics.
- **Solution:** Use [`makeCenteredEmojiIcon()`](file:///home/aj/dev/TouchPlayer/src/QtTools.py) in `src/QtTools.py`, which rasterizes the glyph into a `QPixmap` with explicit vertical padding (`top=8px, bottom=9px`) and uniform contrast tinting.

### 8. Translucent Backing for Rounded Window Corners
- **Quirk:** Styling `QMainWindow { border-radius: 10px; }` on Wayland leaves black rectangular corners because the underlying Wayland subsurface is opaque.
- **Solution:** `WA_TranslucentBackground` is set on both `MainFrame` and `CentralWidget`. The top toolbar (`10px` top corners) and `ui_BottomBar` (`10px` bottom corners) draw the visual window boundary. Fullscreen mode switches these radii back to `0px`.

### 9. Packaging & Release Policy (Strictly No Python Wheels / PyPI)
- **Rule:** **NEVER build, distribute, or attach Python wheels (`.whl`) to GitHub releases**, and do not recommend `pip install` for end users.
- **Why:** TouchPlayer is a standalone desktop GUI application requiring system shared C-libraries (`libmpv.so.2`, `ffmpeg`) and system desktop integration (XDG `.desktop` launcher, application menu icons, MIME type associations). Python wheels cannot resolve system C-libraries, are blocked by PEP 668 ("externally-managed-environment") on modern Linux distros, and fail to install desktop icons.
- **Allowed Release Artifacts:**
  1. **`.deb` package:** Automatic dependency resolution (`libmpv2`, `ffmpeg`, `python3-pyqt6`) and desktop launcher integration for Debian/Ubuntu/Mint.
  2. **Universal tarball (`touchplayer-*.tar.gz`):** Self-contained bundle with [`install.sh`](file:///home/aj/dev/TouchPlayer/install.sh) for Arch, Fedora, openSUSE, etc.
  3. **`SHA256SUMS`:** Checksum verification file.

---

## Testing & Development Guidelines

- **Skip Redundant Pre-Checks & Minimize Tool Chaining:**
  - Do **not** run speculative discovery chains (e.g. repeated `git status`, `git diff`, or pre-verification checks) before making straightforward edits.
  - For simple UI adjustments, styling tweaks, asset updates, or documentation edits, skip running tests unless specifically requested by the user.
  - Only run targeted tests when modifying core logic (such as gesture math, thread boundaries, or state machines), and consolidate tool calls into single, concise actions to avoid latency.

- **Fast Targeted Testing:**
  - Do **not** run the full test suite after routine edits; only run targeted tests for touched code to keep test execution under 0.1s:
    ```bash
    PYTHONPATH=tests:src python3 -m unittest tests/test_pinch.py tests/test_volume.py tests/test_brightness.py tests/test_fullscreen_topbar.py tests/test_title.py tests/test_videoslider.py
    ```
- **Execution Environment:**
  - If running commands in isolated sandboxes where container socket connections encounter issues, execute directly on the host (bypass sandbox).
- **Manual Launch & Verification:**
  ```bash
  python3 src/EasyPlayer.py [path_to_video_or_image]
  ```
  1. **Pinch-to-zoom:** Two fingers spreading apart zooms into midpoint; pinching together zooms out, clamping cleanly at 100%.
  2. **Pan:** Dragging two fingers pans; dragging one finger pans when zoomed in.
  3. **Reset:** Double-tap video surface resets zoom to 100%.
  4. **Fullscreen Tap:** Single tap shows/hides OSD (hides after 6s of inactivity).
  5. **HeaderBar:** Drag top bar to move window; double-click/tap top bar to maximize/restore.
