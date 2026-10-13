"""Putting an RGBA orb on screen, with per-pixel alpha where that is possible.

The survey settled the mechanism by measurement: ``-transparentcolor`` leaves a
soft glow's falloff visible as 62% of the window, and ``UpdateLayeredWindow``
with a premultiplied BGRA bitmap leaves none of it. So the orb is composited by
Windows rather than painted by tk.

**The fallback is built here, not promised.** ``UpdateLayeredWindow`` can be
refused -- a remote desktop session, a software renderer, a driver that declines
layered windows -- and a fallback nobody can trigger is not a fallback. So:

* every call is *checked*, not assumed. The Win32 return value decides.
* the first refusal switches the painter permanently and records why.
* :class:`DiscPainter` draws the same orb flattened onto an opaque disc, which
  needs no Win32 at all.
* the status line says which one is running, so a machine quietly on the
  fallback is visible rather than merely worse-looking.

Two traps worth stating, both found by measuring rather than by reading:

* every GDI signature here declares ``argtypes``. ctypes defaults an undeclared
  argument to ``c_int``, and a 64-bit ``HBITMAP`` does not fit --
  ``OverflowError: int too long to convert``. It happens to work when the
  handles are small, which is how a Win32 binding fails on someone else's
  machine and not on yours.
* **the window handle is resolved per paint, not captured once.** Tk re-creates
  a toplevel's HWND when it maps a borderless window, so a handle read before
  the first ``update()`` is stale by the time anything is drawn. Blitting to the
  stale handle *succeeded* -- the call returned non-zero and the orb was
  nowhere on screen, which is the precise failure the return-value check was
  supposed to catch. So the style bit is verified on the live handle before
  every blit, and the blit goes to that handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Window style bit that lets a window be composited with per-pixel alpha.
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
#: Tell UpdateLayeredWindow the source bitmap carries its own alpha.
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class OrbPainter(Protocol):
    """Puts an RGBA image on screen at a position."""

    name: str

    def paint(self, image: Any, x: int, y: int) -> bool:
        """Draw it. False means this painter could not, and another should."""


def _win32():
    """The two DLLs with their signatures declared. Raises if unavailable."""
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]
    gdi32.CreateDIBSection.argtypes = [
        wt.HDC, ctypes.c_void_p, wt.UINT,
        ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wt.HBITMAP
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.restype = ctypes.c_long
    return ctypes, wt, user32, gdi32


def _structures(ctypes, wt):
    class POINT(ctypes.Structure):
        _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
            ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
        ]

    return POINT, SIZE, BLENDFUNCTION, BITMAPINFOHEADER


def premultiplied_bgra(image: Any) -> bytes:
    """The byte layout UpdateLayeredWindow wants: BGRA, alpha premultiplied.

    Premultiplying is not optional -- without it the glow's semi-transparent
    pixels composite far too bright and the orb gets a white core.
    """
    import numpy as np

    array = np.asarray(image.convert("RGBA"), dtype=np.float32)
    alpha = array[:, :, 3:4] / 255.0
    return (
        np.concatenate(
            [
                array[:, :, 2:3] * alpha,
                array[:, :, 1:2] * alpha,
                array[:, :, 0:1] * alpha,
                array[:, :, 3:4],
            ],
            axis=2,
        )
        .astype(np.uint8)
        .tobytes()
    )


@dataclass
class LayeredPainter:
    """Per-pixel alpha through ``UpdateLayeredWindow``.

    *hwnd* may be an int or a callable returning one. A callable is what the
    view passes, because the handle changes when tk maps the window and a
    captured one is stale before the first frame.

    *update_layered_window* is injectable so a test can make the call fail and
    watch the fallback engage. Without that the fallback could only be taken on
    trust.
    """

    hwnd: Any
    update_layered_window: Any = None
    name: str = "layered"
    last_error: str = ""
    #: Handles already given the style bit, so it is set once per window rather
    #: than on every frame.
    _prepared: set = field(default_factory=set, init=False)

    def handle(self) -> int:
        """The window to paint, read now rather than remembered."""
        try:
            return int(self.hwnd() if callable(self.hwnd) else self.hwnd)
        except Exception:  # noqa: BLE001 - a view mid-teardown has no window
            return 0

    def prepare(self, hwnd: int | None = None) -> bool:
        """Add WS_EX_LAYERED, and check it took.

        Verified rather than assumed: without the bit UpdateLayeredWindow is
        meaningless, and the one failure that cost real time here was a blit
        that reported success into a window that never had it.
        """
        target = self.handle() if hwnd is None else int(hwnd)
        if not target:
            self.last_error = "no window handle"
            return False
        try:
            _ctypes, _wt, user32, _gdi32 = _win32()
            style = user32.GetWindowLongW(target, GWL_EXSTYLE)
            if not style & WS_EX_LAYERED:
                user32.SetWindowLongW(target, GWL_EXSTYLE, style | WS_EX_LAYERED)
            if not user32.GetWindowLongW(target, GWL_EXSTYLE) & WS_EX_LAYERED:
                self.last_error = "the window would not take WS_EX_LAYERED"
                return False
        except Exception as exc:  # noqa: BLE001 - absence is the thing being tested
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        self._prepared.add(target)
        return True

    def paint(self, image: Any, x: int, y: int) -> bool:
        try:
            ctypes, wt, user32, gdi32 = _win32()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

        hwnd = self.handle()
        if hwnd not in self._prepared and not self.prepare(hwnd):
            return False

        POINT, SIZE, BLENDFUNCTION, BITMAPINFOHEADER = _structures(ctypes, wt)
        width, height = image.size
        raw = premultiplied_bgra(image)

        screen_dc = user32.GetDC(0)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = None
        previous = None
        try:
            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth = width
            header.biHeight = -height  # top-down
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = 0
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(
                memory_dc, ctypes.cast(ctypes.byref(header), ctypes.c_void_p), 0,
                ctypes.byref(bits), None, 0,
            )
            if not bitmap:
                self.last_error = "CreateDIBSection returned NULL"
                return False
            ctypes.memmove(bits, raw, len(raw))
            previous = gdi32.SelectObject(memory_dc, bitmap)

            call = self.update_layered_window
            if call is None:
                user32.UpdateLayeredWindow.argtypes = [
                    wt.HWND, wt.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                    wt.HDC, ctypes.POINTER(POINT), wt.DWORD,
                    ctypes.POINTER(BLENDFUNCTION), wt.DWORD,
                ]
                call = user32.UpdateLayeredWindow
            ok = call(
                hwnd, screen_dc, ctypes.byref(POINT(int(x), int(y))),
                ctypes.byref(SIZE(width, height)), memory_dc,
                ctypes.byref(POINT(0, 0)), 0,
                ctypes.byref(BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)),
                ULW_ALPHA,
            )
            if not ok:
                self.last_error = "UpdateLayeredWindow refused the bitmap"
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - any refusal means fall back
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        finally:
            try:
                if previous is not None:
                    gdi32.SelectObject(memory_dc, previous)
                if bitmap:
                    gdi32.DeleteObject(bitmap)
                gdi32.DeleteDC(memory_dc)
                user32.ReleaseDC(0, screen_dc)
            except Exception:  # noqa: BLE001 - cleanup must not mask the result
                pass


@dataclass
class DiscPainter:
    """The fallback: an opaque disc, handed to the view to display.

    No Win32 at all. *show* is whatever the view does with an image -- in
    practice putting it in a Label -- so this is testable without a window.
    """

    show: Any
    name: str = "disc"
    last_error: str = ""
    painted: int = field(default=0, init=False)

    def prepare(self) -> bool:
        return True

    def paint(self, image: Any, x: int, y: int) -> bool:
        try:
            self.show(image, x, y)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        self.painted += 1
        return True


@dataclass
class PainterChoice:
    """Which painter is running, and why -- for the status line.

    The first refusal switches permanently: a driver that declines one frame
    will decline the next, and flapping between two looks would be worse than
    either.
    """

    primary: Any
    fallback: Any
    #: Set once the primary has refused, so it is not retried every frame.
    demoted: bool = False
    reason: str = ""

    @property
    def active(self) -> Any:
        return self.fallback if self.demoted else self.primary

    @property
    def mode(self) -> str:
        return str(getattr(self.active, "name", "unknown"))

    def paint(self, image: Any, x: int, y: int) -> bool:
        """Try the primary; demote permanently on the first refusal."""
        if not self.demoted:
            if self.primary.paint(image, x, y):
                return True
            self.demoted = True
            self.reason = (
                getattr(self.primary, "last_error", "") or "the primary painter refused"
            )
        return self.fallback.paint(image, x, y)

    def describe(self) -> str:
        """What the status line says, so a machine on the fallback is visible."""
        if not self.demoted:
            return "orb: glow"
        return f"orb: flat disc ({self.reason})"


__all__ = [
    "DiscPainter",
    "LayeredPainter",
    "OrbPainter",
    "PainterChoice",
    "WS_EX_LAYERED",
    "premultiplied_bgra",
]
