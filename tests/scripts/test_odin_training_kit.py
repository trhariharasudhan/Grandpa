"""O3: the Odin-1 training kit is complete and consistent.

The notebook is run by Captain on Colab or Kaggle, never here. These tests
check what can be checked without a GPU: the notebook is valid and its code
parses, it trains the same base family as grandpa-brain on the O2 dataset and
exports Q4_K_M GGUF, and the Modelfile, build script and README agree on file
names and never make Odin-1 the default.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOTEBOOK = REPO / "notebooks" / "odin_brain_lora.ipynb"
MODELFILE = REPO / "models" / "Modelfile.brain-odin1"
BASE_MODELFILE = REPO / "models" / "Modelfile.brain"
SCRIPT = REPO / "scripts" / "odin" / "create_odin1.ps1"
README = REPO / "scripts" / "odin" / "README.md"
GGUF_NAME = "grandpa-brain-odin1.Q4_K_M.gguf"


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code() -> str:
    return "\n".join(
        "".join(cell["source"])
        for cell in _notebook()["cells"]
        if cell["cell_type"] == "code"
    )


def test_the_notebook_is_valid_nbformat_4_and_every_cell_parses() -> None:
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["accelerator"] == "GPU"
    for cell in notebook["cells"]:
        assert cell["cell_type"] in {"code", "markdown"}
        assert isinstance(cell["source"], list)
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            source = re.sub(r"^\s*[%!].*$", "", "".join(cell["source"]), flags=re.M)
            ast.parse(source)


def test_it_trains_the_grandpa_brain_family_with_unsloth_lora() -> None:
    code = _code()
    base_from = re.search(r"^FROM\s+(\S+)", BASE_MODELFILE.read_text(), re.M).group(1)
    assert base_from == "qwen3:8b"
    assert 'BASE_MODEL = "unsloth/Qwen3-8B"' in code
    assert "FastLanguageModel.get_peft_model" in code
    assert "load_in_4bit=True" in code


def test_it_uses_the_o2_dataset_with_its_tools() -> None:
    code = _code()
    assert "train.jsonl" in code and "eval.jsonl" in code
    assert 'row["messages"]' in code and "tools=tools" in code


def test_it_exports_q4_k_m_gguf_under_the_modelfile_name() -> None:
    code = _code()
    assert 'quantization_method="q4_k_m"' in code
    assert GGUF_NAME in code


def test_the_modelfile_points_at_the_exported_gguf() -> None:
    text = MODELFILE.read_text(encoding="utf-8")
    assert re.search(rf"^FROM\s+\./odin/{re.escape(GGUF_NAME)}$", text, re.M)
    assert "SYSTEM" in text


def test_the_build_script_uses_the_modelfile_and_the_qwen3_template() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Modelfile.brain-odin1" in text
    assert GGUF_NAME in text
    assert "ollama show qwen3:8b --template" in text
    assert "ollama create grandpa-brain-odin1" in text


def test_the_readme_walks_every_step() -> None:
    text = README.read_text(encoding="utf-8")
    for step in (
        "scripts/odin/make_dataset.py",
        "odin_brain_lora.ipynb",
        "T4 GPU",
        "Run all",
        GGUF_NAME,
        "create_odin1.ps1",
        "grandpa models eval",
    ):
        assert step in text, step


def test_nothing_makes_odin1_the_default() -> None:
    for path in (SCRIPT, README, MODELFILE, NOTEBOOK):
        text = path.read_text(encoding="utf-8")
        assert "default_model" not in text, path
        assert "config set" not in text, path


def test_the_weights_are_ignored_by_git() -> None:
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "*.gguf" in ignore
    assert "/models/odin/" in ignore
