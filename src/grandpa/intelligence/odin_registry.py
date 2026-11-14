"""One registry for every Odin model role, Ollama or not.

``grandpa_models.GRANDPA_MODEL_ROLES`` holds the language-model roles the engine
can chat with. Grandpa also depends on models that never go through chat: a
safety classifier (guard), speech-to-text (ears), text-to-speech (voice) and the
embedding model behind memory. This module lists all of them in one place, with
how each one is installed and how to tell whether it is, so ``grandpa models``
and ``grandpa models setup`` answer from the same table the docs describe.

Status is reported, never assumed: an Ollama role is ``installed`` only when the
running Ollama lists its tag, and the non-Ollama roles check that their Python
package can be imported.
"""

from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from grandpa.intelligence.grandpa_models import GRANDPA_MODEL_ROLES, get_model_role

#: Where the ``Modelfile.<role>`` recipes live in a source checkout.
DEFAULT_MODELFILE_DIR = Path(__file__).resolve().parents[3] / "models"

MEMORY_MODEL_TAG = "grandpa-memory:latest"
MEMORY_SOURCE_TAG = "nomic-embed-text:latest"

INSTALLED = "installed"
MISSING = "missing"
FALLBACK = "fallback"  # not installed under its Grandpa name, but its source is


@dataclass(frozen=True, slots=True)
class OdinRole:
    """One Odin role and how Grandpa provides it."""

    role: str
    name: str
    runtime: str  # "ollama", "faster-whisper" or "tts"
    purpose: str
    modelfile: str = ""  # Modelfile.<x> under models/, for Ollama roles built locally
    source_tag: str = ""  # Ollama tag copied to ``name`` (memory) or FROM line
    fallback_tag: str = ""  # tag used when ``name`` is missing
    python_module: str = ""  # import name for non-Ollama runtimes
    install_hint: str = ""

    @property
    def is_ollama(self) -> bool:
        return self.runtime == "ollama"


@dataclass(slots=True)
class RoleStatus:
    role: OdinRole
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "role": self.role.role,
            "name": self.role.name,
            "runtime": self.role.runtime,
            "purpose": self.role.purpose,
            "status": self.status,
            "detail": self.detail,
        }


def _llm_role(role: str, modelfile: str) -> OdinRole:
    entry = get_model_role(role)
    assert entry is not None, role
    return OdinRole(
        role=role,
        name=entry.ollama_tag,
        runtime="ollama",
        purpose=entry.description,
        modelfile=modelfile,
    )


ODIN_ROLES: tuple[OdinRole, ...] = (
    _llm_role("brain", "Modelfile.brain"),
    _llm_role("fast", "Modelfile.fast"),
    _llm_role("mini", "Modelfile.mini"),
    _llm_role("coder", "Modelfile.coder"),
    _llm_role("eyes", "Modelfile.eyes"),
    OdinRole(
        role="guard",
        name="grandpa-guard:latest",
        runtime="ollama",
        purpose="Safety classifier for actions",
        modelfile="Modelfile.guard",
    ),
    OdinRole(
        role="memory",
        name=MEMORY_MODEL_TAG,
        runtime="ollama",
        purpose="Embeddings for semantic memory",
        source_tag=MEMORY_SOURCE_TAG,
        fallback_tag=MEMORY_SOURCE_TAG,
    ),
    OdinRole(
        role="ears",
        name="grandpa-ears",
        runtime="faster-whisper",
        purpose="Speech-to-text (size from speech.model)",
        python_module="faster_whisper",
        install_hint='uv pip install -e ".[speech]"',
    ),
    OdinRole(
        role="voice",
        name="grandpa-voice",
        runtime="tts",
        purpose="Text-to-speech (backend from tts.backend)",
        install_hint='uv pip install -e ".[voice]"',
    ),
)

_BY_ROLE = {entry.role: entry for entry in ODIN_ROLES}


def llm_roles_without_odin_row() -> set[str]:
    """Chat roles in ``GRANDPA_MODEL_ROLES`` that this table forgot (tested)."""

    return {
        entry.role
        for entry in GRANDPA_MODEL_ROLES
        if "embeddings" not in entry.capabilities
    } - set(_BY_ROLE)


def get_odin_role(role: str) -> OdinRole | None:
    return _BY_ROLE.get(str(role or "").strip().casefold())


def normalize_tag(tag: str) -> str:
    text = str(tag or "").strip()
    return text if ":" in text else f"{text}:latest"


# --------------------------------------------------------------------------
# Ollama access, behind a small protocol so tests use a fake.


class OllamaClient(Protocol):
    def list_tags(self) -> set[str]: ...

    def create(self, name: str, modelfile: Path) -> None: ...

    def copy(self, source: str, destination: str) -> None: ...

    def pull(self, name: str) -> None: ...


class HttpOllamaClient:
    """Talks to a running Ollama. ``create`` uses the ``ollama`` CLI, which
    pulls the Modelfile's FROM model when it is not present yet."""

    def __init__(self, host: str = "http://127.0.0.1:11434", timeout: float = 10.0):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def list_tags(self) -> set[str]:
        import httpx

        response = httpx.get(f"{self.host}/api/tags", timeout=self.timeout)
        response.raise_for_status()
        return {
            normalize_tag(item.get("name", ""))
            for item in response.json().get("models", [])
            if item.get("name")
        }

    def create(self, name: str, modelfile: Path) -> None:
        subprocess.run(
            ["ollama", "create", name.removesuffix(":latest"), "-f", str(modelfile)],
            check=True,
        )

    def copy(self, source: str, destination: str) -> None:
        import httpx

        response = httpx.post(
            f"{self.host}/api/copy",
            json={"source": source, "destination": destination},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def pull(self, name: str) -> None:
        import httpx

        response = httpx.post(
            f"{self.host}/api/pull",
            json={"name": name, "stream": False},
            timeout=None,
        )
        response.raise_for_status()


# --------------------------------------------------------------------------
# Status


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _speech_model_size() -> str:
    try:
        from grandpa.core.config import load_config

        return str(load_config().speech.model or "base.en")
    except Exception:
        return "base.en"


def _tts_backend() -> str:
    try:
        from grandpa.core.config import load_config

        return str(load_config().tts.backend or "pyttsx3")
    except Exception:
        return "pyttsx3"


def role_statuses(
    tags: Iterable[str] | None,
    *,
    module_available: Callable[[str], bool] = _module_available,
    speech_model: Callable[[], str] = _speech_model_size,
    tts_backend: Callable[[], str] = _tts_backend,
) -> list[RoleStatus]:
    """Status of every role. ``tags`` is None when Ollama could not be reached."""

    installed = {normalize_tag(t) for t in tags} if tags is not None else None
    statuses: list[RoleStatus] = []
    for entry in ODIN_ROLES:
        if entry.is_ollama:
            if installed is None:
                statuses.append(RoleStatus(entry, MISSING, "Ollama not reachable"))
            elif normalize_tag(entry.name) in installed:
                statuses.append(RoleStatus(entry, INSTALLED))
            elif entry.fallback_tag and normalize_tag(entry.fallback_tag) in installed:
                statuses.append(
                    RoleStatus(entry, FALLBACK, f"using {entry.fallback_tag}")
                )
            else:
                statuses.append(RoleStatus(entry, MISSING))
        elif entry.runtime == "faster-whisper":
            size = speech_model()
            ok = module_available(entry.python_module)
            statuses.append(
                RoleStatus(
                    entry,
                    INSTALLED if ok else MISSING,
                    f"size {size}" if ok else f"size {size}; {entry.install_hint}",
                )
            )
        else:  # tts
            backend = tts_backend()
            module = {"pyttsx3": "pyttsx3", "kokoro": "kokoro"}.get(backend, "")
            ok = module_available(module) if module else True
            detail = f"backend {backend}"
            if not ok:
                detail += f"; {entry.install_hint}"
            statuses.append(RoleStatus(entry, INSTALLED if ok else MISSING, detail))
    return statuses


def resolve_memory_embedding_tag(tags: Iterable[str]) -> str:
    """grandpa-memory when installed, otherwise the original embedding tag."""

    installed = {normalize_tag(t) for t in tags}
    if MEMORY_MODEL_TAG in installed:
        return MEMORY_MODEL_TAG
    return MEMORY_SOURCE_TAG


# --------------------------------------------------------------------------
# Setup


@dataclass(slots=True)
class SetupStep:
    role: str
    action: str  # "create", "copy", "pull+copy", "skip"
    command: str
    detail: str = ""
    done: bool = False
    error: str = ""


@dataclass(slots=True)
class SetupPlan:
    steps: list[SetupStep] = field(default_factory=list)

    @property
    def runnable(self) -> list[SetupStep]:
        return [step for step in self.steps if step.action != "skip"]


def plan_setup(
    tags: Iterable[str], modelfile_dir: Path = DEFAULT_MODELFILE_DIR
) -> SetupPlan:
    """What ``grandpa models setup`` would do for every missing Ollama role."""

    installed = {normalize_tag(t) for t in tags}
    plan = SetupPlan()
    for entry in ODIN_ROLES:
        if not entry.is_ollama or normalize_tag(entry.name) in installed:
            continue
        short = entry.name.removesuffix(":latest")
        if entry.modelfile:
            path = modelfile_dir / entry.modelfile
            if not path.is_file():
                plan.steps.append(
                    SetupStep(entry.role, "skip", "", f"{path} not found")
                )
                continue
            plan.steps.append(
                SetupStep(entry.role, "create", f"ollama create {short} -f {path}")
            )
        elif entry.source_tag:
            source = entry.source_tag.removesuffix(":latest")
            command = f"ollama cp {source} {short}"
            if normalize_tag(entry.source_tag) in installed:
                plan.steps.append(SetupStep(entry.role, "copy", command))
            else:
                plan.steps.append(
                    SetupStep(
                        entry.role,
                        "pull+copy",
                        f"ollama pull {source}; {command}",
                    )
                )
    return plan


def run_setup(
    plan: SetupPlan,
    client: OllamaClient,
    modelfile_dir: Path = DEFAULT_MODELFILE_DIR,
) -> SetupPlan:
    """Execute a plan. One failing role does not stop the others."""

    for step in plan.runnable:
        entry = _BY_ROLE[step.role]
        try:
            if step.action == "create":
                client.create(entry.name, modelfile_dir / entry.modelfile)
            elif step.action == "copy":
                client.copy(entry.source_tag, entry.name)
            elif step.action == "pull+copy":
                client.pull(entry.source_tag)
                client.copy(entry.source_tag, entry.name)
            step.done = True
        except Exception as exc:  # report and carry on
            step.error = str(exc) or exc.__class__.__name__
            if entry.fallback_tag:
                step.detail = f"falling back to {entry.fallback_tag}"
    return plan


__all__ = [
    "DEFAULT_MODELFILE_DIR",
    "FALLBACK",
    "HttpOllamaClient",
    "INSTALLED",
    "MEMORY_MODEL_TAG",
    "MEMORY_SOURCE_TAG",
    "MISSING",
    "ODIN_ROLES",
    "OdinRole",
    "OllamaClient",
    "RoleStatus",
    "SetupPlan",
    "SetupStep",
    "get_odin_role",
    "normalize_tag",
    "plan_setup",
    "resolve_memory_embedding_tag",
    "role_statuses",
    "run_setup",
]
