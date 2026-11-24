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
    assert reply == {
        "v": 1,
        "type": "reply",
        "format": "markdown",
        "text": "**Done** opening Notepad",
    }
    note = next(m for m in published if m["type"] == "note")
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
