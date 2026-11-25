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
    assert "buy milk" in bridge.sent[0]
    assert 'Attached file "notes.txt"' in bridge.sent[0]
    assert (
        '@"notes.txt"' not in bridge.sent[0]
    )  # the model sees a name, not a path to open
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
    assert public == {
        "pick_file",
        "pick_files",
        "user_name",
        "get_profile",
        "save_profile",
        "open_orb",
        "set_next_context",
        "list_memories",
        "forget_memory",
        "add_memory",
        "list_skills",
        "save_skill",
        "delete_skill",
        "import_skill",
        "skill_instructions",
        "mcp_status",
        "mcp_save_server",
        "mcp_remove_server",
        "mcp_toggle_server",
        "mcp_set_off",
        "mcp_test",
        "providers_status",
        "provider_save",
        "provider_remove",
        "provider_models",
    }
    assert api.pick_file() is None and api.pick_files() == []  # no window yet
    monkeypatch.setattr(window, "user_name", lambda: "Mr. Hari Hara Sudhan")
    assert api.user_name() == "Mr. Hari Hara Sudhan"


def test_the_page_has_the_claude_style_parts() -> None:
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for part in (
        'id="sidebar"',
        'id="side-close"',
        'id="side-open"',
        'id="open-search"',
        'id="palette"',
        'id="nav-projects"',
        'id="projects-view"',
        'id="project-instructions"',
        'id="nav-memory"',
        'id="memory-view"',
        'id="pinned"',
        'id="chats"',
        'id="title-button"',
        'id="user-button"',
        'id="user-name"',
        'id="incognito"',
        'id="plus"',
        'id="attach"',
        'id="mic"',
        'id="model"',
        'id="model-menu"',
        'id="send"',
        'id="stop"',
        'id="settings"',
        'data-tab="data"',
        'data-tab="keys"',
        'id="drop-shade"',
    ):
        assert part in page, part
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # incognito chats are never written to storage
    assert "if (!incognito) { save();" in script
    # voice typing and the stop button only ever send these fixed messages
    assert 'send({ type: "talk" })' in script and 'send({ type: "cancel" })' in script
    # streaming words are shown, never stored
    assert 'msg.type === "delta"' in script and "function onDelta" in script


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


# --- the ＋ menu, files from anywhere the user picked, documents, the profile ---


def test_the_plus_menu_holds_add_files_voice_and_the_orb() -> None:
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for part in (
        'id="plus"',
        'id="plus-menu"',
        'id="attach"',
        'id="plus-voice"',
        'id="plus-orb"',
        'id="set-title"',
        'id="set-email"',
        'id="save-profile"',
    ):
        assert part in page, part


def test_a_picked_file_outside_home_can_be_attached_but_a_typed_one_cannot(
    tmp_path, monkeypatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "plan.txt").write_text("step one\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(Path, "home", lambda: work)
    session, bridge, _published = _session()
    target = str(elsewhere / "plan.txt")

    session.send(f'@"{target}"')  # typed, never picked: refused
    assert "step one" not in bridge.sent[-1]
    session.state = "idle"

    session.allow_file(target)  # picked in the dialog
    session.send(f'@"{target}"')
    assert "step one" in bridge.sent[-1]


def test_a_word_document_is_attached_as_its_text(tmp_path, monkeypatch) -> None:
    import zipfile

    from grandpa.tui.helpers import read_attachment

    doc = tmp_path / "letter.docx"
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Dear Grandpa</w:t></w:r></w:p></w:body></w:document>",
        )
    monkeypatch.chdir(tmp_path)
    text, note = read_attachment("letter.docx")
    assert text is not None and "Dear Grandpa" in text and note == ""


def test_a_document_without_text_gives_a_clear_note(tmp_path, monkeypatch) -> None:
    from grandpa.tui.helpers import read_attachment

    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4 not really")
    monkeypatch.chdir(tmp_path)
    text, note = read_attachment("scan.pdf")
    assert text is None and "couldn't read any text" in note


def test_the_window_is_handed_to_the_api_so_the_file_dialog_can_open(
    monkeypatch,
) -> None:
    """The bug behind "attaching doesn't work": the api never got the window."""
    from grandpa.app import window as app_window

    made: dict = {}

    class Events:
        def __init__(self):
            self.loaded = self

        def __iadd__(self, _handler):
            return self

    class FakeWindow:
        events = Events()

        def create_file_dialog(self, *_a, **_k):
            return ["C:/Users/me/notes.txt"]

    class FakeWebview:
        OPEN_DIALOG = 10

        def create_window(self, *_a, js_api=None, **_k):
            made["api"] = js_api
            return FakeWindow()

        def start(self, **_k):
            made["paths"] = made["api"].pick_files()

    class Session:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        send = talk = cancel = snapshot = start

        def allow_file(self, path):
            return path

    class Server:
        url = "ws://127.0.0.1:1/x"

        def __init__(self, **_k):
            pass

        def start(self, timeout=0):
            pass

        def stop(self):
            pass

        def broadcast(self, _m):
            pass

    monkeypatch.setenv("GRANDPA_HOME", str(Path.cwd() / "runtime" / "test-home"))
    monkeypatch.setattr("grandpa.app.session.AppSession", Session)
    monkeypatch.setattr("grandpa.ui.avatar_server.AvatarServer", Server)
    monkeypatch.setattr(app_window, "_storage_dir", lambda: None)
    app_window.run(webview_module=FakeWebview(), echo=lambda *_a: None)
    assert made["paths"] == ["C:/Users/me/notes.txt"]


def test_the_profile_is_saved_with_title_and_email(tmp_path, monkeypatch) -> None:
    from grandpa.app import window
    from grandpa.core.config import load_config

    config = tmp_path / "config.toml"
    monkeypatch.setenv("Grandpa_CONFIG", str(config))
    monkeypatch.setattr(
        "grandpa.core.config.DEFAULT_CONFIG_PATH", config, raising=False
    )
    load_config.cache_clear()
    monkeypatch.setattr(window, "read_profile", lambda: {"display": "x"})
    try:
        _check_profile_saving(window, config)
    finally:
        load_config.cache_clear()  # never leave this test's config cached


def _check_profile_saving(window, config) -> None:

    bad = window.write_profile("Mr.", "Hari Hara Sudhan", "not-an-email")
    assert bad["ok"] is False and "email" in bad["error"]
    bad = window.write_profile("Sir", "Hari", "")
    assert bad["ok"] is False
    good = window.write_profile("mr", "Hari Hara Sudhan", "hari@example.com")
    assert good["ok"] is True
    text = config.read_text(encoding="utf-8")
    assert 'title = "Mr."' in text and 'email = "hari@example.com"' in text
    assert "onboarding_completed = true" in text


# --- streaming, project instructions, memory --------------------------------


def test_reply_words_stream_to_the_page_but_are_not_recorded() -> None:
    session, bridge, published = _session()
    session.send("hello")
    bridge.hooks.stream("Hel")
    bridge.hooks.stream("lo")
    bridge.hooks.stream("")  # a tool call: drop what was shown
    deltas = [m for m in published if m["type"] == "delta"]
    assert [d.get("text") for d in deltas[:2]] == ["Hel", "lo"]
    assert deltas[2].get("reset") is True
    assert all("run" not in d for d in deltas)  # never replayed after a reconnect


def test_project_instructions_go_with_the_next_message_only() -> None:
    from grandpa.app.window import AppApi

    session, bridge, published = _session()
    api = AppApi(session)
    assert api.set_next_context("Answer in Thanglish.") is True
    session.send("/clear")  # a command neither carries nor uses it up
    assert bridge.sent[-1] == "/clear"
    bridge.hooks.ready_for_input("You > ")
    session.send("menu ideas")
    assert "Answer in Thanglish." in bridge.sent[-1] and bridge.sent[-1].endswith(
        "menu ideas"
    )
    user = [m for m in published if m["type"] == "user"][-1]
    assert user["text"] == "menu ideas"  # shown as typed
    bridge.hooks.ready_for_input("You > ")
    session.send("more")
    assert bridge.sent[-1] == "more"
    assert api.set_next_context(123) is False


def test_forgetting_a_memory_needs_its_exact_id(monkeypatch) -> None:
    from grandpa.app import window

    asked: list = []

    class Store:
        def forget(self, query):
            asked.append(query)
            return 1

    monkeypatch.setattr("grandpa.memory_context.MemoryStore", Store)
    assert window.forget_memory("tea") is False  # a search could match many
    assert window.forget_memory(True) is False
    assert window.forget_memory(0) is False
    assert window.forget_memory(7) is True
    assert asked == ["7"]
