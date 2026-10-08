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

# The key's name is the controller's to decide; this module only renders
# it. Imported rather than repeated: a literal "hold SPACE" in the header
# outlived the change of default to f9 and shipped, because the constant
# moved and the copies of it did not. One direction only -- bubble.py
# imports no toolkit and nothing from here.
from grandpa.ui.bubble import DEFAULT_HOLD_KEY, METER_BARS
from grandpa.voice.push_to_talk import describe_hold_key, parse_hold_key

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

#: Our key names mapped to Tk keysyms, so the hold key can be swallowed in the
#: entry box.
#:
#: Holding the key while the bubble has focus used to put a character in the text
#: box and record nothing a user could see. The two mechanisms can coexist, and
#: the binding level is what makes it work. Measured, because the obvious
#: implementation is the wrong one:
#:
#:     control: no "break", bound on the entry      entry 'ab '   not suppressed
#:     instance binding on the entry + "break"      entry 'ab'    SUPPRESSED
#:     binding on the toplevel + "break"            entry 'ab '   not suppressed
#:
#: Tk resolves bindings in bindtags order -- ``('.!entry', 'Entry', '.', 'all')``
#: -- and the Entry's insertion *is* its class binding. An instance binding runs
#: first and ``"break"`` stops the class binding; a toplevel binding runs third,
#: after the character is already in.
#:
#: And it cannot eat the global key, because a KeyPress is only delivered to the
#: focused window: with the bubble unfocused this binding never fires, while
#: ``GetAsyncKeyState`` never consults focus. Same key, both paths, no conflict.
KEY_SYMS: dict[str, tuple[str, ...]] = {
    "space": ("space",),
    "ctrl": ("Control_L", "Control_R"),
    "shift": ("Shift_L", "Shift_R"),
    "alt": ("Alt_L", "Alt_R"),
    "f8": ("F8",),
    "f9": ("F9",),
    "f10": ("F10",),
    # Both spellings deliberately. Tk on Windows reports the Windows key as
    # Win_L/Win_R and the context-menu key as App; the X11 names are bound too
    # so a binding is not silently absent on another platform. Binding a keysym
    # tk never delivers costs nothing.
    "win": ("Win_L", "Super_L"),
    "rwin": ("Win_R", "Super_R"),
    "menu": ("App", "Menu"),
}

#: Colour per state, so the indicator is readable at a glance.
STATE_COLOURS = {
    "loading": "#8a8a8a",
    "idle": "#4caf50",
    "recording": "#e53935",
    "transcribing": "#fb8c00",
    "thinking": "#1e88e5",
    "error": "#e53935",
}

BACKGROUND = "#17181b"
SURFACE = "#1f2024"
FOREGROUND = "#f2f3f5"
MUTED = "#8b8f98"
DIVIDER = "#2a2c31"
WIDTH = 392
HEIGHT = 286

#: Type scale. Three sizes only -- state, body, meta -- so the window has a
#: readable hierarchy without becoming a design exercise.
FONT_STATE = ("Segoe UI Semibold", 11)
FONT_BODY = ("Segoe UI", 10)
FONT_META = ("Segoe UI", 8)

#: The level meter. Bars are created once and only their coordinates change, so
#: a meter updating ten times a second never allocates a canvas item.
METER_HEIGHT = 30
METER_BAR_GAP = 2.0
#: Drawn when nothing is being recorded: a flat line, not an empty box.
METER_RESTING_HEIGHT = 2.0


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
    #: The hold key -- possibly a combination like ``ctrl+win`` -- so it can be
    #: swallowed in the entry rather than typed.
    hold_key: str = DEFAULT_HOLD_KEY
    #: Asked, at the instant of the keystroke, whether the *whole* hold key is
    #: down. A combination has to be bound part by part, so without this the
    #: swallow would over-reach: binding Control_L for ``ctrl+win`` would eat
    #: Ctrl+C in the bubble's own text box. Injected, because the view has no
    #: key probe and must not grow one. ``None`` means swallow unconditionally,
    #: which is the single-key behaviour this replaced.
    combo_is_down: Any = None
    #: Called when the hold key is pressed while the bubble has focus. The
    #: character is already suppressed by then; this is so the bubble can say it
    #: saw the key instead of appearing to ignore it.
    on_hold_key: Any = None
    #: Called when the speech toggle is clicked.
    on_toggle_speech: Any = None
    root: Any = field(default=None, init=False)
    _widgets: dict[str, Any] = field(default_factory=dict, init=False)
    _drag_origin: tuple[int, int] = field(default=(0, 0), init=False)
    _swallowed_press: bool = field(default=False, init=False)
    _meter_bars: list[Any] = field(default_factory=list, init=False)

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
            header, text="Loading model...", bg=BACKGROUND, fg=FOREGROUND, anchor="w",
            font=FONT_STATE,
        )
        self._widgets["state"].pack(side="left", padx=(7, 0))
        # Discoverability only. The primitive is the held key, which works
        # without this window having focus; clicking here would move focus and
        # the pointer away from whatever is being dictated into.
        self._widgets["hold_hint"] = tk.Label(
            header, text=self.hold_hint_text(), bg=SURFACE, fg=MUTED,
            font=FONT_META, padx=6, pady=2,
        )
        self._widgets["hold_hint"].pack(side="right")
        # Spoken replies, on or off. A label rather than a Checkbutton so it
        # cannot be tabbed into -- the window must never acquire focus except
        # from a deliberate click.
        self._widgets["speak"] = tk.Label(
            header, text=self._speak_label(True), bg=SURFACE, fg=MUTED,
            font=FONT_META, padx=6, pady=2,
        )
        self._widgets["speak"].pack(side="right", padx=(0, 6))
        self._widgets["speak"].bind("<Button-1>", self._toggle_speech)

        # The level meter sits directly under the state line, because while the
        # key is held it is the only thing the user is looking at.
        meter = tk.Canvas(
            root, height=METER_HEIGHT, bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        meter.pack(fill="x", padx=10, pady=(2, 2))
        self._widgets["meter"] = meter
        self._meter_bars = [
            meter.create_rectangle(0, 0, 0, 0, fill=DIVIDER, width=0)
            for _ in range(METER_BARS)
        ]
        self.set_levels(())

        self._widgets["transcript"] = tk.Label(
            root, text="", bg=BACKGROUND, fg=MUTED, anchor="w", justify="left",
            wraplength=WIDTH - 24, font=FONT_BODY,
        )
        self._widgets["transcript"].pack(fill="x", padx=10, pady=(0, 2))

        # Text, not Label: a reply has to be selectable so it can be copied.
        reply = tk.Text(
            root, height=6, bg=SURFACE, fg=FOREGROUND, relief="flat", wrap="word",
            insertbackground=FOREGROUND, font=FONT_BODY,
            padx=8, pady=6, highlightthickness=0, bd=0,
        )
        reply.pack(fill="both", expand=True, padx=10, pady=(2, 6))
        # Read-only but still selectable. "disabled" would block selection too.
        reply.bind("<Key>", lambda _event: "break")
        self._widgets["reply"] = reply

        entry = tk.Entry(
            root, bg=SURFACE, fg=FOREGROUND, relief="flat",
            insertbackground=FOREGROUND, font=FONT_BODY,
            highlightthickness=0, bd=0,
            # Keeps the entry out of the tab order, so the window cannot acquire
            # focus by being tabbed into from elsewhere.
            takefocus=False,
        )
        entry.pack(fill="x", padx=10, pady=(0, 6))
        entry.bind("<Return>", self._submit)
        # On the entry, not the toplevel: a toplevel binding fires after the
        # class binding that inserts the character, so "break" there is too
        # late. See KEY_SYMS for the measurement.
        for part in self._hold_key_parts():
            for keysym in KEY_SYMS.get(part, ()):
                entry.bind(f"<KeyPress-{keysym}>", self._swallow_hold_key)
                # The release too, so a key-up cannot insert either -- but only
                # when the matching press was swallowed. See the handler.
                entry.bind(f"<KeyRelease-{keysym}>", self._release_hold_key)
        self._widgets["entry"] = entry

        self._widgets["status"] = tk.Label(
            root, text="", bg=BACKGROUND, fg=MUTED, anchor="w",
            wraplength=WIDTH - 24, justify="left", font=FONT_META,
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

    def _hold_key_parts(self) -> tuple[str, ...]:
        """The keys that make up the hold, or none if the spec is unusable."""
        try:
            return parse_hold_key(self.hold_key)
        except ValueError:
            return ()

    # --- the level meter -----------------------------------------------------

    def set_levels(self, levels: tuple[float, ...]) -> None:
        """Draw the capture meter from values the controller normalised.

        Only coordinates change: the bars are created once in :meth:`show`, so
        redrawing ten times a second allocates nothing. An empty tuple means
        "not recording" and draws a flat resting line rather than an empty box,
        because a blank strip reads as a broken widget.
        """
        meter = self._widgets.get("meter")
        if meter is None or not self._meter_bars:
            return
        usable = float(WIDTH - 20)
        slot = usable / max(1, len(self._meter_bars))
        bar_width = max(1.0, slot - METER_BAR_GAP)
        middle = METER_HEIGHT / 2.0
        active = bool(levels)
        for index, bar in enumerate(self._meter_bars):
            value = levels[index] if index < len(levels) else 0.0
            height = max(METER_RESTING_HEIGHT, value * (METER_HEIGHT - 2.0))
            left = index * slot
            try:
                meter.coords(
                    bar, left, middle - height / 2.0, left + bar_width,
                    middle + height / 2.0,
                )
                meter.itemconfigure(
                    bar, fill=STATE_COLOURS["recording"] if active else DIVIDER
                )
            except Exception:  # noqa: BLE001 - a closed window must not raise
                return

    # --- spoken replies ------------------------------------------------------

    @staticmethod
    def _speak_label(enabled: bool) -> str:
        return "speech on" if enabled else "speech off"

    def set_speech_enabled(self, enabled: bool) -> None:
        """Reflect whether replies are spoken. The controller owns the truth."""
        widget = self._widgets.get("speak")
        if widget is None:
            return
        try:
            widget.configure(
                text=self._speak_label(enabled), fg=FOREGROUND if enabled else MUTED
            )
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def _toggle_speech(self, _event: Any = None) -> None:
        if callable(self.on_toggle_speech):
            try:
                self.on_toggle_speech()
            except Exception:  # noqa: BLE001 - a click must not kill the UI
                pass

    def hold_hint_text(self) -> str:
        """What the header tells the user to hold.

        Derived from :attr:`hold_key`, never written out. The window said
        "hold SPACE" for a whole release after the default became f9, and
        this label is the one place a user actually reads the key name.
        """
        return f"hold {describe_hold_key(self.hold_key)}"

    def _release_hold_key(self, _event: Any = None) -> str | None:
        """Swallow a key-up only if its key-down was swallowed.

        Otherwise releasing Ctrl after an ordinary Ctrl+C would be eaten too,
        which is the over-reach the predicate exists to avoid.
        """
        if not self._swallowed_press:
            return None
        self._swallowed_press = False
        return "break"

    def _swallow_hold_key(self, _event: Any = None) -> str | None:
        """Keep the hold key out of the text box, and say it was seen.

        Returning ``"break"`` stops the Entry's class binding, which is what
        would otherwise insert the character. The global probe is unaffected --
        it reads the keyboard, not this window's events -- so the hold still
        starts; this only stops the character and tells the controller to
        explain itself rather than appear to do nothing.
        """
        if callable(self.combo_is_down):
            try:
                engaged = bool(self.combo_is_down())
            except Exception:  # noqa: BLE001 - a predicate must not eat a key
                engaged = False
            if not engaged:
                # One part of a combination, pressed on its own. Not ours, so
                # let the keystroke reach the entry and Ctrl+C still copies.
                return None
        self._swallowed_press = True
        if callable(self.on_hold_key):
            try:
                self.on_hold_key()
            except Exception:  # noqa: BLE001 - a keypress must not kill the UI
                pass
        return "break"

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


__all__ = ["FOCUS_STEALING_CALLS", "KEY_SYMS", "STATE_COLOURS", "TkBubbleView"]
