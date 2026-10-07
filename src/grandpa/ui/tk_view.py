"""The tkinter window. The toolkit is injected, so a test opens nothing.

The same shape as ``grandpa.tray.start_tray(pystray_module=...)``: the module is
a parameter, never an import at test time. Tests pass a recorder and assert on
the calls, which is how the focus guarantee below is checked rather than assumed.

Three window attributes carry the requirements, and all three are already proven
in this repository by ``automation.locator._render_tk_overlay``, which draws a
borderless always-on-top transparent highlight over an arbitrary window:

    overrideredirect(True)        borderless -- no title bar to drag or close
    attributes("-topmost", True)  stays above other windows
    geometry("+x+y")              placed where it was left

**It must never take focus.** A floating window that grabs keystrokes is worse
than no window: the normal case is typing into something else while the bubble is
visible. So nothing here calls ``focus_force``, ``focus_set``, ``grab_set`` or
``takefocus``, the entry box takes focus only from a real click, and
``tests/ui/test_bubble_never_takes_focus.py`` asserts the absence by inspecting
every recorded call rather than trusting this paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Calls that would move focus to the bubble. None of them may ever appear.
FOCUS_STEALING_CALLS = (
    "focus_force",
    "focus_set",
    "grab_set",
    "grab_set_global",
    "lift",
    "deiconify",
    "tkraise",
)

#: Colour per state, so the indicator is readable at a glance.
STATE_COLOURS = {
    "loading": "#8a8a8a",
    "idle": "#4caf50",
    "recording": "#e53935",
    "transcribing": "#fb8c00",
    "thinking": "#1e88e5",
    "error": "#e53935",
}

BACKGROUND = "#1c1c1c"
FOREGROUND = "#f0f0f0"
WIDTH = 380
HEIGHT = 240


@dataclass
class TkBubbleView:
    """A borderless, always-on-top bubble.

    ``tkinter_module`` is the injection point. Left as ``None`` it is imported
    on first use, which is what the real command does and what no test does.
    """

    tkinter_module: Any = None
    title: str = "Grandpa"
    on_submit: Any = None
    on_close: Any = None
    root: Any = field(default=None, init=False)
    _widgets: dict[str, Any] = field(default_factory=dict, init=False)
    _drag_origin: tuple[int, int] = field(default=(0, 0), init=False)

    def _tk(self) -> Any:
        if self.tkinter_module is None:
            import tkinter

            self.tkinter_module = tkinter
        return self.tkinter_module

    # --- BubbleView ----------------------------------------------------------

    def show(self, *, position: tuple[int, int], topmost: bool) -> None:
        tk = self._tk()
        root = tk.Tk()
        self.root = root
        root.title(self.title)
        # Borderless: no title bar, which is also why dragging is bound below.
        root.overrideredirect(True)
        if topmost:
            root.attributes("-topmost", True)
        root.geometry(f"{WIDTH}x{HEIGHT}+{int(position[0])}+{int(position[1])}")
        root.configure(bg=BACKGROUND)

        header = tk.Frame(root, bg=BACKGROUND)
        header.pack(fill="x", padx=10, pady=(10, 4))
        # The state dot and its label.
        self._widgets["dot"] = tk.Label(
            header, text="●", bg=BACKGROUND, fg=STATE_COLOURS["loading"]
        )
        self._widgets["dot"].pack(side="left")
        self._widgets["state"] = tk.Label(
            header, text="Loading model...", bg=BACKGROUND, fg=FOREGROUND, anchor="w"
        )
        self._widgets["state"].pack(side="left", padx=(6, 0))
        # Discoverability only. The primitive is the held key, which works
        # without this window having focus; clicking here would move focus and
        # the pointer away from whatever is being dictated into.
        self._widgets["hold_hint"] = tk.Label(
            header, text="hold SPACE", bg=BACKGROUND, fg="#8a8a8a"
        )
        self._widgets["hold_hint"].pack(side="right")

        self._widgets["transcript"] = tk.Label(
            root, text="", bg=BACKGROUND, fg="#b0b0b0", anchor="w", justify="left",
            wraplength=WIDTH - 24,
        )
        self._widgets["transcript"].pack(fill="x", padx=10)

        # Text, not Label: a reply has to be selectable so it can be copied.
        reply = tk.Text(
            root, height=6, bg="#242424", fg=FOREGROUND, relief="flat", wrap="word",
            insertbackground=FOREGROUND,
        )
        reply.pack(fill="both", expand=True, padx=10, pady=6)
        # Read-only but still selectable. "disabled" would block selection too.
        reply.bind("<Key>", lambda _event: "break")
        self._widgets["reply"] = reply

        entry = tk.Entry(
            root, bg="#242424", fg=FOREGROUND, relief="flat",
            insertbackground=FOREGROUND,
            # Keeps the entry out of the tab order, so the window cannot acquire
            # focus by being tabbed into from elsewhere.
            takefocus=False,
        )
        entry.pack(fill="x", padx=10, pady=(0, 6))
        entry.bind("<Return>", self._submit)
        self._widgets["entry"] = entry

        self._widgets["status"] = tk.Label(
            root, text="", bg=BACKGROUND, fg="#8a8a8a", anchor="w",
            wraplength=WIDTH - 24, justify="left",
        )
        self._widgets["status"].pack(fill="x", padx=10, pady=(0, 10))

        # Dragging, because overrideredirect removed the title bar.
        for widget in (header, self._widgets["state"], self._widgets["dot"]):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        root.bind("<Escape>", lambda _event: self._close())

    def set_state(self, state: str, label: str) -> None:
        dot = self._widgets.get("dot")
        if dot is not None:
            dot.configure(fg=STATE_COLOURS.get(state, FOREGROUND))
        widget = self._widgets.get("state")
        if widget is not None:
            widget.configure(text=label)

    def set_status_line(self, text: str) -> None:
        widget = self._widgets.get("status")
        if widget is not None:
            widget.configure(text=text)

    def set_transcript(self, text: str) -> None:
        widget = self._widgets.get("transcript")
        if widget is not None:
            widget.configure(text=f"“{text}”" if text else "")

    def set_reply(self, text: str) -> None:
        widget = self._widgets.get("reply")
        if widget is None:
            return
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def clear_entry(self) -> None:
        widget = self._widgets.get("entry")
        if widget is not None:
            widget.delete(0, "end")

    def position(self) -> tuple[int, int]:
        if self.root is None:
            return (0, 0)
        try:
            return int(self.root.winfo_x()), int(self.root.winfo_y())
        except Exception:
            return (0, 0)

    def close(self) -> None:
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    # --- the loop ------------------------------------------------------------

    def pump(self, interval_ms: int, callback: Any) -> None:
        """Run *callback* on the tk loop every *interval_ms*.

        The hold has to be polled from somewhere, and tkinter owns the thread
        that may touch widgets. ``after`` keeps the poll on that thread instead
        of mutating widgets from the watcher.
        """
        if self.root is None:
            return

        def tick() -> None:
            try:
                callback()
            finally:
                if self.root is not None:
                    self.root.after(interval_ms, tick)

        self.root.after(interval_ms, tick)

    def run(self) -> None:
        if self.root is not None:
            self.root.mainloop()

    # --- internals -----------------------------------------------------------

    def _submit(self, _event: Any = None) -> str:
        entry = self._widgets.get("entry")
        text = entry.get() if entry is not None else ""
        if callable(self.on_submit):
            self.on_submit(text)
        return "break"

    def _drag_start(self, event: Any) -> None:
        self._drag_origin = (int(event.x), int(event.y))

    def _drag_move(self, event: Any) -> None:
        if self.root is None:
            return
        x = int(event.x_root) - self._drag_origin[0]
        y = int(event.y_root) - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _close(self) -> None:
        if callable(self.on_close):
            self.on_close()
        else:
            self.close()


__all__ = ["FOCUS_STEALING_CALLS", "STATE_COLOURS", "TkBubbleView"]
