"""The desktop app: session messages, answers, and page safety guards."""

from __future__ import annotations

from pathlib import Path

from grandpa.app.session import AppSession
from grandpa.app.window import WEB_DIR, browser_address, connect_script
from grandpa.tui.bridge import Question, UiHooks


class FakeBridge:
    def __init__(self, hooks: UiHooks) -> None:
        self.hooks = hooks
        self.sent: list[str] = []
        self.cancelled = 0

    def start(self) -> None:
        self.hooks.output("BIG ASCII BANNER\n")
        self.hooks.ready_for_input("You > ")

    def send(self, text: str) -> None:
        self.sent.append(text)

    def cancel(self) -> bool:
        self.cancelled += 1
        return True

    def quit(self) -> None:
        pass


def _session():
    published: list[dict] = []
    session = AppSession(published.append, bridge_factory=FakeBridge)
    session.start()
    return session, session.bridge, published


def test_the_startup_banner_is_hidden_and_the_app_becomes_ready() -> None:
    session, _bridge, published = _session()
    assert session.state == "idle"
    assert not any("BANNER" in str(m) for m in published)
    assert published[-1]["type"] in {"state", "model"}


def test_a_message_and_its_markdown_reply() -> None:
    session, bridge, published = _session()
    assert session.send("hello") is True
    assert bridge.sent == ["hello"] and session.state == "thinking"
    assert session.send("again") is False  # one at a time
    hooks = bridge.hooks
    hooks.turn("grandpa")
    hooks.output("  · open_app ok\n")
    hooks.reply("markdown", "**Done** opening Notepad")
    hooks.ready_for_input("You > ")
    kinds = [m["type"] for m in published]
    assert kinds[-4:] == ["note", "reply", "state", "state"] or "reply" in kinds
    reply = next(m for m in published if m["type"] == "reply")
    assert {k: reply[k] for k in ("v", "type", "format", "text")} == {
        "v": 1,
        "type": "reply",
        "format": "markdown",
        "text": "**Done** opening Notepad",
    }
    note = next(m for m in published if m["type"] == "note")
    assert reply["seq"] > note["seq"] and reply["run"] == note["run"]
    assert "open_app ok" in note["text"]
    assert session.state == "idle"
    assert [m["type"] for m in session.snapshot()][:3] == ["user", "note", "reply"]


def test_questions_are_answered_from_the_page() -> None:
    session, bridge, published = _session()
    session.send("delete my note")
    question = Question(
        kind="confirm", prompt="Delete note 'x'? [y/N]", options=[], yes_no=True
    )
    bridge.hooks.ask(question)
    ask = published[-1]
    assert (
        ask["type"] == "ask"
        and ask["kind"] == "confirm"
        and "Delete note" in ask["prompt"]
    )
    assert session.send("yes") is True
    assert question.wait() == "y"

    choose = Question(
        kind="choose", prompt="Switch model", options=["  Fast  Middle", "* Brain"]
    )
    bridge.hooks.ask(choose)
    assert session.send("Fast  Middle") is True  # the page's text arrives trimmed
    assert choose.wait() == "  Fast  Middle"


def test_stop_answers_an_open_question_with_no() -> None:
    session, bridge, _ = _session()
    session.send("shutdown")
    question = Question(
        kind="confirm", prompt="Shut down? [y/N]", options=[], yes_no=True
    )
    bridge.hooks.ask(question)
    assert session.cancel() is True
    assert question.wait() == "n"
    assert (
        session.cancel() is True and bridge.cancelled == 1
    )  # nothing open: stops the reply


def test_model_switches_are_announced() -> None:
    session, bridge, published = _session()
    session.send("/model fast")
    bridge.hooks.reply("text", "Model changed to Grandpa Fast (grandpa-fast:latest).")
    assert session.model == "grandpa-fast:latest"
    assert {"v": 1, "type": "model", "name": "grandpa-fast:latest"} in published


def test_the_page_never_builds_html_from_strings() -> None:
    # Replies are model output; building markup from strings would let a reply
    # inject script. The page uses createElement/textContent only.
    for name in ("app.js", "markdown.js"):
        source = (WEB_DIR / name).read_text(encoding="utf-8")
        for banned in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
        ):
            assert banned not in source, f"{name} uses {banned}"
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert "script-src 'self'" in page and "default-src 'none'" in page
    assert "connect-src ws://127.0.0.1:*" in page


def test_addresses_carry_the_token_only_in_the_hash_or_script() -> None:
    url = "ws://127.0.0.1:1234/avatar?token=abc"
    assert browser_address(url, 5555).startswith("http://127.0.0.1:5555/index.html#ws=")
    assert connect_script(url) == (
        'window.grandpaConnect && window.grandpaConnect("ws://127.0.0.1:1234/avatar?token=abc");'
    )


def test_every_page_file_exists() -> None:
    for name in ("index.html", "app.css", "app.js", "markdown.js"):
        assert (Path(WEB_DIR) / name).is_file()


def test_a_startup_failure_shows_its_reason() -> None:
    class FailingBridge(FakeBridge):
        def start(self) -> None:
            self.hooks.output("Ollama is not running. Start it with: ollama serve\n")
            self.hooks.finished(1)

    published: list[dict] = []
    session = AppSession(published.append, bridge_factory=FailingBridge)
    session.start()
    notes = [m["text"] for m in published if m["type"] == "note"]
    assert any("Ollama is not running" in n for n in notes)
    assert session.state == "stopped"


# --- attach, voice typing, the window API, and the Claude-style page ------------


def test_an_attached_file_is_read_and_named_in_the_user_record(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_text("buy milk\n", encoding="utf-8")
    session, bridge, published = _session()
    assert session.send('what is in this?\n@"notes.txt"') is True
    assert "buy milk" in bridge.sent[0] and "File: notes.txt" in bridge.sent[0]
    user = next(m for m in published if m["type"] == "user")
    assert user["attached"] == ["notes.txt"]


def test_a_file_that_cannot_be_attached_gives_a_red_note(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session, bridge, published = _session()
    session.send('@"missing.txt" please')
    assert bridge.sent == ['@"missing.txt" please']
    assert any(m["type"] == "note" and m.get("failed") for m in published)


def test_voice_typing_sends_the_words_back_to_the_page(monkeypatch) -> None:
    import grandpa.tui.voice as voice

    class FakeTalk:
        def __init__(self, on_text, on_error, on_level, **_k) -> None:
            self.on_text, self.recording = on_text, False

        def start(self) -> bool:
            self.recording = True
            return True

        def stop(self) -> None:
            self.recording = False
            self.on_text("open notepad")

    monkeypatch.setattr(voice, "PushToTalk", FakeTalk)
    session, _bridge, published = _session()
    assert session.talk() is True
    assert published[-1] == {**published[-1], "type": "listening"}
    assert session.talk() is True  # second click stops and transcribes
    heard = [m for m in published if m["type"] == "heard"]
    assert heard and heard[-1]["text"] == "open notepad"


def test_the_window_api_only_picks_files_and_reads_the_name(monkeypatch) -> None:
    from grandpa.app import window

    api = window.AppApi()
    public = {name for name in dir(api) if not name.startswith("_")}
    assert public == {"pick_file", "user_name", "window"}
    assert api.pick_file() is None  # no window yet: nothing happens
    monkeypatch.setattr(window, "user_name", lambda: "Captain")
    assert api.user_name() == "Captain"


def test_the_page_has_the_claude_style_parts() -> None:
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for part in (
        'id="sidebar"',
        'id="side-close"',
        'id="side-open"',
        'id="search"',
        'id="projects"',
        'id="new-project"',
        'id="chats"',
        'id="user-name"',
        'id="open-settings"',
        'id="incognito"',
        'id="attach"',
        'id="mic"',
        'id="model"',
        'id="model-menu"',
        'id="settings"',
        'data-tab="data"',
    ):
        assert part in page, part
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # incognito chats are never written to storage
    assert "if (!incognito) { save();" in script
    # voice typing and the stop button only ever send these fixed messages
    assert 'send({ type: "talk" })' in script and 'send({ type: "cancel" })' in script


def test_the_page_uses_only_the_project_colours() -> None:
    import re

    css = (WEB_DIR / "app.css").read_text(encoding="utf-8")
    from grandpa.tui.themes import DARK, LIGHT

    allowed = {
        c.lower()
        for c in (
            "#E5E7EB",
            "#168BFF",
            "#FFD21F",
            "#FF3B45",
            "#A855F7",
            "#22C55E",
            "#FF922B",
        )
    }
    for theme in (DARK, LIGHT):
        allowed |= {
            str(v).lower()
            for v in vars(theme).values()
            if isinstance(v, str) and v.startswith("#")
        }
        allowed |= {str(v).lower() for v in getattr(theme, "accents", {}).values()}
    used = {c.lower() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", css)}
    assert used <= allowed, used - allowed
