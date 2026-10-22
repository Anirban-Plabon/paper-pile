"""Per-screen scale on WSL.

WSLg tells Linux apps that every monitor is at 100 %, whatever Windows uses (e.g. a laptop panel
at 150 % next to an external screen at 100 %), so a Linux window looks a third smaller on the
scaled screen. Windows knows the real scale of each monitor; this asks it (one PowerShell call)
and matches its monitors to the screens the GUI sees by their pixel geometry.

Pure logic plus one subprocess call; the GUI decides what to do with the numbers.
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("paper_pile.display")

_ROW = re.compile(r"PPMON (-?\d+) (-?\d+) (\d+) (\d+) (\d+)(?: WORK (-?\d+) (-?\d+) (\d+) (\d+))?")
POWERSHELL_FALLBACK = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")

# Per-monitor-aware, so rectangles are in physical pixels (as WSLg reports them) and the DPI is
# the effective one (96 = 100 %). Prints "left top width height dpi WORK left top width height";
# the work area is the monitor without the Windows taskbar (WSLg does not know about it).
_SCRIPT = r"""
$ProgressPreference = 'SilentlyContinue'
Add-Type -TypeDefinition @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class PPMon {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)]
  public struct MI { public int cb; public RECT mon; public RECT work; public uint flags; }
  public delegate bool Proc(IntPtr h, IntPtr dc, ref RECT r, IntPtr d);
  [DllImport("user32.dll")]
  static extern bool EnumDisplayMonitors(IntPtr dc, IntPtr clip, Proc cb, IntPtr d);
  [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr h, ref MI mi);
  [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
  [DllImport("shcore.dll")]
  static extern int GetDpiForMonitor(IntPtr h, int kind, out uint x, out uint y);
  public static string Run() {
    SetThreadDpiAwarenessContext(new IntPtr(-4));
    List<string> rows = new List<string>();
    Proc each = delegate(IntPtr h, IntPtr dc, ref RECT r, IntPtr d) {
      MI mi = new MI(); mi.cb = Marshal.SizeOf(typeof(MI)); GetMonitorInfo(h, ref mi);
      uint x, y; GetDpiForMonitor(h, 0, out x, out y);
      int w = mi.mon.R - mi.mon.L, ht = mi.mon.B - mi.mon.T;
      int ww = mi.work.R - mi.work.L, wh = mi.work.B - mi.work.T;
      string work = " WORK " + mi.work.L + " " + mi.work.T + " " + ww + " " + wh;
      rows.Add("PPMON " + mi.mon.L + " " + mi.mon.T + " " + w + " " + ht + " " + x + work);
      return true; };
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, each, IntPtr.Zero);
    return string.Join("\n", rows.ToArray());
  }
}
"@
[PPMon]::Run()
"""


@dataclass(frozen=True, slots=True)
class Monitor:
    """A monitor rectangle in physical pixels and its scale (1.5 = 150 %)."""

    left: int
    top: int
    width: int
    height: int
    scale: float
    work_width: int = 0  # the part not covered by the Windows taskbar (0: unknown, all of it)
    work_height: int = 0
    work_left: int = 0  # where that part starts, as ``left`` / ``top``
    work_top: int = 0


@dataclass(frozen=True, slots=True)
class Screen:
    """A screen as the GUI sees it, rectangle in physical pixels."""

    name: str
    left: int
    top: int
    width: int
    height: int


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def parse_monitors(text: str) -> list[Monitor]:
    """Read the script's ``PPMON l t w h dpi [WORK w h]`` lines, skipping PowerShell's other
    output."""
    monitors = []
    # a row can share its line with PowerShell's progress XML, so search rather than split
    for left, top, width, height, dpi, work_l, work_t, work_w, work_h in _ROW.findall(text):
        if int(width) > 0 and int(height) > 0 and int(dpi) > 0:
            monitors.append(
                Monitor(
                    int(left),
                    int(top),
                    int(width),
                    int(height),
                    int(dpi) / 96,
                    int(work_w or 0),
                    int(work_h or 0),
                    int(work_l or 0),
                    int(work_t or 0),
                )
            )
    return monitors


def _normalised(rects: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    # WSLg shifts the layout so nothing is negative; compare both layouts from their top-left
    if not rects:
        return []
    dx = min(r[0] for r in rects)
    dy = min(r[1] for r in rects)
    return [(x - dx, y - dy, w, h) for x, y, w, h in rects]


def match_scales(screens: list[Screen], monitors: list[Monitor]) -> dict[str, float]:
    """Scale per screen name (see :func:`match_monitors`)."""
    return {name: m.scale for name, m in match_monitors(screens, monitors).items()}


def work_area(monitor: Monitor) -> tuple[int, int]:
    """The usable size of ``monitor`` in physical pixels (all of it when the taskbar is unknown)."""
    return (monitor.work_width or monitor.width, monitor.work_height or monitor.height)


def taskbar_insets(monitor: Monitor, window_height: int) -> tuple[int, int]:
    """``(top, bottom)`` physical pixels of a maximized window of ``window_height`` (physical)
    that lie under the Windows taskbar. WSLg maximizes to the whole monitor on some screens; the
    page then keeps its content out of these strips."""
    if not monitor.work_height or window_height <= monitor.work_height:
        return (0, 0)
    top = max(0, monitor.work_top - monitor.top) if monitor.work_width else 0
    return (top, max(0, window_height - monitor.work_height - top))


def match_monitors(screens: list[Screen], monitors: list[Monitor]) -> dict[str, Monitor]:
    """The Windows monitor of each screen: same rectangle first, else the only one of that size."""
    if not screens or not monitors:
        return {}
    screen_rects = _normalised([(s.left, s.top, s.width, s.height) for s in screens])
    monitor_rects = _normalised([(m.left, m.top, m.width, m.height) for m in monitors])
    result: dict[str, Monitor] = {}
    for screen, rect in zip(screens, screen_rects, strict=True):
        same = [m for m, r in zip(monitors, monitor_rects, strict=True) if r == rect]
        if not same:
            same = [m for m in monitors if (m.width, m.height) == rect[2:]]
        if len(same) == 1:
            result[screen.name] = same[0]
    return result


def _powershell() -> str | None:
    found = shutil.which("powershell.exe")
    if found:
        return found
    return str(POWERSHELL_FALLBACK) if POWERSHELL_FALLBACK.exists() else None


def query_windows_monitors(timeout: float = 30) -> list[Monitor] | None:
    """Ask Windows for its monitors (a few seconds); None when it can't be asked."""
    exe = _powershell()
    if exe is None:
        return None
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    cwd = "/mnt/c" if Path("/mnt/c").is_dir() else None  # avoids the UNC-path warning
    try:
        done = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("could not ask Windows for monitor scales: %s", exc)
        return None
    monitors = parse_monitors(done.stdout)
    return monitors or None


def load_cached(path: Path) -> list[Monitor]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [Monitor(**row) for row in rows]
    except (OSError, ValueError, TypeError):
        return []


def save_cached(path: Path, monitors: list[Monitor]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([asdict(m) for m in monitors]), encoding="utf-8")
    except OSError as exc:
        log.info("could not cache monitor scales: %s", exc)
