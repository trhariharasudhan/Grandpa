"""Load system prompt and few-shot overrides from $Grandpa_HOME.

LLM-guided spec search (M1) proposes edits that get written to disk by appliers.
This module lets agents pick those overrides up at runtime:

- System prompts: ``$Grandpa_HOME/agents/{name}/system_prompt.md``
- Few-shot exemplars: ``$Grandpa_HOME/agents/{name}/few_shot.json``

Override files are templates — they may contain ``{tool_descriptions}`` and
other format placeholders that the agent fills in via ``.format()``, exactly
like the hardcoded constants.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _Grandpa_home() -> Path:
    """Resolve $Grandpa_HOME, defaulting to ~/.openjarvis."""
    return Path(os.environ.get("Grandpa_HOME", "~/.Grandpa")).expanduser()


def load_system_prompt_override(agent_name: str) -> str | None:
    """Return the override prompt for *agent_name*, or ``None``.

    Looks for ``$Grandpa_HOME/agents/<agent_name>/system_prompt.md``.
    ``Grandpa_HOME`` defaults to ``~/.Grandpa`` when unset.
    """
    home = _Grandpa_home()
    prompt_path = home / "agents" / agent_name / "system_prompt.md"
    if not prompt_path.exists():
        return None
    try:
        content = prompt_path.read_text(encoding="utf-8")
        logger.info(
            "Loaded system prompt override for %s from %s", agent_name, prompt_path
        )
        return content
    except Exception:
        logger.warning(
            "Failed to read system prompt override at %s", prompt_path, exc_info=True
        )
        return None


def load_few_shot_exemplars(
    agent_name: str,
) -> list[dict[str, Any]]:
    """Return few-shot exemplars for *agent_name*, or empty list.

    Looks for ``$Grandpa_HOME/agents/<agent_name>/few_shot.json``.
    Expected format: ``[{"input": "Q", "output": "A"}, ...]``.
    """
    home = _Grandpa_home()
    fs_path = home / "agents" / agent_name / "few_shot.json"
    if not fs_path.exists():
        return []
    try:
        data = json.loads(fs_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("few_shot.json for %s is not a list", agent_name)
            return []
        logger.info(
            "Loaded %d few-shot exemplars for %s from %s",
            len(data),
            agent_name,
            fs_path,
        )
        return data
    except Exception:
        logger.warning(
            "Failed to read few-shot exemplars at %s",
            fs_path,
            exc_info=True,
        )
        return []
