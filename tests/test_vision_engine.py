from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from click.testing import CliRunner
from PIL import Image

from grandpa.automation.locator import HighlightOverlay
from grandpa.automation.models import (
    AutomationAction,
    AutomationResult,
    BoundingBox,
    LocatedElement,
)
from grandpa.automation.planner import AutomationPlanner
from grandpa.automation.service import ScreenAutomationService
from grandpa.cli.vision_cmd import vision
from grandpa.screen.capture import ScreenCapture
from grandpa.screen.models import OcrBlock, OcrResult
from grandpa.screen.ocr import _extract_blocks
from grandpa.vision.actions import VisualActionService
from grandpa.vision.graph import ElementGraphBuilder
from grandpa.vision.matcher import HybridElementMatcher
from grandpa.vision.models import (
    ElementGraph,
    VisionBounds,
    VisionCaptureMetadata,
    VisionMatch,
    VisionNode,
    VisionResult,
)
from grandpa.vision.service import VisionEngine


def _metadata() -> VisionCaptureMetadata:
    return VisionCaptureMetadata(
        800,
        600,
        1,
        "Example",
        10,
        20,
        datetime(2026, 1, 1),
        "active_window",
        "mock",
        (100, 200, 900, 800),
    )


def _graph(*nodes: VisionNode) -> ElementGraph:
    return ElementGraph(
        tuple(nodes), _metadata(), uia_available=True, ocr_available=True
    )


def test_ocr_graph_preserves_reading_groups_and_offsets() -> None:
    ocr = OcrResult(
        "Login now",
        blocks=(
            OcrBlock("Login", 0.95, (10, 20, 50, 20), 0, "1:1:1", "1:1"),
            OcrBlock("now", 0.90, (65, 20, 30, 20), 1, "1:1:1", "1:1"),
        ),
    )

    graph = ElementGraphBuilder().build(capture=_metadata(), ocr=ocr, uia_nodes=())

    line = graph.node("ocr:line:1:1:1")
    paragraph = graph.node("ocr:paragraph:1:1")
    assert line is not None and line.text == "Login now"
    assert paragraph is not None and line.id in paragraph.children
    assert graph.node("ocr:word:0").bounds.left == 110


def test_graph_merges_uia_and_ocr_agreement() -> None:
    uia = VisionNode(
        "uia:1",
        "button",
        name="Login",
        confidence=1.0,
        bounds=VisionBounds(110, 220, 80, 30),
        source="uia",
        clickable=True,
    )
    ocr = OcrResult(
        "Login",
        blocks=(OcrBlock("Login", 0.93, (10, 20, 80, 30)),),
    )

    graph = ElementGraphBuilder().build(capture=_metadata(), ocr=ocr, uia_nodes=(uia,))

    assert graph.node("uia:1").source == "uia+ocr"


def test_matcher_ranks_exact_hybrid_clickable_match_first() -> None:
    graph = _graph(
        VisionNode(
            "1",
            "button",
            name="Login",
            confidence=1,
            bounds=VisionBounds(10, 10, 80, 20),
            source="uia+ocr",
            clickable=True,
        ),
        VisionNode(
            "2",
            "text",
            text="Login help",
            confidence=0.8,
            bounds=VisionBounds(10, 50, 80, 20),
            source="ocr",
        ),
    )

    matches = HybridElementMatcher().search(graph, "Login", actionable=True)

    assert matches[0].node.id == "1"
    assert matches[0].confidence > matches[1].confidence


def test_matcher_hides_invisible_and_deprioritizes_disabled_controls() -> None:
    graph = _graph(
        VisionNode("hidden", "button", name="Save", visible=False),
        VisionNode(
            "disabled",
            "button",
            name="Save",
            enabled=False,
            visible=True,
            source="uia",
        ),
    )

    assert HybridElementMatcher().search(graph, "Save", actionable=True) == ()


def test_ocr_only_target_is_not_clickable_without_verification() -> None:
    node = VisionNode(
        "ocr:1",
        "text",
        text="Continue",
        confidence=0.99,
        bounds=VisionBounds(10, 10, 100, 30),
        source="ocr",
    )
    engine = SimpleNamespace(
        find=lambda *_args, **_kwargs: VisionResult(
            "handled",
            "",
            _graph(node),
            (VisionMatch(node, 0.69),),
        )
    )
    service = VisualActionService(engine=engine, minimum_confidence=0.6)

    result = service.prepare_click("Continue")

    assert result.status == "confirmation_required"
    assert "OCR only" in result.message


def test_ambiguous_buttons_are_never_chosen_arbitrarily() -> None:
    first = VisionNode("1", "button", name="Login", source="uia+ocr", clickable=True)
    second = VisionNode("2", "button", name="Login", source="uia+ocr", clickable=True)
    matches = (VisionMatch(first, 0.95), VisionMatch(second, 0.93))
    engine = SimpleNamespace(
        find=lambda *_args, **_kwargs: VisionResult(
            "handled", "", _graph(first, second), matches
        )
    )

    result = VisualActionService(engine=engine).prepare_click("Login")

    assert result.status == "ambiguous"


def test_highlight_is_read_only() -> None:
    highlighted = []
    node = VisionNode(
        "1",
        "button",
        name="Save",
        bounds=VisionBounds(10, 20, 50, 20),
        source="uia+ocr",
        clickable=True,
    )
    engine = SimpleNamespace(
        find=lambda *_args, **_kwargs: VisionResult(
            "handled", "", _graph(node), (VisionMatch(node, 0.95),)
        )
    )
    service = VisualActionService(
        engine=engine,
        highlighter=HighlightOverlay(lambda item, _duration: highlighted.append(item)),
    )

    result = service.highlight("Save")

    assert result.status == "handled"
    assert highlighted[0].text == "Save"


def test_screen_capture_supports_region_without_duplicate_backend(monkeypatch) -> None:
    capture = ScreenCapture()
    monkeypatch.setattr(
        capture,
        "_capture_region",
        lambda region: (
            Image.new("RGB", (region[2] - region[0], region[3] - region[1]), "white"),
            "mock",
        ),
    )
    monkeypatch.setattr("grandpa.screen.capture.list_monitors", lambda: [])

    result = capture.capture(region=(100, 200, 300, 400))

    assert result.capture_source == "region"
    assert result.capture_region == (100, 200, 300, 400)
    assert (result.width, result.height) == (200, 200)


def test_ocr_preprocessing_coordinates_scale_back_to_source_image() -> None:
    fake = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_data=lambda *_args, **_kwargs: {
            "text": ["Save"],
            "conf": ["90"],
            "left": [200],
            "top": [100],
            "width": [80],
            "height": [40],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        },
    )

    blocks, _confidence = _extract_blocks(
        fake,
        Image.new("RGB", (1600, 1200)),
        "eng",
        scale_x=0.5,
        scale_y=0.5,
    )

    assert blocks[0].bounds == (100, 50, 40, 20)


def test_vision_describe_reports_dialog_loading_and_error() -> None:
    nodes = (
        VisionNode("root", "window", name="Example", focused=True),
        VisionNode("dialog", "window", name="Installer", parent="root"),
        VisionNode("button", "button", name="Continue", clickable=True),
        VisionNode("progress", "progress_bar", name="Loading"),
        VisionNode("line", "text_line", text="Error: install failed"),
    )
    engine = VisionEngine()
    engine.inspect = lambda **_kwargs: VisionResult("handled", "", _graph(*nodes))  # type: ignore[method-assign]

    result = engine.describe()

    assert result.data["dialog_detected"] is True
    assert result.data["loading"] is True
    assert result.data["error_detected"] is True


def test_vision_describe_does_not_report_active_root_as_dialog() -> None:
    root = VisionNode("root", "window", name="Example", focused=True)
    engine = VisionEngine()
    engine.inspect = lambda **_kwargs: VisionResult(  # type: ignore[method-assign]
        "handled", "", _graph(root)
    )

    result = engine.describe()

    assert result.data["dialog_detected"] is False


def test_vision_selected_returns_only_visible_selected_nodes() -> None:
    selected = VisionNode("selected", "text", name="Chosen", selected=True)
    hidden = VisionNode("hidden", "text", name="Hidden", selected=True, visible=False)
    engine = VisionEngine()
    engine.inspect = lambda **_kwargs: VisionResult(  # type: ignore[method-assign]
        "handled", "", _graph(selected, hidden)
    )

    assert engine.selected() == (selected,)


def test_vision_cli_help_lists_read_only_debug_commands() -> None:
    result = CliRunner().invoke(vision, ["--help"])

    assert result.exit_code == 0
    for command in (
        "inspect",
        "describe",
        "graph",
        "screenshot",
        "find",
        "buttons",
        "controls",
    ):
        assert command in result.output


def test_planner_uses_visual_lookup_for_plain_find_and_scroll_until() -> None:
    find = AutomationPlanner().parse("Find Login")
    scroll = AutomationPlanner().parse("Scroll down until Submit appears")

    assert find is not None and find.kind == "locate"
    assert scroll is not None and scroll.kind == "scroll_until"
    assert scroll.target == "submit"


def test_scroll_until_is_bounded_and_stops_when_target_appears() -> None:
    target = LocatedElement(
        "Submit",
        "button",
        0.94,
        BoundingBox(10, 20, 80, 30),
        source="uia+ocr",
    )

    class Locator:
        calls = 0

        def locate(self, _query, *, limit=2):
            self.calls += 1
            return () if self.calls == 1 else (target,)

    class Executor:
        locator = Locator()

        def execute(self, action, **_kwargs):
            assert action.kind == "scroll"
            return AutomationResult("handled", "Scrolled.", action)

    service = ScreenAutomationService(executor=Executor())
    result = service._scroll_until(  # noqa: SLF001 - focused bounded-loop unit test
        AutomationAction(
            "scroll_until",
            "Submit",
            {"direction": "down", "amount": -5, "max_attempts": 3},
        ),
        dry_run=False,
    )

    assert result.status == "handled"
    assert result.data["scroll_steps"] == 1
