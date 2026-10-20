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

#: 420x440, down from 520x512.
#:
#: **This moves the flip again.** The panel fits on the orb's right while
#: ``orb_x + ORB_SIZE + ANCHOR_GAP + WIDTH <= work_area_right``, so on this
#: 1536-wide work area the threshold goes from ``orb_x <= 956`` at 520 wide to
#: ``orb_x <= 1056`` at 420 -- a hundred pixels further right before the panel
#: has to flip to the other side. ``anchor_panel_to_orb`` and ``_panel_fits``
#: both take the size as a parameter and the command passes these constants,
#: so they follow; the environment-marked corner test is what proves they do.
#:
#: The height came down from 512 only because the conversation scrolls now.
#: 512 was chosen to fit one exchange plus its action row at the larger of the
#: two font metrics this machine produces, with twelve pixels to spare. A
#: scrolling list has no such requirement: it is allowed to be taller than the
#: window, because being taller than the window is what scrolling is for.
WIDTH = 420
HEIGHT = 440

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
#:
#: 44, down from 68. The 68 was a 28-pixel logo ring beside a title stacked
#: over a tagline; the ring is gone -- the orb is on screen beside this window
#: and two rings is one too many -- and the tagline went with it, because the
#: second line of text was the other half of the height.
HEADER_HEIGHT = 44

#: The action row under a Grandpa message: 40x22 outlined buttons at 10pt.
ACTION_WIDTH = 40
ACTION_HEIGHT = 22

#: The input pill: its height, and the gap between its edge and the text.
INPUT_HEIGHT = 34
INPUT_PAD = 12

#: The bubbles, which size themselves to their text now.
#:
#: **This is the fix for a bug that lived thirteen days.** They used to be
#: fixed pixel boxes with the text in a ``create_window`` of a fixed height,
#: and a ``tk.Text`` with no scrollbar shows what fits and says nothing about
#: the rest. Measured with a 600-character reply, every version of this panel
#: since the first one silently dropped lines:
#:
#:     773341b5  the first bubble     showed  7 of 15 lines
#:     e534e758  nothing blank        showed  6 of 11
#:     871da8a1  before the redesign  showed  6 of 11
#:     cc86a0e6  the redesign         showed  5 of 11
#:
#: None of them had a scrollbar, an ellipsis, or any mark that more existed.
#: What is left here is the width of the text and the padding round it; the
#: height is whatever the wrapped text asks for.
BUBBLE_MAX_WIDTH = 286
BUBBLE_PAD = 9

#: How far the two sides are indented from the opposite edge, so a bubble
#: reads as belonging to one speaker rather than filling the panel.
BUBBLE_INSET = 28

#: The scrollback. Bounded rather than unbounded: each exchange is eight
#: widgets, and measured on this machine 200 of them is 1600 widgets and 5.5
#: seconds to build in one go. That build never happens in practice -- history
#: is session-only and rows are appended one at a time, at 44ms each -- but
#: the bound is what keeps a long day from finding the limit.
HISTORY_LIMIT = 200

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

#: Captions. The reported problem behind item 2: when a transcript is wrong,
#: "did it mishear me or misunderstand me" needs different fixes from the user,
#: and two unlabelled blocks of text in one pane cannot be told apart. The
#: bubbles carry that distinction by side and colour now, so the captions are
#: shorter -- but they stay, because colour alone is not a label.
CAPTION_HEARD = "you"
CAPTION_REPLY = "Grandpa"

#: The product's own name, in the header. The tagline that sat under it is
#: gone: it was the second line that made the header 68 pixels tall, and a
#: window the user opened on purpose does not need to introduce itself.
PRODUCT_NAME = "GRANDPA"

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
CLOSE_GLYPH = "\u2715"

#: Type scale. Three sizes only -- state, body, meta -- so the window has a
#: readable hierarchy without becoming a design exercise.
FONT_STATE = ("Segoe UI Semibold", 10)
FONT_BODY = ("Segoe UI", 10)
FONT_META = ("Segoe UI", 8)
#: The header's title and the small type on timestamps and buttons. 12 rather
#: than 14, with the header at 44 rather than 68.
FONT_TITLE = ("Segoe UI Semibold", 12)
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
    #: The canvas item holding the scrolling Frame, and the one holding the
    #: entry: both are resized when their canvas is.
    _scroll_window: Any = field(default=None, init=False)
    _entry_window: Any = field(default=None, init=False)
    _field_shape: Any = field(default=None, init=False)
    #: One entry per exchange on screen, oldest first. Appended to, never
    #: rebuilt: measured, rebuilding 200 rows costs 6.8 seconds against 44ms
    #: to append one.
    _rows: list[Any] = field(default_factory=list, init=False)
    #: The row being filled in -- the user has spoken but the reply has not
    #: arrived. None between exchanges.
    _open_row: Any = field(default=None, init=False)
    #: True while the view is scrolled to the bottom. A new message only drags
    #: the view down when this is true, so arriving text cannot yank a reply
    #: out from under someone reading further up.
    _at_bottom: bool = field(default=True, init=False)
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

    # --- the scrolling conversation ------------------------------------------

    def _on_convo_resized(self, _event: Any = None) -> None:
        """The content changed height, so the scrollable region did."""
        scroll = self._widgets.get("scroll")
        if scroll is None:
            return
        try:
            region = scroll.bbox("all")
            if region:
                scroll.configure(scrollregion=region)
            if self._at_bottom:
                scroll.yview_moveto(1.0)
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def _on_scroll_resized(self, event: Any = None) -> None:
        """Keep the inner frame exactly as wide as the canvas.

        Without this the frame keeps its requested width and the bubbles sit
        against the left edge whatever the panel does.
        """
        scroll = self._widgets.get("scroll")
        if scroll is None or self._scroll_window is None:
            return
        try:
            width = int(getattr(event, "width", 0)) or scroll.winfo_width()
            scroll.itemconfigure(self._scroll_window, width=width)
        except Exception:  # noqa: BLE001
            pass

    def _on_field_resized(self, event: Any = None) -> None:
        """Redraw the input pill at the new width, and restretch the entry."""
        field = self._widgets.get("field")
        if field is None:
            return
        try:
            width = int(getattr(event, "width", 0)) or field.winfo_width()
            if self._field_shape is not None:
                field.delete(self._field_shape)
            self._field_shape = self._rounded(
                field, 1, 1, width - 2, INPUT_HEIGHT - 2, INPUT_HEIGHT / 2.0,
                fill=SURFACE, outline=BORDER,
            )
            if self._field_shape is not None:
                field.tag_lower(self._field_shape)
            if self._entry_window is not None:
                field.itemconfigure(
                    self._entry_window, width=max(20, width - INPUT_PAD * 2)
                )
        except Exception:  # noqa: BLE001
            pass

    def _claim_wheel(self, _event: Any = None) -> None:
        """Take the wheel while the pointer is over the conversation.

        Scoped to entering and leaving rather than bound once for the whole
        interpreter: ``bind_all`` would take the wheel from the orb's window
        too, and they share an interpreter.
        """
        if self.root is None:
            return
        try:
            self.root.bind_all("<MouseWheel>", self._on_wheel)
        except Exception:  # noqa: BLE001
            pass

    def _release_wheel(self, _event: Any = None) -> None:
        if self.root is None:
            return
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:  # noqa: BLE001
            pass

    def _on_wheel(self, event: Any = None) -> str | None:
        scroll = self._widgets.get("scroll")
        if scroll is None:
            return None
        try:
            delta = int(getattr(event, "delta", 0))
            # Windows reports 120 per notch; three lines a notch is the
            # platform convention.
            scroll.yview_scroll(-1 * (delta // 120) * 3, "units")
            self._note_scroll_position()
        except Exception:  # noqa: BLE001
            pass
        return "break"

    def _note_scroll_position(self) -> None:
        """Remember whether the view is parked at the bottom."""
        scroll = self._widgets.get("scroll")
        if scroll is None:
            return
        try:
            _first, last = scroll.yview()
            self._at_bottom = float(last) >= 0.999
        except Exception:  # noqa: BLE001
            self._at_bottom = True

    def _scroll_to_bottom(self) -> None:
        scroll = self._widgets.get("scroll")
        if scroll is None:
            return
        try:
            scroll.update_idletasks()
            region = scroll.bbox("all")
            if region:
                scroll.configure(scrollregion=region)
            scroll.yview_moveto(1.0)
            self._at_bottom = True
        except Exception:  # noqa: BLE001
            pass

    def _bubble(
        self, parent: Any, text: str, *, side: str, colour: str,
        selectable: bool = False,
    ) -> Any:
        """One bubble, as tall as its own text.

        The height is asked of the widget rather than fixed, which is the
        whole of the truncation fix: the text reports the height it needs and
        the canvas is built to it, so there is no box for text to fall out of.

        *selectable* makes it a read-only ``Text`` rather than a ``Label``.
        The reply uses it, and not for neatness: selection is the precedent
        the copy button rests on -- that copying a reply is already possible
        by hand. A copy button whose justification had quietly stopped being
        true would be worse than no button at all.
        """
        tk = self._tk()
        row = tk.Frame(parent, bg=BACKGROUND)
        pad = BUBBLE_INSET
        row.pack(fill="x", pady=(0, 2), padx=(pad, 0) if side == "right" else (0, pad))
        if selectable:
            label = tk.Text(
                row, bg=colour, fg=FOREGROUND, relief="flat", wrap="word",
                insertbackground=FOREGROUND, font=FONT_BODY, padx=0, pady=0,
                highlightthickness=0, bd=0, takefocus=False, height=1,
            )
            label.insert("1.0", text)
            # Read-only but still selectable. "disabled" would block selection
            # as well, which is the thing being preserved.
            label.bind("<Key>", lambda _event: "break")
            # Measured after it is given its real width, below.
            height = 0
        else:
            label = tk.Label(
                row, text=text, bg=colour, fg=FOREGROUND, font=FONT_BODY,
                wraplength=BUBBLE_MAX_WIDTH, justify="left", anchor="nw",
            )
            height = self._needed_height(label) + BUBBLE_PAD * 2
        width = BUBBLE_MAX_WIDTH + BUBBLE_PAD * 2
        bubble = tk.Canvas(
            row, width=width, height=height, bg=BACKGROUND,
            highlightthickness=0, bd=0, takefocus=False,
        )
        bubble.pack(side=side)
        window = bubble.create_window(
            BUBBLE_PAD, BUBBLE_PAD, window=label, anchor="nw",
            width=BUBBLE_MAX_WIDTH,
        )
        if selectable:
            # Now that it is the width it will be drawn at, ask how tall its
            # wrapped text is. Asking before this wrapped it at the Text's
            # default width, which made the bubble thousands of pixels tall
            # -- and still lost no text, so only a size check catches it.
            height = self._text_height(label, text) + BUBBLE_PAD * 2
            try:
                bubble.configure(height=height)
                bubble.itemconfigure(window, height=height - BUBBLE_PAD * 2)
            except Exception:  # noqa: BLE001
                pass
        self._rounded(
            bubble, 0, 0, width - 1, height - 1, BUBBLE_RADIUS,
            fill=colour, outline="",
        )
        return row, bubble, label

    @staticmethod
    def wrapped_lines(text: str, width: float, measure: Any) -> int:
        """How many lines *text* takes when word-wrapped into *width* pixels.

        *measure* is a callable returning the pixel width of a string --
        ``tkinter.font.Font.measure`` in the window, anything in a test. Pure,
        so the arithmetic can be checked without a toolkit, which is the point:
        every geometry-based version of this was untestable and all three were
        wrong.

        Words longer than the line get a line of their own rather than being
        split, which is what ``wrap="word"`` does.
        """
        if not text:
            return 1
        lines = 0
        for paragraph in str(text).split("\n"):
            words = paragraph.split()
            if not words:
                lines += 1
                continue
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and measure(candidate) > width:
                    lines += 1
                    current = word
                else:
                    current = candidate
            lines += 1
        return max(1, lines)

    def _text_height(self, widget: Any, text: str) -> int:
        """How tall the wrapped reply needs to be, in pixels."""
        try:
            import tkinter.font as tkfont

            font = tkfont.Font(font=FONT_BODY)
            lines = self.wrapped_lines(text, BUBBLE_MAX_WIDTH, font.measure)
            spacing = int(font.metrics("linespace"))
        except Exception:  # noqa: BLE001 - no toolkit behind it
            lines, spacing = 1, 17
        try:
            widget.configure(height=lines)
        except Exception:  # noqa: BLE001
            pass
        return lines * spacing

    @staticmethod
    def _needed_height(label: Any) -> int:
        """How tall the wrapped text is, or a sane default off a real toolkit.

        The recorded-call fake has no geometry, so this has to work without
        one -- but the number it returns there decides nothing a test asserts,
        and the real height is what the environment-marked test measures.
        """
        try:
            label.update_idletasks()
            value = int(label.winfo_reqheight())
            if value > 0:
                return value
        except Exception:  # noqa: BLE001
            pass
        return 20

    def _meta(self, parent: Any, text: str, *, side: str) -> Any:
        tk = self._tk()
        label = tk.Label(
            parent, text=text, bg=BACKGROUND, fg=MUTED, font=FONT_SMALL,
        )
        label.pack(anchor="e" if side == "right" else "w",
                   padx=(0, BUBBLE_INSET) if side == "right" else (BUBBLE_INSET, 0))
        return label

    def _restack(self) -> None:
        """Put the scrolling conversation back at the end of the pack order.

        The packer allocates in pack order and the scroll area expands, so it
        must be the last thing packed into ``body``. Anything packed after it
        is handed nothing: the action row simply never appeared, and before
        that the thinking pill was mapped a single pixel tall.
        """
        scroll = self._widgets.get("scroll")
        if scroll is None:
            return
        try:
            scroll.pack_forget()
            scroll.pack(fill="both", expand=True, padx=12, pady=(3, 0))
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def _show_conversation(self) -> None:
        """Hide the empty state once there is a conversation, and show it again
        when there is not.

        The bubbles are no longer packed and unpacked here: they are rows in
        a list that is appended to, so showing them is simply having created
        them. What is left is the empty state and the action row, which are
        the two things that depend on whether anything has been said.
        """
        try:
            if self._has_exchange:
                self._widgets["empty"].pack_forget()
                # The pill shares the action row's slot, so whichever belongs
                # there is decided in one place.
                self.set_thinking(self._thinking)
            else:
                self._widgets["empty"].pack(fill="both", expand=True)
                self._widgets["actions"].pack_forget()
            self._restack()
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
                pill.pack(side="bottom", anchor="w", padx=12, pady=(4, 0))
            else:
                pill.pack_forget()
                if actions is not None and self._has_exchange:
                    actions.pack(
                        side="bottom", anchor="w", padx=12, pady=(4, 0)
                    )
            self._restack()
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
        #
        # One row, not two. It carried a 28px logo ring over a title and a
        # tagline, which is what made it 68 pixels tall; the ring is gone --
        # the orb is on screen beside this window and two rings is one too
        # many -- and the tagline with it, because a second line of text is
        # the other half of the height.
        header = tk.Frame(body, bg=BACKGROUND, height=HEADER_HEIGHT)
        header.pack(fill="x", padx=10, pady=(4, 0))
        header.pack_propagate(False)
        # Under its name in DRAG_HANDLE_WIDGETS, so that tuple is the handle
        # rather than a description of it.
        self._widgets["header"] = header

        self._widgets["title"] = tk.Label(
            header, text=PRODUCT_NAME, bg=BACKGROUND, fg=FOREGROUND,
            font=FONT_TITLE, anchor="w",
        )
        self._widgets["title"].pack(side="left")

        # Close, far right. An affordance for something that already exists --
        # Escape is bound to the same handler -- rather than new behaviour.
        self._widgets["close"] = tk.Label(
            header, text=CLOSE_GLYPH, bg=BACKGROUND, fg=MUTED,
            font=FONT_META, padx=6,
        )
        self._widgets["close"].pack(side="right")
        self._widgets["close"].bind("<Button-1>", lambda _event: self._close())

        # The state, as a dot in the state colour and the state's own word.
        status_block = tk.Frame(header, bg=BACKGROUND)
        status_block.pack(side="right", padx=(0, 8))
        self._widgets["dot"] = tk.Label(
            status_block, text="\u25cf", bg=BACKGROUND, font=FONT_SMALL,
            fg=STATE_COLOURS["loading"],
        )
        self._widgets["dot"].pack(side="left")
        self._widgets["state"] = tk.Label(
            status_block, text="Loading model...", bg=BACKGROUND, fg=FOREGROUND,
            anchor="w", font=FONT_STATE,
        )
        self._widgets["state"].pack(side="left", padx=(5, 0))

        # Which orb painter is live, as one muted word beside the state.
        #
        # **This is the only always-visible place it is reported.** The status
        # line under the input used to carry it and that line is gone: a line
        # that is always there is wallpaper, and it was four facts wide. The
        # trouble with showing it only on a fault is that a silent panel then
        # cannot confirm the glow painter is running, it can only fail to deny
        # it -- and confirming that is step O1 of the manual QA, the one step
        # every other visual judgement depends on. One word costs almost
        # nothing and turns O1 back into a glance.
        # Built when the painter is first reported, with its word in it: a
        # Label constructed with text="" is a widget present while saying
        # nothing, which is the fault this window was audited for.
        self._widgets["painter_slot"] = header

        # Spoken replies, on or off. A label rather than a Checkbutton so it
        # cannot be tabbed into -- the window must never acquire focus except
        # from a deliberate click.
        self._widgets["speak"] = tk.Label(
            header, text=self._speak_label(True), bg=SURFACE, fg=MUTED,
            font=FONT_SMALL, padx=5, pady=1,
        )
        self._widgets["speak"].pack(side="right", padx=(0, 8))
        self._widgets["speak"].bind("<Button-1>", self._toggle_speech)

        self._widgets["header_divider"] = tk.Frame(body, bg=DIVIDER, height=1)
        self._widgets["header_divider"].pack(fill="x", pady=(4, 0))

        # The level meter sits directly under the header, because while the key
        # is held it is the only thing the user is looking at.
        meter = tk.Canvas(
            body, height=METER_HEIGHT, bg=BACKGROUND, highlightthickness=0,
            bd=0, takefocus=False,
        )
        meter.pack(fill="x", padx=12, pady=(3, 0))
        self._widgets["meter"] = meter
        self._meter_bars = [
            meter.create_rectangle(0, 0, 0, 0, fill=DIVIDER, width=0)
            for _ in range(METER_BARS)
        ]
        self.set_levels(())

        # --- the conversation, which scrolls ---------------------------------
        #
        # A Canvas holding a Frame, which is the only way tk scrolls arbitrary
        # widgets. ``takefocus=False`` because the window must never become
        # tabbable; the Canvas is the one widget here big enough to be an
        # obvious tab target.
        scroll = tk.Canvas(
            body, bg=BACKGROUND, highlightthickness=0, bd=0, takefocus=False,
        )
        self._widgets["scroll"] = scroll

        inner = tk.Frame(scroll, bg=BACKGROUND)
        self._widgets["convo"] = inner
        self._scroll_window = scroll.create_window(
            0, 0, window=inner, anchor="nw",
        )
        inner.bind("<Configure>", self._on_convo_resized)
        scroll.bind("<Configure>", self._on_scroll_resized)
        # Entering the canvas claims the wheel and leaving gives it back, so
        # the binding is scoped to this window rather than the interpreter --
        # a bare bind_all would steal the wheel from the orb as well.
        scroll.bind("<Enter>", self._claim_wheel)
        scroll.bind("<Leave>", self._release_wheel)

        # The empty conversation, inside the scroll area so it scrolls away
        # the moment there is anything to scroll.
        empty = tk.Frame(inner, bg=BACKGROUND)
        self._widgets["empty"] = empty
        ring = tk.Canvas(
            empty, width=44, height=44, bg=BACKGROUND, highlightthickness=0,
            bd=0, takefocus=False,
        )
        ring.pack(pady=(14, 6))
        ring.create_oval(3, 3, 41, 41, outline=DIVIDER, width=2)
        self._widgets["empty_ring"] = ring
        self._widgets["empty_title"] = tk.Label(
            empty, text=EMPTY_TITLE, bg=BACKGROUND, fg=FOREGROUND,
            font=FONT_BODY,
        )
        self._widgets["empty_title"].pack()
        self._widgets["empty_body"] = tk.Label(
            empty, text=EMPTY_BODY.format(key=describe_hold_key(self.hold_key)),
            bg=BACKGROUND, fg=MUTED, font=FONT_SMALL,
        )
        self._widgets["empty_body"].pack(pady=(2, 0))
        empty.pack(fill="both", expand=True)

        # --- the action row, pinned ------------------------------------------
        #
        # Below the scroll area rather than inside it, so copy, read and stop
        # are reachable without scrolling back to find them. They act on the
        # newest reply, which is the only one they could sensibly act on.
        actions = tk.Frame(body, bg=BACKGROUND)
        self._widgets["actions"] = actions
        for name, label, handler in (
            ("copy", ACTION_COPY, self._copy_reply),
            ("read", ACTION_READ, self._read_reply),
            ("stop", ACTION_STOP, self._stop_speaking),
        ):
            button = tk.Canvas(
                actions, width=ACTION_WIDTH, height=ACTION_HEIGHT,
                bg=BACKGROUND, highlightthickness=0, bd=0, takefocus=False,
            )
            button.pack(side="left", padx=(0, 5))
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

        # The thinking pill shares the action row's slot. Both are the same
        # height, and controls for the previous reply are the least useful
        # thing on screen while a new one is being worked on.
        pill = tk.Frame(body, bg=SURFACE)
        self._widgets["thinking"] = pill
        self._widgets["thinking_dot"] = tk.Label(
            pill, text="\u25cf", bg=SURFACE, fg=STATE_COLOURS["thinking"],
            font=FONT_SMALL, padx=5,
        )
        self._widgets["thinking_dot"].pack(side="left")
        self._widgets["thinking_text"] = tk.Label(
            pill, text=THINKING_TEXT, bg=SURFACE, fg=MUTED, font=FONT_SMALL,
            padx=5, pady=2,
        )
        self._widgets["thinking_text"].pack(side="left")

        # --- the input --------------------------------------------------------
        self._widgets["input_divider"] = tk.Frame(body, bg=DIVIDER, height=1)

        input_row = tk.Frame(body, bg=BACKGROUND)
        self._widgets["input_row"] = input_row

        # A rounded pill rather than a square box with a bright blue outline.
        # The send arrow beside it is gone: Enter already sent, and a button
        # that duplicates a key is a second way to do one thing.
        field = tk.Canvas(
            input_row, height=INPUT_HEIGHT, bg=BACKGROUND,
            highlightthickness=0, bd=0, takefocus=False,
        )
        field.pack(fill="x", expand=True)
        self._widgets["field"] = field
        self._field_shape = None

        entry = tk.Entry(
            field, bg=SURFACE, fg=MUTED, relief="flat",
            insertbackground=FOREGROUND, font=FONT_BODY,
            # No highlight ring at all: the pill behind it is the edge now.
            highlightthickness=0, bd=0,
            # Keeps the entry out of the tab order, so the window cannot
            # acquire focus by being tabbed into from elsewhere.
            takefocus=False,
        )
        self._entry_window = field.create_window(
            INPUT_PAD, INPUT_HEIGHT / 2, window=entry, anchor="w",
            height=INPUT_HEIGHT - 12,
        )
        field.bind("<Configure>", self._on_field_resized)
        entry.bind("<Return>", self._submit)
        # A placeholder, because nothing else said the box could be typed in.
        entry.bind("<FocusIn>", self._hide_placeholder)
        entry.bind("<FocusOut>", self._show_placeholder)
        # On the entry, not the toplevel: a toplevel binding fires after the
        # class binding that inserts the character, so "break" there is too
        # late. See KEY_SYMS for the measurement.
        for part in self._hold_key_parts():
            for keysym in KEY_SYMS.get(part, ()):
                entry.bind(f"<KeyPress-{keysym}>", self._swallow_hold_key)
                entry.bind(f"<KeyRelease-{keysym}>", self._release_hold_key)
        self._widgets["entry"] = entry
        self._show_placeholder()

        # Only what is true. The entry is single-line, so there is no
        # "Shift + Enter for a new line" to promise.
        self._widgets["hold_hint"] = tk.Label(
            body, text=self.input_hint_text(),
            bg=BACKGROUND, fg=MUTED, font=FONT_META, anchor="w",
        )

        # From the bottom up, so the conversation above gets the slack rather
        # than taking it. The packer hands out space in pack order, so the
        # frame that expands must come last or the rows below it are pushed
        # off the window -- which is exactly what happened once already.
        self._widgets["hold_hint"].pack(
            side="bottom", fill="x", padx=12, pady=(4, 8)
        )
        self._widgets["input_row"].pack(
            side="bottom", fill="x", padx=12, pady=(6, 0)
        )
        self._widgets["input_divider"].pack(side="bottom", fill="x", pady=(4, 0))
        # And now the conversation, into whatever is left.
        scroll.pack(fill="both", expand=True, padx=12, pady=(3, 0))
        # Which of the action row and the thinking pill belongs in their
        # shared slot, and whether the empty state is showing, are decided in
        # one place rather than here.
        self._show_conversation()

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
        """Show what is wrong, or nothing at all.

        **The panel's always-present status line is gone.** It carried the
        model, the speech state, the microphone and the orb painter on every
        frame -- four facts wide, permanently there, and therefore read once
        and never again. The painter moved to one muted word in the header,
        where it can still be glanced at; everything else here is a fault.

        The widget is built on first use, with its text. A Label constructed
        with ``text=""`` at show() would be a widget present while saying
        nothing, which is the fault this window was audited for and which
        ``test_no_widget_is_constructed_with_an_empty_string`` exists to catch.
        """
        text = str(text or "")
        widget = self._widgets.get("fault")
        if widget is None:
            if not text:
                return
            tk = self._tk()
            body = self._widgets.get("input_row")
            parent = getattr(body, "master", None) or body
            if tk is None or parent is None:
                return
            try:
                widget = tk.Label(
                    parent, text=text, bg=BACKGROUND,
                    fg=STATE_COLOURS["error"], font=FONT_META, anchor="w",
                    wraplength=WIDTH - 32, justify="left",
                )
            except Exception:  # noqa: BLE001
                return
            self._widgets["fault"] = widget
        try:
            widget.configure(text=text)
            if text:
                widget.pack(side="bottom", fill="x", padx=12, pady=(2, 0))
            else:
                widget.pack_forget()
        except Exception:  # noqa: BLE001
            pass

    def set_transcript(self, text: str) -> None:
        """Open a row with what was heard, at the bottom of the conversation.

        A row rather than a label reconfigured in place. The panel kept one
        transcript label and one reply pane, so a second question overwrote
        the first and the only trace left was a truncated one-line summary.
        """
        self._last_transcript = text or ""
        if not text:
            return
        self._has_exchange = True
        self._show_conversation()
        tk_module = self._tk()
        if tk_module is None:
            return
        inner = self._widgets.get("convo")
        if inner is None:
            return
        try:
            if self._open_row is not None:
                # Spoke twice before a reply arrived: correct the open row
                # rather than leaving a question with no answer above it.
                label = self._open_row.get("heard_label")
                if label is not None:
                    label.configure(text=f"\u201c{text}\u201d")
                meta = self._open_row.get("heard_meta")
                if meta is not None:
                    meta.configure(text=self.user_meta_text(text))
                self._scroll_to_bottom()
                return
            row, bubble, label = self._bubble(
                inner, f"\u201c{text}\u201d", side="right", colour=BUBBLE_USER
            )
            meta = self._meta(inner, self.user_meta_text(text), side="right")
            # Clicking it loads it into the box below to be corrected and resent.
            for widget in (row, bubble, label):
                widget.bind("<Button-1>", self._edit_transcript)
            self._open_row = {
                "heard": text, "row": row, "heard_label": label,
                "heard_meta": meta,
            }
            self._trim_rows()
            self._scroll_to_bottom()
        except Exception:  # noqa: BLE001 - a closed window must not raise
            pass

    def set_reply(self, text: str) -> None:
        """Complete the open row with the reply, and pin the actions to it."""
        self._last_reply = text or ""
        if not text:
            return
        self._has_exchange = True
        self._show_conversation()
        inner = self._widgets.get("convo")
        if inner is None:
            return
        try:
            row, bubble, label = self._bubble(
                inner, text, side="left", colour=BUBBLE_GRANDPA,
                selectable=True,
            )
            meta = self._meta(inner, self.reply_meta_text(), side="left")
            entry = self._open_row or {}
            entry.update({
                "reply": text, "reply_row": row, "reply_label": label,
                "reply_meta": meta,
            })
            self._rows.append(entry)
            self._open_row = None
            # The reply widget the copy button reads, and the one the
            # truncation probe measures.
            self._widgets["reply"] = label
            self._trim_rows()
            self._scroll_to_bottom()
        except Exception:  # noqa: BLE001
            pass

    def _trim_rows(self) -> None:
        """Keep the scrollback bounded, oldest first.

        Each exchange is eight widgets and nothing ever releases them on its
        own, so without this a long day is a slow leak.
        """
        try:
            while len(self._rows) > HISTORY_LIMIT:
                oldest = self._rows.pop(0)
                for key in ("row", "reply_row"):
                    widget = oldest.get(key)
                    if widget is not None:
                        widget.destroy()
                for key in ("heard_meta", "reply_meta"):
                    widget = oldest.get(key)
                    if widget is not None:
                        widget.destroy()
        except Exception:  # noqa: BLE001
            pass

    def rows(self) -> tuple[tuple[str, str], ...]:
        """The exchanges on screen, oldest first. For tests and for counting."""
        return tuple(
            (str(row.get("heard", "")), str(row.get("reply", "")))
            for row in self._rows
        )

    def set_painter(self, word: str) -> None:
        """The one muted word in the header: ``glow`` or ``disc``.

        **The only always-visible report of which painter is live.** The
        status line that used to carry it is gone, and a line shown only on a
        fault cannot confirm the good case -- it can only fail to deny it.
        Confirming the glow painter is running is step O1 of the manual QA,
        and every later visual judgement depends on knowing which painter drew
        what is on screen.

        Built on first use, with its word, so there is never an empty Label
        sitting in the header.
        """
        word = str(word or "")
        widget = self._widgets.get("painter")
        if widget is None:
            if not word:
                return
            tk = self._tk()
            header = self._widgets.get("painter_slot")
            if tk is None or header is None:
                return
            try:
                widget = tk.Label(
                    header, text=word, bg=BACKGROUND, fg=MUTED,
                    font=FONT_SMALL,
                )
                widget.pack(side="right", padx=(0, 8))
            except Exception:  # noqa: BLE001
                return
            self._widgets["painter"] = widget
            return
        try:
            widget.configure(text=word)
        except Exception:  # noqa: BLE001
            pass

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
    "FOCUS_STEALING_CALLS",
    "KEY_SYMS",
    "REMAP_CALLS",
    "STATE_COLOURS",
    "TkBubbleView",
]
