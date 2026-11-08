# To do

## Alt+Tab does not list TouchPlayer with other apps

**Symptoms (seen with the snap, 1.3.5):**
- From a non-TouchPlayer app, Alt+Tab does not show TouchPlayer at all.
- From a TouchPlayer window, Alt+Tab only switches between TouchPlayer windows.

**Already ruled out in the code:**
- No window flag hides the main window from the switcher (no `Qt.Tool`, `Qt.Dialog` or `BypassWindowManager`).
- The Wayland app ID matches the launcher: `touchplayer_touchplayer` in the snap (`snapd` renames the `.desktop` file), `TouchPlayer` otherwise (`app.setDesktopFileName` in `src/EasyPlayer.py`).
- Both `.desktop` files set `StartupWMClass=TouchPlayer`.

**To find out on the affected machine:**
1. Snap or `.deb`? Check whether the `.deb` or a run from source (`python3 src/EasyPlayer.py`) behaves the same. Only the snap means a packaging cause; both means the app or GNOME.
2. Fullscreen, or another workspace or screen? Check a normal window too, and whether TouchPlayer sits on a different workspace or monitor from the other apps.
3. Switcher settings. If any is `true` while TouchPlayer is on another workspace or monitor, that alone explains the symptoms:
   ```bash
   gsettings get org.gnome.shell.app-switcher current-workspace-only
   gsettings get org.gnome.shell.window-switcher current-workspace-only
   gsettings get org.gnome.shell.extensions.dash-to-dock isolate-workspaces
   gsettings get org.gnome.shell.extensions.dash-to-dock isolate-monitors
   ```
4. What GNOME thinks the window is: Alt+F2, `lg`, Enter, then the **Windows** tab with TouchPlayer open. Note which app it lists for the TouchPlayer window (Esc closes it).
