# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License,
# as published by the Free Software Foundation, either version 2 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the  GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, see <https://www.gnu.org/licenses/>.

'''
Colour temperature as a GPU shader.

FFmpeg's colortemperature video filter runs on the CPU for every pixel of every frame, and forces
hardware-decoded frames back to the CPU. On large videos that stutters. The same maths in a tiny
mpv user shader costs next to nothing on the GPU.

libmpv's render API uses mpv's older gpu renderer, which has no runtime shader parameters
(--glsl-shader-opts is gpu-next only) and caches shader files by path. So each temperature gets its
own file with the gains written in as constants.
'''

import hashlib
import math
import os
import tempfile

STEP_K = 50  # temperatures are rounded to this, so at most a few dozen shader files ever exist
PRESERVE_LIGHTNESS = 0.5  # FFmpeg's pl=0.5, which TouchPlayer always used

_SHADER = '''//!HOOK MAIN
//!BIND HOOKED
//!DESC TouchPlayer colour temperature {kelvin}K

// Same maths as FFmpeg's colortemperature filter (mix=1, pl={preserve})
vec4 hook() {{
    vec4 c = HOOKED_texOff(0);
    vec3 n = c.rgb * vec3({r:.6f}, {g:.6f}, {b:.6f});
    float l0 = max(max(c.r, c.g), c.b) + min(min(c.r, c.g), c.b) + 1e-6;
    float l1 = max(max(n.r, n.g), n.b) + min(min(n.r, n.g), n.b) + 1e-6;
    c.rgb = mix(n, n * (l0 / l1), {preserve:.6f});
    return c;
}}
'''


def gains(kelvin):
    """Per-channel RGB multipliers for a temperature, as FFmpeg's kelvin2rgb computes them"""
    k = kelvin / 100.0
    if k <= 66.0:
        r = 1.0
        g = 0.39008157876901960784 * math.log(k) - 0.63184144378862745098
    else:
        t = max(k - 60.0, 0.0)
        r = 1.29293618606274509804 * math.pow(t, -0.1332047592)
        g = 1.12989086089529411765 * math.pow(t, -0.0755148492)
    if k >= 66.0:
        b = 1.0
    elif k <= 19.0:
        b = 0.0
    else:
        b = 0.54320678911019607843 * math.log(k - 10.0) - 1.19625408914
    return tuple(min(max(v, 0.0), 1.0) for v in (r, g, b))


def quantise(kelvin):
    return int(math.floor(kelvin / STEP_K + 0.5)) * STEP_K  # halves round up; round() would round to even


def shaderSource(kelvin):
    r, g, b = gains(kelvin)
    return _SHADER.format(kelvin=kelvin, r=r, g=g, b=b, preserve=PRESERVE_LIGHTNESS)


def shaderDir():
    """A per-user folder kept across runs: at most a few dozen tiny files, so nothing to clean up after a crash"""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    folder = os.path.join(base, "touchplayer-shaders-%d" % os.getuid())
    os.makedirs(folder, mode=0o700, exist_ok=True)
    return folder


def shaderPath(kelvin, folder=None):
    """The shader file for a temperature, written if missing. Raises OSError if it cannot be written.
    The name carries a hash of the source, so an upgrade never reuses an older version's file."""
    source = shaderSource(quantise(kelvin))
    digest = hashlib.sha1(source.encode()).hexdigest()[:10]
    folder = folder or shaderDir()
    path = os.path.join(folder, "colortemp-%d-%s.glsl" % (quantise(kelvin), digest))
    if not os.path.exists(path):
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(source)
            os.replace(tmp, path)  # never a half-written file at the final name
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return path
