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
from grandpa.ui.palette import RING_COLOURS
from grandpa.voice.push_to_talk import describe_hold_key, parse_hold_key

#: The only widgets a drag may start from: the header strip and the two
#: non-interactive labels inside it. Everything else in the panel is something
#: you click, type into or select, and a drag beginning there would fight it.
DRAG_HANDLE_WIDGETS = ("header", "state", "dot")

#: Calls that would move focus to the bubble. None of them may ever appear.
FOCUS_STEALING_CALLS = (
    "focus_force",
    "focus_set",
    "grab_set",
    "grab_set_global",
    "lift",
    "tkraise",
)

#: ``deiconify`` was on the list above until it was measured. On a borderless
#: topmost window it does *not* take the foreground: with the panel withdrawn,
#: the foreground window was the same handle before and after the call, and
#: never the panel's own. It is kept separate rather than merged into the list
#: because the safety is conditional -- it is safe as the *undo of a withdraw*,
#: and a test pins it to that one use. Used to raise an already-visible window
#: it would be ``lift`` by another name.
REMAP_CALLS = ("withdraw", "deiconify")

#: Recorded because it is the one hole in the promise, and the recorded-call
#: tests cannot see it: ``Tk()`` itself takes the foreground when the window
#: first appears -- measured, the foreground window became the panel's own
#: handle. No call in this file causes it and none can undo it. Which is why
#: collapsing is a withdraw and never a destroy-and-rebuild: rebuilding would
#: take the foreground again on every single expand.
CREATION_TAKES_FOREGROUND = True

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
#: The state dot and the meter bars, from the same palette the orb draws
#: from. These were separate values and they disagreed with the orb about every
#: state -- idle was green here and blue there, thinking blue here and violet
#: there. A colour that means two things means nothing.
STATE_COLOURS = dict(RING_COLOURS)

BACKGROUND = "#17181b"
SURFACE = "#1f2024"
FOREGROUND = "#f2f3f5"
MUTED = "#8b8f98"
DIVIDER = "#2a2c31"

#: 520 wide, as the design asks. This moves the point at which the panel flips
#: to the orb's other side: it fits on the right while
#: ``orb_x + ORB_SIZE + ANCHOR_GAP + WIDTH <= work_area_right``, so on a
#: 1536-wide work area that is orb_x <= 956 rather than 1076 -- 120 pixels
#: earlier. ``anchor_panel_to_orb`` and ``_panel_fits`` both take the size as a
#: parameter and the command passes these constants, so they follow; the
#: environment-marked corner test is what proves they do.
WIDTH = 520

#: 512 rather than the 480 this started at, because the rows are budgeted in
#: pixels and tk's own scaling is not a constant on one machine.
#:
#: Measured, same display, same session: ``tk scaling`` is 1.335 when the panel
#: runs as an ordinary script and 1.668 under pytest -- a ratio of exactly the
#: display's 125%, because one process ends up DPI-aware and the other does
#: not. At the larger figure every meta line grows from 19 pixels to 23 and the
#: conversation needs 268 where 480 gave it 248, so the action row was simply
#: not mapped and copy, read and stop vanished.
#:
#: 512 gives the conversation 280: twelve pixels of margin over the worst
#: metric measured rather than the one-pixel fit 480 had. A panel that sized
#: itself from its content would not need the margin at all, and that is the
#: real fix if a third metric ever turns up.
HEIGHT = 512

#: The bubbles. Grandpa on the left in grey, the user on the right in blue, as
#: two speakers in a conversation rather than two captioned panes.
BUBBLE_GRANDPA = "#2a2a3a"
BUBBLE_USER = "#1e3a5f"

#: Corner radius for the bubbles and for the panel's own inner border.
#:
#: Drawn on a Canvas with ``create_polygon(smooth=True)``, because measured,
#: ``tk.Frame`` has no radius option of any kind. The panel's *window* is a hard
#: rectangle too -- also measured: a borderless toplevel's corner pixel is panel
#: coloured, radius 0, so Windows 11's compositor does not round it. Rounding
#: the window itself would need ``SetWindowRgn`` or a layered window, which is a
#: second Win32 mechanism and its own decision. So the border is drawn inside.
#:
#: **And the panel still reads as square.** Measured, not predicted. The border
#: canvas fills the window and the body frame sits on top of it, opaque and
#: square, inset by three logical pixels -- so the only part of the border a
#: person can see is the three pixels of straight run at each edge and a nick
#: at each corner. Reading the top-left 50x50 at 125%, eight rows of the arc
#: are missing as shipped; unpack the body and every row but the outermost has
#: border in it, so the arc is drawn and simply covered. A panel with genuinely
#: rounded corners needs the window itself rounded -- ``SetWindowRgn`` or a
#: layered panel -- which is the second mechanism this deliberately avoids.
#: BUBBLE_RADIUS is a different case: a bubble's canvas has nothing on top of
#: it, so its corners are the radius they say.
BUBBLE_RADIUS = 12
PANEL_RADIUS = 14

#: What one of those radii has to be multiplied by before tk will draw it.
#:
#: ``create_polygon(smooth=True)`` is a quadratic B-spline. It is tangent to
#: the midpoints of its control segments and does not pass through the corner
#: control point at all, so it cuts the corner far tighter than the radius
#: asked for. Measured on screen, four nominal radii against the visible arc
#: in logical pixels:
#:
#:     nominal   8    14    20    28
#:     visible 3.2   5.6   8.0  10.4
#:
#: A flat 0.40, so the correction is a constant rather than a curve.
#: Duplicating the control points so the straight runs stay straight changes
#: nothing -- also measured, identical to the pixel. The radii above are
#: therefore what a person sees, and this is what turns one into the other.
SPLINE_RADIUS_FACTOR = 1.0 / 0.40

#: Header band. Fixed, because the drag handle is the header and a handle that
#: changes height with its content is a handle that moves under the pointer.
HEADER_HEIGHT = 68

#: The action row under a Grandpa message: 40x22 outlined buttons at 10pt.
ACTION_WIDTH = 40
ACTION_HEIGHT = 22

#: The three buttons right of the input field.
INPUT_BUTTON = 38

#: The two bubbles, and the text area inside each.
#:
#: Fixed rather than fitted to the text, so the layout does not jump between
#: a one-line reply and a five-line one. The heights are what the window has
#: room for: measured on the real packer, these rows want 268 logical pixels
#: at the larger of the two font metrics this machine produces (see HEIGHT),
#: against the 280 the conversation gets. Make either bubble much taller and
#: copy, read and stop stop being mapped at all -- which is what the
#: environment-marked test in tests/ui/test_panel_redesign.py checks, and what
#: it catches when either number is raised.
USER_BUBBLE = (320, 48)
USER_TEXT = (296, 32)
GRANDPA_BUBBLE = (380, 100)
GRANDPA_TEXT = (356, 80)

#: The input's border. An Entry with no border and the same colour as the pane
#: above it does not read as something you type in -- which is exactly what was
#: reported.
BORDER = "#34373d"
#: The border when the input has focus, and the accent on the heard row.
ACCENT = "#5a9cf8"

#: What each pane says when it has nothing to say. An element that is invisible
#: until it has content has to be *asked* about; one that explains itself does
#: not. These are the fix for the audit above.
PLACEHOLDER_ENTRY = "Message Grandpa..."
EMPTY_REPLY = (
    "Replies appear here.\n\n"
    "Hold {key} anywhere to talk, or type below and press Enter."
)
EMPTY_HEARD = "nothing heard yet"

#: How many earlier exchanges the strip above the current one shows. Two, so
#: with the current exchange the panel holds three -- enough for the voice-only
#: case, where three questions can be asked before the panel is ever opened.
EARLIER_ROWS = 2

#: The separator between what was asked and what came back, on one line.
EARLIER_JOIN = "  ->  "

#: How long an earlier line may be before it is cut. A compact reminder, not a
#: second copy of the exchange.
EARLIER_LIMIT = 58

#: Captions. The reported problem behind item 2: when a transcript is wrong,
#: "did it mishear me or misunderstand me" needs different fixes from the user,
#: and two unlabelled blocks of text in one pane cannot be told apart. The
#: bubbles carry that distinction by side and colour now, so the captions are
#: shorter -- but they stay, because colour alone is not a label.
CAPTION_HEARD = "you"
CAPTION_REPLY = "Grandpa"

#: The product's own name and what it is, in the header.
PRODUCT_NAME = "GRANDPA"
PRODUCT_TAGLINE = "Personal AI Assistant"

#: The empty conversation. A faint ring and two lines, rather than a dark
#: rectangle the size of the window.
EMPTY_TITLE = "No messages yet"
EMPTY_BODY = "Hold {key} to talk, or type below"

#: The thinking pill.
THINKING_TEXT = "Thinking \u00b7 \u00b7 \u00b7"

#: Under a user message. The message was submitted and returned, so this is
#: known rather than assumed.
SENT_TEXT = "sent"

#: The action row's buttons. "stop" stops *speaking* -- interrupt_speech()
#: already exists. Stopping generation is a different thing and is not here:
#: bridge.send() is one blocking call with no cancellation.
ACTION_COPY = "copy"
ACTION_READ = "read"
ACTION_STOP = "stop"

#: The input row. Only what is true: Enter sends, and the entry is single-line,
#: so there is no "Shift + Enter for a new line" to promise.
INPUT_HINT = "Enter to send  \u00b7  {hold} to talk"
SEND_GLYPH = "\u27a4"
CLOSE_GLYPH = "\u2715"

#: Type scale. Three sizes only -- state, body, meta -- so the window has a
#: readable hierarchy without becoming a design exercise.
FONT_STATE = ("Segoe UI Semibold", 11)
FONT_BODY = ("Segoe UI", 10)
FONT_META = ("Segoe UI", 8)
#: The header's two lines, and the small type on timestamps and buttons.
FONT_TITLE = ("Segoe UI Semibold", 14)
FONT_TAGLINE = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)

#: The level meter. Bars are created once and only their coordinates change, so
#: a meter updating ten times a second never allocates a canvas item.
METER_HEIGHT = 22
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
    #: Called when the heard row is clicked, to load the transcript into
    #: the box for correcting. See _edit_transcript.
    on_edit_transcript: Any = None
    #: Called with ``(dx, dy)`` while the header is dragged. Given one, the
    #: panel does NOT move itself: the controller owns where both windows are,
    #: because the orb has to come along. Without it the panel moves alone, as
    #: it did before the two became one component.
    on_drag: Any = None
    #: Called when "read" is clicked: say the last reply again. Calls the
    #: controller's existing speech path; the view owns no speaker.
    on_read: Any = None
    #: Called when "stop" is clicked. Stops SPEAKING -- interrupt_speech()
    #: already exists. It does not stop generation: bridge.send() is one
    #: blocking call with no cancellation, which is a separate piece of work.
    on_stop_speaking: Any = None
    root: Any = field(default=None, init=False)
    _widgets: dict[str, Any] = field(default_factory=dict, init=False)
    _drag_origin: tuple[int, int] = field(default=(0, 0), init=False)
    _swallowed_press: bool = field(default=False, init=False)
    _meter_bars: list[Any] = field(default_factory=list, init=False)
    #: True while the entry is showing its placeholder rather than
    #: something the user typed. Submitting must not send it.
    _placeholder_active: bool = field(default=False, init=False)
    #: The last transcript, so clicking the heard row can offer it for
    #: correction without the view having to ask the controller.
    _last_transcript: str = field(default="", init=False)
    #: The earlier-exchange labels, created once so the layout does not jump.
    _earlier_rows: list[Any] = field(default_factory=list, init=False)
    #: The last reply, so copy and read have something to act on without the
    #: view asking the controller for it again.
    _last_reply: str = field(default="", init=False)
    #: Whether an exchange has happened. Decides between the bubbles and the
    #: empty state, so neither is ever shown with nothing in it.
    _has_exchange: bool = field(default=False, init=False)
    #: The canvas id of the header's logo ring, so the state recolours that one
    #: item rather than everything that happens to be on the canvas.
    _logo_ring: Any = field(default=None, init=False)
    #: Whether the thinking pill is wanted. Kept, because the pill shares the
    #: action row's slot and rebuilding the rows has to know which of the two
    #: belongs there.
    _thinking: bool = field(default=False, init=False)
    #: True while the panel is withdrawn -- collapsed to the orb. The widgets
    #: still exist and still hold the last exchange.
    hidden: bool = field(default=False, init=False)

    def _tk(self) -> Any:
        if self.tkinter_module is None:
            import tkinter

            self.tkinter_module = tkinter
        return self.tkinter_module

    # --- drawing -------------------------------------------------------------

    @staticmethod
    def rounded_points(
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float,
        *,
        factor: float = SPLINE_RADIUS_FACTOR,
    ) -> list[float]:
        """A rounded rectangle as polygon points, for ``smooth=True``.

        Pure, so the geometry is testable without a canvas. Each corner is
        three points; the spline through them is what rounds it. ``tk.Frame``
        has no radius option of any kind -- measured -- so this is the only way
        to get a rounded shape out of this toolkit.

        *radius* is the radius you want to **see**. It is multiplied by
        :data:`SPLINE_RADIUS_FACTOR` first, because the spline draws a corner
        much tighter than its control points describe, and then clamped to the
        box -- so an over-corrected radius rounds a small shape completely
        rather than inverting it.
        """
        radius = max(0.0, float(radius)) * float(factor)
        radius = max(0.0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        return [
            x0 + radius, y0,
            x1 - radius, y0,
            x1, y0,
            x1, y0 + radius,
            x1, y1 - radius,
            x1, y1,
            x1 - radius, y1,
            x0 + radius, y1,
            x0, y1,
            x0, y1 - radius,
            x0, y0 + radius,
            x0, y0,
        ]

    def _rounded(
        self,
        canvas: Any,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float,
        *,
        fill: str,
        outline: str,
    ) -> Any:
        """Draw a rounded rectangle. Returns the item, or None if it could not."""
        try:
            return canvas.create_polygon(
                *self.rounded_points(x0, y0, x1, y1, radius),
                smooth=True,
                splinesteps=12,
                fill=fill,
                outline=outline,
            )
        except Exception:  # noqa: BLE001 - a closed window must not raise
            return None

    def _show_conversation(self) -> None:
        """Show the bubbles, or the empty state, but never both or neither.

        The window's standing rule is that nothing is present while saying
        nothing. An exchange that has not happened is not an empty bubble; it
        is the empty state, and the bubbles are unpacked until there is
        something in them.
        """
        rows = (
            "user_row", "user_meta", "grandpa_row", "grandpa_meta", "actions",
        )
        try:
            if self._has_exchange:
                self._widgets["empty"].pack_forget()
                for name in rows:
                    widget = self._widgets.get(name)
                    if widget is not None:
                        widget.pack(fill="x", pady=(0, 4))
                # The pill shares the action row's slot, so re-showing the
                # rows must not leave both.
                self.set_thinking(self._thinking)
            else:
                for name in rows:
                    widget = self._widgets.get(name)
                    if widget is not None:
                        widget.pack_forget()
                self._widgets["empty"].pack(fill="both", expand=True)
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def set_thinking(self, thinking: bool) -> None:
        """Show or hide the thinking pill, in the action row's slot.

        **The pill takes the action row's place rather than sitting below it.**
        Measured on the real packer: the conversation's rows fill all but a
        dozen pixels of it, so a pill packed as a seventh row was mapped at a
        height of one -- present, invisible, and invisible exactly when the
        user is waiting and most wants to see it.

        Sharing the slot costs nothing and is the better reading anyway. Both
        are 22 pixels tall, so nothing shifts, and while a reply is being
        worked on, controls for the *previous* reply are the least useful
        thing on screen.
        """
        self._thinking = bool(thinking)
        pill = self._widgets.get("thinking")
        actions = self._widgets.get("actions")
        if pill is None:
            return
        try:
            if thinking and self._has_exchange:
                if actions is not None:
                    actions.pack_forget()
                pill.pack(anchor="w", pady=(0, 4))
            else:
                pill.pack_forget()
                if actions is not None and self._has_exchange:
                    actions.pack(fill="x", pady=(0, 4))
        except Exception:  # noqa: BLE001
            pass

    # --- the action row ------------------------------------------------------

    def _copy_reply(self, _event: Any = None) -> None:
        """Put the last reply on the clipboard.

        **Why this clipboard path is not gated when the catalogued ones are.**
        ``action_layer`` has clipboard actions behind consent, and they are
        gated because a *model* or a *voice command* drives them -- something
        the user did not do with their own hands. This is a button on the
        user's own screen, clicked by the user, and it is already possible
        today: the reply is a selectable Text widget, so Ctrl+C does the same
        thing. Gate what the model does, not what the person does.
        """
        if self.root is None or not self._last_reply:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._last_reply)
        except Exception:  # noqa: BLE001 - a clipboard refusal is not fatal
            pass

    def _read_reply(self, _event: Any = None) -> None:
        """Say the last reply again, through the controller's own speech path."""
        if callable(self.on_read):
            try:
                self.on_read()
            except Exception:  # noqa: BLE001 - a click must not kill the UI
                pass

    def _stop_speaking(self, _event: Any = None) -> None:
        """Stop speaking. Not stop generating -- see on_stop_speaking."""
        if callable(self.on_stop_speaking):
            try:
                self.on_stop_speaking()
            except Exception:  # noqa: BLE001
                pass

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

        # The panel's own rounded border, drawn on a Canvas that sits under
        # everything else. tk.Frame has no radius option -- measured -- and the
        # window itself is a hard rectangle, also measured, so this is a
        # rounded border *inside* a square window rather than a rounded
        # window. The alternative is SetWindowRgn or a layered panel, which is
        # a second Win32 mechanism and its own decision.
        frame = tk.Canvas(
            root, bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        frame.place(x=0, y=0, relwidth=1, relheight=1)
        self._widgets["frame"] = frame
        self._rounded(
            frame, 1, 1, WIDTH - 2, HEIGHT - 2, PANEL_RADIUS,
            fill="", outline=BORDER,
        )

        body = tk.Frame(root, bg=BACKGROUND)
        body.pack(fill="both", expand=True, padx=3, pady=3)

        # --- header, which is also the drag handle --------------------------
        header = tk.Frame(body, bg=BACKGROUND, height=HEADER_HEIGHT)
        header.pack(fill="x", padx=10, pady=(6, 0))
        header.pack_propagate(False)
        # Under its name in DRAG_HANDLE_WIDGETS, so that tuple is the handle
        # rather than a description of it.
        self._widgets["header"] = header

        # The logo ring. An oval rather than the orb's own renderer: at 28
        # pixels a three-pixel blue ring is the same picture, and reusing
        # orb_image here would pull the image pipeline into the panel for no
        # visible gain.
        logo = tk.Canvas(
            header, width=28, height=28, bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        logo.pack(side="left", pady=(8, 0))
        # Loading, not recording: the panel opens while the model is still
        # coming up, and a ring that starts blue says it is listening.
        self._logo_ring = logo.create_oval(
            2, 2, 26, 26, outline=STATE_COLOURS["loading"], width=3
        )
        self._widgets["logo"] = logo

        titles = tk.Frame(header, bg=BACKGROUND)
        titles.pack(side="left", padx=(10, 0), pady=(8, 0))
        self._widgets["title"] = tk.Label(
            titles, text=PRODUCT_NAME, bg=BACKGROUND, fg=FOREGROUND,
            font=FONT_TITLE, anchor="w",
        )
        self._widgets["title"].pack(fill="x")
        self._widgets["tagline"] = tk.Label(
            titles, text=PRODUCT_TAGLINE, bg=BACKGROUND, fg=MUTED,
            font=FONT_TAGLINE, anchor="w",
        )
        self._widgets["tagline"].pack(fill="x")

        # Close, far right. An affordance for something that already exists --
        # Escape is bound to the same handler -- rather than new behaviour.
        # There is deliberately no minimise or maximise: collapsing to the orb
        # is already the gesture and it is one click on the orb, and the
        # panel's extended style is WS_EX_TOOLWINDOW, so it has no taskbar
        # button to minimise to.
        self._widgets["close"] = tk.Label(
            header, text=CLOSE_GLYPH, bg=BACKGROUND, fg=MUTED,
            font=FONT_STATE, padx=6,
        )
        self._widgets["close"].pack(side="right", pady=(8, 0))
        self._widgets["close"].bind("<Button-1>", lambda _event: self._close())

        # The state, as a dot in the state colour and the state's own word.
        status_block = tk.Frame(header, bg=BACKGROUND)
        status_block.pack(side="right", padx=(0, 10), pady=(8, 0))
        self._widgets["dot"] = tk.Label(
            status_block, text="\u25cf", bg=BACKGROUND,
            fg=STATE_COLOURS["loading"],
        )
        self._widgets["dot"].pack(side="left")
        self._widgets["state"] = tk.Label(
            status_block, text="Loading model...", bg=BACKGROUND, fg=FOREGROUND,
            anchor="w", font=FONT_STATE,
        )
        self._widgets["state"].pack(side="left", padx=(6, 0))

        # Spoken replies, on or off. A label rather than a Checkbutton so it
        # cannot be tabbed into -- the window must never acquire focus except
        # from a deliberate click.
        self._widgets["speak"] = tk.Label(
            header, text=self._speak_label(True), bg=SURFACE, fg=MUTED,
            font=FONT_META, padx=6, pady=2,
        )
        self._widgets["speak"].pack(side="right", padx=(0, 10), pady=(8, 0))
        self._widgets["speak"].bind("<Button-1>", self._toggle_speech)

        self._widgets["header_divider"] = tk.Frame(body, bg=DIVIDER, height=1)
        self._widgets["header_divider"].pack(fill="x", pady=(6, 0))

        # The level meter sits directly under the header, because while the key
        # is held it is the only thing the user is looking at. The design does
        # not show it; it stays because it is the only answer to "is it hearing
        # me" and it was built for that.
        meter = tk.Canvas(
            body, height=METER_HEIGHT, bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        meter.pack(fill="x", padx=14, pady=(4, 0))
        self._widgets["meter"] = meter
        self._meter_bars = [
            meter.create_rectangle(0, 0, 0, 0, fill=DIVIDER, width=0)
            for _ in range(METER_BARS)
        ]
        self.set_levels(())

        # --- the conversation ----------------------------------------------
        convo = tk.Frame(body, bg=BACKGROUND)
        self._widgets["convo"] = convo
        # Packed at the very end of show(), after the input block has claimed
        # the bottom. The packer hands out space in pack order, so a frame
        # that expands must come last or it takes everything and the rows
        # below it are pushed off the window. That is exactly what happened:
        # one long reply pushed the status line past the bottom edge, and the
        # status line is where errors are reported.

        # The strip that holds the earlier exchanges. A Frame only: its rows
        # are built when there is something to put in them, because a label
        # constructed with no text is a widget that exists while saying
        # nothing, which is the fault this window was audited for.
        self._widgets["earlier"] = tk.Frame(convo, bg=BACKGROUND)
        self._earlier_rows = []

        # What was said, on the right in blue.
        user_row = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["user_row"] = user_row
        self._widgets["heard_bar"] = tk.Frame(user_row, bg=DIVIDER, width=3)
        self._widgets["heard_bar"].pack(side="right", fill="y", padx=(6, 0))
        user_bubble = tk.Canvas(
            user_row, width=USER_BUBBLE[0], height=USER_BUBBLE[1], bg=BACKGROUND,
            highlightthickness=0, bd=0,
        )
        user_bubble.pack(side="right")
        self._widgets["user_bubble"] = user_bubble
        self._rounded(
            user_bubble, 0, 0, USER_BUBBLE[0] - 1, USER_BUBBLE[1] - 1,
            BUBBLE_RADIUS, fill=BUBBLE_USER, outline="",
        )
        # Constructed with the empty-state text rather than "", so it occupies
        # its space from the first frame and the layout does not jump.
        self._widgets["transcript"] = tk.Label(
            user_bubble, text=EMPTY_HEARD, bg=BUBBLE_USER, fg=MUTED, anchor="nw",
            justify="left", wraplength=USER_TEXT[0], font=FONT_BODY,
        )
        user_bubble.create_window(
            12, 8, window=self._widgets["transcript"], anchor="nw",
            width=USER_TEXT[0], height=USER_TEXT[1],
        )
        # Clicking it loads it into the box below to be corrected and resent.
        for widget in (user_row, user_bubble, self._widgets["transcript"]):
            widget.bind("<Button-1>", self._edit_transcript)

        user_meta = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["user_meta"] = user_meta
        self._widgets["heard_caption"] = tk.Label(
            user_meta, text=CAPTION_HEARD, bg=BACKGROUND, fg=MUTED,
            font=FONT_SMALL, anchor="e",
        )
        self._widgets["heard_caption"].pack(side="right")

        # What came back, on the left in grey.
        grandpa_row = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["grandpa_row"] = grandpa_row
        grandpa_bubble = tk.Canvas(
            grandpa_row, width=GRANDPA_BUBBLE[0], height=GRANDPA_BUBBLE[1],
            bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        grandpa_bubble.pack(side="left")
        self._widgets["grandpa_bubble"] = grandpa_bubble
        self._rounded(
            grandpa_bubble, 0, 0, GRANDPA_BUBBLE[0] - 1, GRANDPA_BUBBLE[1] - 1,
            BUBBLE_RADIUS, fill=BUBBLE_GRANDPA, outline="",
        )
        # Text, not Label: a reply has to be selectable so it can be copied by
        # hand, which is also the precedent the copy button rests on.
        reply = tk.Text(
            grandpa_bubble, bg=BUBBLE_GRANDPA, fg=FOREGROUND, relief="flat",
            wrap="word", insertbackground=FOREGROUND, font=FONT_BODY,
            padx=0, pady=0, highlightthickness=0, bd=0,
        )
        grandpa_bubble.create_window(
            12, 10, window=reply, anchor="nw",
            width=GRANDPA_TEXT[0], height=GRANDPA_TEXT[1],
        )
        # Read-only but still selectable. "disabled" would block selection too.
        reply.bind("<Key>", lambda _event: "break")
        self._widgets["reply"] = reply
        self._show_empty_reply()

        grandpa_meta = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["grandpa_meta"] = grandpa_meta
        self._widgets["reply_caption"] = tk.Label(
            grandpa_meta, text=CAPTION_REPLY, bg=BACKGROUND, fg=MUTED,
            font=FONT_SMALL, anchor="w",
        )
        self._widgets["reply_caption"].pack(side="left")

        # The action row. copy, read and stop -- no redo, because re-sending a
        # message is new behaviour, and stop here means stop *speaking*.
        actions = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["actions"] = actions
        for name, label, handler in (
            ("copy", ACTION_COPY, self._copy_reply),
            ("read", ACTION_READ, self._read_reply),
            ("stop", ACTION_STOP, self._stop_speaking),
        ):
            # A Canvas, so ACTION_WIDTH and ACTION_HEIGHT are pixels and not a
            # Label's character count, and so the outline can be rounded the
            # same way the bubbles are.
            button = tk.Canvas(
                actions, width=ACTION_WIDTH, height=ACTION_HEIGHT,
                bg=BACKGROUND, highlightthickness=0, bd=0, takefocus=False,
            )
            button.pack(side="left", padx=(0, 6))
            self._rounded(
                button, 0, 0, ACTION_WIDTH - 1, ACTION_HEIGHT - 1,
                ACTION_HEIGHT / 2.0, fill=BACKGROUND, outline=BORDER,
            )
            caption = tk.Label(
                button, text=label, bg=BACKGROUND, fg=MUTED, font=FONT_SMALL,
                takefocus=False,
            )
            button.create_window(
                ACTION_WIDTH / 2, ACTION_HEIGHT / 2, window=caption,
            )
            # Both, because the caption covers the middle of the canvas and a
            # click that lands on the word must count as a click on the button.
            button.bind("<Button-1>", handler)
            caption.bind("<Button-1>", handler)
            self._widgets[f"action_{name}"] = button
            self._widgets[f"action_{name}_label"] = caption

        # The thinking pill: shown only while there is thinking to report.
        pill = tk.Frame(convo, bg=SURFACE)
        self._widgets["thinking"] = pill
        self._widgets["thinking_dot"] = tk.Label(
            pill, text="\u25cf", bg=SURFACE, fg=STATE_COLOURS["thinking"],
            font=FONT_SMALL, padx=(6),
        )
        self._widgets["thinking_dot"].pack(side="left")
        self._widgets["thinking_text"] = tk.Label(
            pill, text=THINKING_TEXT, bg=SURFACE, fg=MUTED, font=FONT_SMALL,
            padx=6, pady=3,
        )
        self._widgets["thinking_text"].pack(side="left")

        # The empty conversation. A faint ring and two lines, rather than a
        # dark rectangle the size of the window.
        empty = tk.Frame(convo, bg=BACKGROUND)
        self._widgets["empty"] = empty
        ring = tk.Canvas(
            empty, width=56, height=56, bg=BACKGROUND, highlightthickness=0, bd=0,
        )
        ring.pack(pady=(18, 8))
        ring.create_oval(3, 3, 53, 53, outline=DIVIDER, width=2)
        self._widgets["empty_ring"] = ring
        self._widgets["empty_title"] = tk.Label(
            empty, text=EMPTY_TITLE, bg=BACKGROUND, fg=FOREGROUND, font=FONT_BODY,
        )
        self._widgets["empty_title"].pack()
        self._widgets["empty_body"] = tk.Label(
            empty, text=EMPTY_BODY.format(key=describe_hold_key(self.hold_key)),
            bg=BACKGROUND, fg=MUTED, font=FONT_META,
        )
        self._widgets["empty_body"].pack(pady=(2, 0))

        self._show_conversation()

        # --- the input ------------------------------------------------------
        self._widgets["input_divider"] = tk.Frame(body, bg=DIVIDER, height=1)

        input_row = tk.Frame(body, bg=BACKGROUND)
        self._widgets["input_row"] = input_row

        # Send, right of the field. The same on_submit Enter already calls, so
        # nothing can happen through it that could not happen before.
        self._widgets["send"] = tk.Label(
            input_row, text=SEND_GLYPH, bg=STATE_COLOURS["recording"],
            fg=FOREGROUND, font=FONT_STATE, width=2, height=1, takefocus=False,
        )
        self._widgets["send"].pack(side="right", padx=(8, 0))
        self._widgets["send"].bind("<Button-1>", self._submit)

        field = tk.Canvas(
            input_row, height=INPUT_BUTTON, bg=BACKGROUND,
            highlightthickness=0, bd=0,
        )
        field.pack(side="left", fill="x", expand=True)
        self._widgets["field"] = field

        entry = tk.Entry(
            field, bg=SURFACE, fg=MUTED, relief="flat",
            insertbackground=FOREGROUND, font=FONT_BODY,
            # A visible edge, so it reads as an input. With
            # highlightthickness=0 and the same colour as the pane above, it
            # was an anonymous dark strip -- the reported fault.
            highlightthickness=1, highlightbackground=ACCENT,
            highlightcolor=ACCENT, bd=0,
            # Keeps the entry out of the tab order, so the window cannot
            # acquire focus by being tabbed into from elsewhere.
            takefocus=False,
        )
        field.create_window(
            0, 0, window=entry, anchor="nw", width=WIDTH - 90, height=INPUT_BUTTON,
        )
        entry.bind("<Return>", self._submit)
        # A placeholder, because nothing else said the box could be typed in.
        # Focus-driven rather than key-driven: the entry only takes focus from a
        # real click (takefocus=False), and a <Key> binding here would sit
        # alongside the hold-key swallow bindings for no benefit.
        entry.bind("<FocusIn>", self._hide_placeholder)
        entry.bind("<FocusOut>", self._show_placeholder)
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
        self._show_placeholder()

        # Only what is true. The entry is single-line, so there is no
        # "Shift + Enter for a new line" to promise.
        self._widgets["hold_hint"] = tk.Label(
            body, text=self.input_hint_text(),
            bg=BACKGROUND, fg=MUTED, font=FONT_META, anchor="w",
        )
        # Bottom-up, so the order on screen is divider, box, hint, status.

        # Constructed with text rather than "". It was only ever non-blank
        # because controller.start() refreshes it immediately, which is the
        # controller's good manners rather than this widget's correctness.
        self._widgets["status"] = tk.Label(
            body, text="starting...", bg=BACKGROUND, fg=MUTED, anchor="w",
            wraplength=WIDTH - 32, justify="left", font=FONT_META,
        )
        self._widgets["status"].pack(side="bottom", fill="x", padx=14, pady=(2, 8))
        self._widgets["hold_hint"].pack(
            side="bottom", fill="x", padx=14, pady=(6, 0)
        )
        self._widgets["input_row"].pack(
            side="bottom", fill="x", padx=14, pady=(8, 0)
        )
        self._widgets["input_divider"].pack(side="bottom", fill="x", pady=(6, 0))
        # And now the conversation, into whatever is left.
        convo.pack(fill="both", expand=True, padx=14, pady=(4, 0))

        # Dragging, because overrideredirect removed the title bar. Bound to
        # the header and the two things in it that are not interactive, and to
        # nothing else: not the entry, not the speech toggle, not the user
        # bubble (which is clickable for correcting), not the action buttons,
        # not the status line. DRAG_HANDLE_WIDGETS names them so a test can pin
        # the list.
        for name in DRAG_HANDLE_WIDGETS:
            widget = self._widgets[name]
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
        logo = self._widgets.get("logo")
        if logo is not None and self._logo_ring is not None:
            # The header's ring carries the state too, so the panel reads as
            # the same object as the orb beside it. By the ring's own id, not
            # by everything on the canvas.
            try:
                logo.itemconfigure(
                    self._logo_ring, outline=STATE_COLOURS.get(state, FOREGROUND)
                )
            except Exception:  # noqa: BLE001
                pass
        # Thinking and transcribing are both indeterminate work the user is
        # waiting on, which is what the pill says.
        self.set_thinking(str(state) in {"thinking", "transcribing"})

    def set_status_line(self, text: str) -> None:
        widget = self._widgets.get("status")
        if widget is not None:
            widget.configure(text=text)

    @staticmethod
    def earlier_line(heard: str, reply: str) -> str:
        """One exchange on one line, cut to length. Pure, so it is testable."""
        line = f"{heard}{EARLIER_JOIN}{reply}".replace("\n", " ").strip()
        if len(line) > EARLIER_LIMIT:
            line = line[: EARLIER_LIMIT - 1].rstrip() + "\u2026"
        return line

    def set_earlier(self, rows: Any) -> None:
        """Show up to EARLIER_ROWS previous exchanges, newest first.

        Rows are built on first use with the text they will show, never blank
        and never packed empty. The strip itself is absent when there is
        nothing before the current exchange.
        """
        strip = self._widgets.get("earlier")
        if strip is None:
            return
        kept = [
            self.earlier_line(str(heard or ""), str(reply or ""))
            for heard, reply in tuple(rows or ())[:EARLIER_ROWS]
        ]
        tk = self._tk()
        try:
            while len(self._earlier_rows) < len(kept):
                row = tk.Label(
                    strip, text=kept[len(self._earlier_rows)], bg=BACKGROUND,
                    fg=MUTED, anchor="w", justify="left", font=FONT_META,
                )
                self._earlier_rows.append(row)
            for index, row in enumerate(self._earlier_rows):
                if index < len(kept):
                    row.configure(text=kept[index])
                    row.pack(fill="x")
                else:
                    row.pack_forget()
            if kept:
                strip.pack(
                    fill="x", pady=(0, 4), before=self._widgets["user_row"],
                )
            else:
                strip.pack_forget()
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def set_transcript(self, text: str) -> None:
        """Show what was heard, in its own row, visibly not the reply.

        An empty transcript restores the empty state rather than blanking the
        row: a zero-height label made the layout jump, and a blank strip said
        nothing about what the row was.
        """
        self._last_transcript = text or ""
        widget = self._widgets.get("transcript")
        if widget is not None:
            try:
                if text:
                    widget.configure(text=f"“{text}”", fg=FOREGROUND)
                else:
                    widget.configure(text=EMPTY_HEARD, fg=MUTED)
            except Exception:  # noqa: BLE001
                pass
        # The accent edge lights up only when there is something heard, so the
        # row reads as live rather than as decoration.
        bar = self._widgets.get("heard_bar")
        if bar is not None:
            try:
                bar.configure(bg=ACCENT if text else DIVIDER)
            except Exception:  # noqa: BLE001
                pass
        caption = self._widgets.get("heard_caption")
        if caption is not None:
            try:
                caption.configure(text=self.user_meta_text(text))
            except Exception:  # noqa: BLE001
                pass
        if text:
            self._has_exchange = True
            self._show_conversation()

    def user_meta_text(self, heard: str, when: str | None = None) -> str:
        """The line under a user message: time, sent, and how to correct it.

        **This adds a field the panel did not have.** The time is knowable at
        the moment the message is shown, so it needs no new capability and no
        new plumbing -- but it is data rather than drawing, and saying so is
        the point.

        "sent" is not a guess either: ``submit`` was called and returned.
        """
        if not heard:
            return CAPTION_HEARD
        stamp = when if when is not None else self._now()
        return f"{CAPTION_HEARD}  \u00b7  {stamp}  \u00b7  {SENT_TEXT}  \u00b7  click to correct"

    def reply_meta_text(self, when: str | None = None) -> str:
        """The line under a Grandpa message: who said it and when."""
        stamp = when if when is not None else self._now()
        return f"{CAPTION_REPLY}  \u00b7  {stamp}"

    @staticmethod
    def _now() -> str:
        """The wall clock, as hh:mm. Its own method so a test can replace it."""
        import time

        return time.strftime("%H:%M")

    def set_reply(self, text: str) -> None:
        """Show the reply. An empty one restores the empty state."""
        widget = self._widgets.get("reply")
        if widget is None:
            return
        self._last_reply = text or ""
        if not text:
            self._show_empty_reply()
            return
        # The first reply is what turns the empty state into a conversation.
        self._has_exchange = True
        self._show_conversation()
        caption = self._widgets.get("reply_caption")
        if caption is not None:
            try:
                caption.configure(text=self.reply_meta_text())
            except Exception:  # noqa: BLE001
                pass
        try:
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(fg=FOREGROUND)
        except Exception:  # noqa: BLE001
            pass

    def clear_entry(self) -> None:
        """Empty the box after submitting, and put the placeholder back."""
        widget = self._widgets.get("entry")
        if widget is not None:
            try:
                widget.delete(0, "end")
            except Exception:  # noqa: BLE001
                pass
        self._placeholder_active = False
        self._show_placeholder()

    def position(self) -> tuple[int, int]:
        if self.root is None:
            return (0, 0)
        try:
            return int(self.root.winfo_x()), int(self.root.winfo_y())
        except Exception:
            return (0, 0)

    def hide(self) -> bool:
        """Take the panel off screen without destroying it.

        Destroying it would lose the last exchange, which is the one thing a
        collapsed orb cannot show, and rebuilding it would take the foreground
        again. So the widgets and their contents stay exactly as they are.
        """
        if self.root is None:
            return False
        try:
            self.root.withdraw()
        except Exception:
            return False
        self.hidden = True
        return True

    def unhide(self) -> bool:
        """Put it back, with everything it was showing still in it.

        The only tk call that re-maps a withdrawn window. Measured not to take
        the foreground for a borderless topmost window -- see REMAP_CALLS -- and
        used here and nowhere else.
        """
        if self.root is None:
            return False
        try:
            self.root.deiconify()
        except Exception:
            return False
        self.hidden = False
        return True

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

    # --- empty states --------------------------------------------------------
    #
    # Every one of these exists because the audit found an element that was
    # invisible or meaningless until something filled it. A pane that explains
    # itself does not have to be asked about.

    def _show_empty_reply(self) -> None:
        """Write the reply pane's empty state, in the muted colour."""
        reply = self._widgets.get("reply")
        if reply is None:
            return
        try:
            reply.delete("1.0", "end")
            reply.insert("1.0", EMPTY_REPLY.format(key=describe_hold_key(self.hold_key)))
            reply.configure(fg=MUTED)
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def _show_placeholder(self, _event: Any = None) -> None:
        """Put the placeholder back, if the box is empty."""
        entry = self._widgets.get("entry")
        if entry is None or self._placeholder_active:
            return
        try:
            if entry.get():
                return
            entry.insert(0, PLACEHOLDER_ENTRY)
            entry.configure(fg=MUTED)
            self._placeholder_active = True
        except Exception:  # noqa: BLE001
            pass

    def _hide_placeholder(self, _event: Any = None) -> None:
        """Take the placeholder out, so it is never mistaken for input."""
        entry = self._widgets.get("entry")
        if entry is None or not self._placeholder_active:
            return
        try:
            entry.delete(0, "end")
            entry.configure(fg=FOREGROUND)
            self._placeholder_active = False
        except Exception:  # noqa: BLE001
            pass

    # --- correcting a transcript ---------------------------------------------

    def set_entry_text(self, text: str) -> None:
        """Put *text* in the box, ready to be edited and sent.

        Used to correct a mis-heard transcript: the alternative is saying the
        whole sentence again, and one wrong word does not deserve that.
        """
        entry = self._widgets.get("entry")
        if entry is None:
            return
        try:
            self._placeholder_active = False
            entry.delete(0, "end")
            entry.insert(0, text)
            entry.configure(fg=FOREGROUND)
            # No focus_set: the window must never take focus on its own. The
            # text is waiting; the user clicks when they want it.
            entry.icursor("end")
        except Exception:  # noqa: BLE001
            pass

    def _edit_transcript(self, _event: Any = None) -> None:
        """Clicking the heard row offers it for correction."""
        if not self._last_transcript:
            return
        if callable(self.on_edit_transcript):
            try:
                self.on_edit_transcript(self._last_transcript)
                return
            except Exception:  # noqa: BLE001 - a click must not kill the UI
                pass
        self.set_entry_text(self._last_transcript)

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
        """What the window tells the user to hold.

        Derived from :attr:`hold_key`, never written out. The window said
        "hold SPACE" for a whole release after the default became f9, and this
        phrase is the one place a user actually reads the key name. It moved
        from a header chip to the line under the input when the panel was
        redesigned; it is still produced here and nowhere else.
        """
        return f"hold {describe_hold_key(self.hold_key)}"

    def input_hint_text(self) -> str:
        """The line under the input. Only what is true.

        The entry is single-line, so there is no "Shift + Enter for a new
        line" to promise -- the design asked for that line and it would have
        been a lie until multi-line input exists.
        """
        return INPUT_HINT.format(hold=self.hold_hint_text())

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
        if self._placeholder_active:
            # The box looks full but nothing was typed. Sending the placeholder
            # would ask the assistant to answer our own prompt.
            return "break"
        text = entry.get() if entry is not None else ""
        if callable(self.on_submit):
            self.on_submit(text)
        return "break"

    def _drag_start(self, event: Any) -> None:
        self._drag_origin = (int(event.x), int(event.y))

    def _drag_move(self, event: Any) -> None:
        target = (
            int(event.x_root) - self._drag_origin[0],
            int(event.y_root) - self._drag_origin[1],
        )
        if callable(self.on_drag):
            here = self.position()
            try:
                self.on_drag(target[0] - here[0], target[1] - here[1])
                return
            except Exception:  # noqa: BLE001 - a drag must not kill the UI
                pass
        self.move_to(*target)

    def move_to(self, x: int, y: int) -> bool:
        """Put the panel at a screen position.

        Used by the drag, and by expanding from the orb -- which places the
        panel while it is still withdrawn, so it never appears at its old spot
        first and then jump.
        """
        if self.root is None:
            return False
        try:
            self.root.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            return False
        return True

    def _close(self) -> None:
        if callable(self.on_close):
            self.on_close()
        else:
            self.close()


__all__ = [
    "CREATION_TAKES_FOREGROUND",
    "DRAG_HANDLE_WIDGETS",
    "EARLIER_JOIN",
    "EARLIER_LIMIT",
    "EARLIER_ROWS",
    "FOCUS_STEALING_CALLS",
    "KEY_SYMS",
    "REMAP_CALLS",
    "STATE_COLOURS",
    "TkBubbleView",
]
