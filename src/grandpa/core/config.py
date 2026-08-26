"""Configuration loading, hardware detection, and engine recommendation.

User configuration lives at ``~/.grandpa/config.toml``.  ``load_config()``
detects hardware, fills sensible defaults, then overlays any user overrides
found in the TOML file.
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Hardware dataclasses
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path(
    os.environ.get("GRANDPA_HOME", Path.home() / ".grandpa")
).expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
CONFIG_RECOVERY_MESSAGE = (
    "Configuration was invalid and was backed up. Safe defaults were loaded."
)
CONFIG_RECOVERY_FAILED_MESSAGE = (
    "Configuration was invalid but could not be backed up. "
    "Safe defaults were loaded for this session."
)
_CONFIG_RECOVERY_WARNINGS: list[str] = []

#: Config keys that were accepted but never read by any code path, mapped to
#: what actually governs the behaviour now. They are removed rather than left
#: in place: a security option that looks configurable and does nothing is
#: worse than no option at all. Loading a config that still sets one emits a
#: warning through :func:`consume_config_recovery_warnings` so the setting is
#: not silently dropped.
REMOVED_CONFIG_KEYS: dict[str, str] = {
    "security.enforce_tool_confirmation": (
        "never read; tool confirmation is decided per-tool by "
        "ToolSpec.requires_confirmation and the executor's confirm_callback"
    ),
    "security.merkle_audit": "never read; the audit log has no Merkle mode",
    "security.signing_key_path": "never read; skill signing loads its own key",
    "security.ssrf_protection": (
        "never read; SSRF checks are unconditional in the http_request, "
        "browser and web_search tools and cannot be disabled"
    ),
    "security.rate_limit_enabled": (
        "never read; no request path consults the rate limiter"
    ),
    "security.rate_limit_rpm": "never read; see security.rate_limit_enabled",
    "security.rate_limit_burst": "never read; see security.rate_limit_enabled",
    "security.local_engine_bypass": "never read; no engine path consults it",
    "security.local_tool_bypass": "never read; no tool path consults it",
    "security.vault_key_path": (
        "never read; the vault always uses ~/.grandpa/.vault_key"
    ),
}


def _warn_about_removed_keys(data: Dict[str, Any]) -> None:
    """Queue a warning for each removed key still present in *data*."""
    for dotted, reason in REMOVED_CONFIG_KEYS.items():
        section, _, key = dotted.partition(".")
        values = data.get(section)
        if isinstance(values, dict) and key in values:
            _CONFIG_RECOVERY_WARNINGS.append(
                f"Ignoring removed config key '{dotted}' — {reason}. "
                "Delete it from config.toml to silence this warning."
            )


def _ensure_config_dir() -> Path:
    """Ensure the config directory exists with restrictive permissions."""
    from grandpa.security.file_utils import secure_mkdir

    return secure_mkdir(DEFAULT_CONFIG_DIR)


def consume_config_recovery_warnings() -> list[str]:
    """Return and clear pending user-facing configuration recovery notices."""

    warnings = list(_CONFIG_RECOVERY_WARNINGS)
    _CONFIG_RECOVERY_WARNINGS.clear()
    return warnings


def _timestamped_backup_path(path: Path, marker: str = "corrupt") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.{marker}-{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{marker}-{timestamp}-{suffix}")
        suffix += 1
    return candidate


def _atomic_write_text(path: Path, content: str) -> None:
    """Write UTF-8 text with a durable same-directory atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _recover_invalid_config(path: Path, hw: "HardwareInfo", engine: str) -> Path:
    """Preserve an invalid config and atomically replace it with safe defaults."""

    backup = _timestamped_backup_path(path)
    os.replace(path, backup)
    try:
        _atomic_write_text(path, generate_minimal_toml(hw, engine))
    except Exception:
        if not path.exists() and backup.exists():
            os.replace(backup, path)
        raise
    _CONFIG_RECOVERY_WARNINGS.append(CONFIG_RECOVERY_MESSAGE)
    return backup


@dataclass(slots=True)
class GpuInfo:
    """Detected GPU metadata."""

    vendor: str = ""
    name: str = ""
    vram_gb: float = 0.0
    compute_capability: str = ""
    count: int = 0


@dataclass(slots=True)
class HardwareInfo:
    """Detected system hardware."""

    platform: str = ""
    cpu_brand: str = ""
    cpu_count: int = 0
    ram_gb: float = 0.0
    gpu: Optional[GpuInfo] = None


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str]) -> str:
    """Run a command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,  # noqa: S603
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _detect_nvidia_gpu() -> Optional[GpuInfo]:
    if not shutil.which("nvidia-smi"):
        return None
    raw = _run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,count,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    if not raw:
        return None
    try:
        first_line = raw.splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        name = parts[0]
        vram_mb = float(parts[1])
        count = int(parts[2])
        compute_capability = parts[3] if len(parts) > 3 else ""
        return GpuInfo(
            vendor="nvidia",
            name=name,
            vram_gb=round(vram_mb / 1024, 1),
            compute_capability=compute_capability,
            count=count,
        )
    except (IndexError, ValueError):
        return None


def _detect_amd_gpu() -> Optional[GpuInfo]:
    if not shutil.which("rocm-smi"):
        return None
    raw = _run_cmd(["rocm-smi", "--showproductname"])
    if not raw:
        return None
    name = raw.splitlines()[0] if raw else "AMD GPU"

    # Parse VRAM from rocm-smi --showmeminfo vram
    vram_gb = 0.0
    try:
        vram_raw = _run_cmd(["rocm-smi", "--showmeminfo", "vram"])
        for line in vram_raw.splitlines():
            if "Total Memory (B):" in line:
                vram_bytes = int(line.split(":")[-1].strip())
                vram_gb = round(vram_bytes / (1024**3), 1)
                break
    except (ValueError, IndexError):
        vram_gb = 0.0

    # Parse GPU count from rocm-smi --showallinfo
    count = 1
    try:
        allinfo_raw = _run_cmd(["rocm-smi", "--showallinfo"])
        import re

        gpu_ids = set(re.findall(r"GPU\[(\d+)\]", allinfo_raw))
        if gpu_ids:
            count = len(gpu_ids)
    except (ValueError, IndexError):
        count = 1

    return GpuInfo(vendor="amd", name=name, vram_gb=vram_gb, count=count)


def _detect_apple_gpu() -> Optional[GpuInfo]:
    if platform.system() != "Darwin":
        return None
    raw = _run_cmd(["system_profiler", "SPDisplaysDataType"])
    if "Apple" not in raw:
        return None
    # Rough extraction — "Apple M2 Max" etc.
    ram_gb = _total_ram_gb()
    for line in raw.splitlines():
        line = line.strip()
        if "Chipset Model" in line:
            name = line.split(":")[-1].strip()
            return GpuInfo(vendor="apple", name=name, vram_gb=ram_gb, count=1)
    return GpuInfo(vendor="apple", name="Apple Silicon", vram_gb=ram_gb, count=1)


def _detect_cpu_brand() -> str:
    """Best-effort CPU brand string."""
    if platform.system() == "Darwin":
        brand = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if brand:
            return brand
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _total_ram_gb() -> float:
    try:
        if platform.system() == "Darwin":
            raw = _run_cmd(["sysctl", "-n", "hw.memsize"])
            return round(int(raw) / (1024**3), 1) if raw else 0.0
        if platform.system() == "Windows":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024**3), 1)
            return 0.0
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
    except (OSError, ValueError, AttributeError):
        pass
    return 0.0


def detect_hardware() -> HardwareInfo:
    """Auto-detect hardware capabilities with graceful fallbacks."""
    gpu = _detect_nvidia_gpu() or _detect_amd_gpu() or _detect_apple_gpu()
    return HardwareInfo(
        platform=platform.system().lower(),
        cpu_brand=_detect_cpu_brand(),
        cpu_count=os.cpu_count() or 1,
        ram_gb=_total_ram_gb(),
        gpu=gpu,
    )


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


def recommend_engine(hw: HardwareInfo) -> str:
    """Return the supported local inference runtime."""
    return "ollama"


def _available_memory_gb(hw: HardwareInfo) -> float:
    """Return usable memory in GB for model loading."""
    gpu = hw.gpu
    if gpu and gpu.vram_gb > 0:
        return gpu.vram_gb * max(gpu.count, 1) * 0.9
    if hw.ram_gb > 0:
        return (hw.ram_gb - 4) * 0.8
    return 0.0


_MODEL_TIER_FALLBACK = "grandpa-mini:latest"


def recommend_model(hw: HardwareInfo, engine: str) -> str:
    """Suggest a default model for the selected engine and hardware.

    Uses the canonical low-resource Grandpa Odin role for local Ollama.
    """
    if engine != "ollama":
        return ""
    if _available_memory_gb(hw) <= 0:
        return ""
    return _MODEL_TIER_FALLBACK


def estimated_download_gb(parameter_count_b: float) -> float:
    """Estimate download size in GB for Q4_K_M quantized model."""
    return parameter_count_b * 0.5 * 1.1


# ---------------------------------------------------------------------------
# Configuration hierarchy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OllamaEngineConfig:
    """Per-engine config for Ollama."""

    host: str = ""
    num_ctx: int = 8192


@dataclass(slots=True)
class NativeEngineConfig:
    """Per-engine config for Native in-process llama.cpp / GGUF backend."""

    models_dir: str = ""
    n_threads: int = 0
    n_gpu_layers: int = 0
    n_ctx: int = 8192
    use_mmap: bool = True
    use_mlock: bool = False
    verbose: bool = False


@dataclass
class EngineConfig:
    """Inference settings for local and remote runtimes."""

    default: str = "ollama"
    ollama: OllamaEngineConfig = field(default_factory=OllamaEngineConfig)
    native: NativeEngineConfig = field(default_factory=NativeEngineConfig)

    @property
    def ollama_host(self) -> str:
        """Deprecated: use ``engine.ollama.host``."""
        return self.ollama.host

    @ollama_host.setter
    def ollama_host(self, value: str) -> None:
        self.ollama.host = value


@dataclass(slots=True)
class IntelligenceConfig:
    """The model — identity, paths, quantization, and generation defaults."""

    default_model: str = "grandpa-mini:latest"
    fallback_model: str = ""
    model_path: str = ""  # Local weights (HF repo, GGUF file, etc.)
    checkpoint_path: str = ""  # Checkpoint/adapter path
    quantization: str = "none"  # none, fp8, int8, int4, gguf_q4, gguf_q8
    preferred_engine: str = ""  # Reserved; Ollama is the supported runtime.
    provider: str = "local"
    # Generation defaults (overridable per-call)
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.0
    stop_sequences: str = ""  # Comma-separated stop strings


@dataclass(slots=True)
class RoutingLearningConfig:
    """Routing sub-policy config within Learning."""

    policy: str = "heuristic"  # heuristic | learned
    min_samples: int = 5  # Min traces before trusting learned routing


@dataclass
class LearningConfig:
    """Runtime query-routing settings."""

    enabled: bool = True
    routing: RoutingLearningConfig = field(default_factory=RoutingLearningConfig)

    @property
    def default_policy(self) -> str:
        """Backward-compatible alias for the routing policy."""
        return self.routing.policy

    @default_policy.setter
    def default_policy(self, value: str) -> None:
        self.routing.policy = value


@dataclass(slots=True)
class StorageConfig:
    """Storage (memory) backend settings."""

    default_backend: str = "sqlite"
    db_path: str = str(DEFAULT_CONFIG_DIR / "memory.db")
    context_top_k: int = 5
    context_min_score: float = 0.0
    context_max_tokens: int = 2048
    chunk_size: int = 512
    chunk_overlap: int = 64


# Backward-compatibility alias
MemoryConfig = StorageConfig


@dataclass(slots=True)
class MCPConfig:
    """MCP (Model Context Protocol) settings."""

    enabled: bool = True
    servers: str = ""  # JSON list of MCP server configs


@dataclass(slots=True)
class BrowserConfig:
    """Browser automation settings (Playwright)."""

    headless: bool = True
    timeout_ms: int = 30000
    viewport_width: int = 1280
    viewport_height: int = 720


@dataclass(slots=True)
class ToolsConfig:
    """Tools primitive settings — wraps storage and MCP configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    enabled: str = ""  # comma-separated default tools


@dataclass
class AgentConfig:
    """Agent harness settings — orchestration, tools, system prompt."""

    default_agent: str = "simple"
    max_turns: int = 10
    tools: str = ""  # comma-separated tool names
    objective: str = ""  # concise purpose for routing/learning/docs
    system_prompt: str = ""  # inline system prompt (takes precedence if set)
    system_prompt_path: str = ""  # path to system prompt file (.txt, .md)
    context_from_memory: bool = True  # inject relevant memory context into prompts
    default_system_prompt: str = (
        "You are a helpful AI assistant running locally on the user's own "
        "hardware through grandpa. You are not a cloud service. Respond "
        "helpfully, concisely, and accurately."
    )

    # Backward-compat property for old field name
    @property
    def default_tools(self) -> str:
        """Deprecated: use ``agent.tools``."""
        return self.tools

    @default_tools.setter
    def default_tools(self, value: str) -> None:
        self.tools = value


@dataclass(slots=True)
class ServerAuthConfig:
    """Local API authentication settings.

    ``grandpa serve`` requires a bearer key by default. When this is empty a
    key is generated on first run and written back here.
    """

    api_key: str = ""


@dataclass(slots=True)
class ServerConfig:
    """API server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    agent: str = "orchestrator"
    model: str = ""
    workers: int = 1
    cors_origins: list = field(default_factory=list)
    auth: ServerAuthConfig = field(default_factory=ServerAuthConfig)


@dataclass(slots=True)
class TelemetryConfig:
    """Telemetry persistence settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "telemetry.db")
    gpu_metrics: bool = False
    gpu_poll_interval_ms: int = 50
    energy_vendor: str = ""  # auto-detect or force "nvidia"/"amd"/"apple"/"cpu_rapl"
    warmup_samples: int = 0
    steady_state_window: int = 5
    steady_state_threshold: float = 0.05


@dataclass(slots=True)
class TracesConfig:
    """Trace system settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "traces.db")


@dataclass(slots=True)
class CapabilitiesConfig:
    """RBAC capability system settings."""

    enabled: bool = False
    policy_path: str = ""


@dataclass(slots=True)
class SecurityConfig:
    """Security guardrails settings.

    Every field here is read by :func:`grandpa.security.setup_security` or the
    doctor. Options that no code consulted were removed rather than left
    looking configurable — see :data:`REMOVED_CONFIG_KEYS`.

    Note that SSRF protection is *not* configurable: ``check_ssrf`` is applied
    unconditionally by the http_request, browser and web_search tools. It has
    no off switch by design.
    """

    enabled: bool = True
    scan_input: bool = True
    scan_output: bool = True
    mode: str = "redact"  # "redact" | "warn" | "block"
    secret_scanner: bool = True
    pii_scanner: bool = True
    audit_log_path: str = str(DEFAULT_CONFIG_DIR / "audit.db")
    profile: str = ""
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)


# ---------------------------------------------------------------------------
# Security profile presets
# ---------------------------------------------------------------------------

_SECURITY_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    # Only keys that some code path actually reads. The profiles previously
    # also set rate_limit_* and local_*_bypass, none of which were ever
    # consulted — see REMOVED_CONFIG_KEYS.
    "personal": {
        "security": {"mode": "redact"},
        "server": {"host": "127.0.0.1"},
    },
    "shared": {
        "security": {"mode": "redact"},
        "server": {"host": "127.0.0.1"},
    },
    "server": {
        "security": {"mode": "block"},
        "server": {"host": "0.0.0.0"},
    },
}


def apply_security_profile(
    security_cfg: "SecurityConfig",
    server_cfg: "ServerConfig | None",
    *,
    overrides: "set[str] | None" = None,
) -> None:
    """Expand a named security profile into config fields.

    Fields in *overrides* (explicitly set by the user in TOML) are
    not overwritten by the profile.
    """
    profile = security_cfg.profile
    if not profile:
        return

    if profile not in _SECURITY_PROFILES:
        raise ValueError(
            f"Unknown security profile '{profile}'. "
            f"Valid profiles: {', '.join(_SECURITY_PROFILES)}"
        )

    _overrides = overrides or set()
    pdef = _SECURITY_PROFILES[profile]

    for key, value in pdef.get("security", {}).items():
        if key not in _overrides and hasattr(security_cfg, key):
            setattr(security_cfg, key, value)

    if server_cfg is not None:
        for key, value in pdef.get("server", {}).items():
            if key not in _overrides and hasattr(server_cfg, key):
                setattr(server_cfg, key, value)


@dataclass(slots=True)
class SchedulerConfig:
    """Task scheduler settings."""

    enabled: bool = False
    poll_interval: int = 60
    db_path: str = ""  # Defaults to ~/.grandpa/scheduler.db


@dataclass(slots=True)
class WorkflowConfig:
    """Workflow engine settings."""

    enabled: bool = False
    max_parallel: int = 4
    default_node_timeout: int = 300


@dataclass(slots=True)
class SessionConfig:
    """Local API and assistant session settings."""

    enabled: bool = False
    max_age_hours: float = 24.0
    consolidation_threshold: int = 100
    db_path: str = str(DEFAULT_CONFIG_DIR / "sessions.db")


@dataclass(slots=True)
class A2AConfig:
    """Agent-to-Agent protocol settings."""

    enabled: bool = False


@dataclass(slots=True)
class OperatorsConfig:
    """Operator lifecycle settings."""

    enabled: bool = False
    manifests_dir: str = "~/.grandpa/operators"
    auto_activate: str = ""  # Comma-separated operator IDs


@dataclass(slots=True)
class SpeechConfig:
    """Speech-to-text settings."""

    backend: str = "auto"  # "auto", "faster-whisper", "openai", "deepgram"
    model: str = "base"  # Whisper model size: tiny, base, small, medium, large-v3
    language: str = ""  # Empty = auto-detect
    device: str = "auto"  # "auto", "cpu", "cuda"
    compute_type: str = "auto"  # "auto", "float16", "int8", "float32"


@dataclass(slots=True)
class TTSConfig:
    """Text-to-speech settings."""

    backend: str = "kokoro"  # Default fallback backend
    enabled: bool = True


@dataclass(slots=True)
class GrandpaVoiceConfig:
    """Grandpa local cloned voice TTS engine settings."""

    engine: str = "f5"
    device: str = "cpu"
    voice_id: str = "grandpa"
    reference_audio: str = ""
    reference_text: str = ""
    service_url: str = "http://127.0.0.1:8765"
    synthesis_timeout_seconds: float = 600.0
    nfe_step: int = 8
    cpu_threads: int = 4
    cfg_strength: float = 0.0
    character_voice: bool = True
    pitch_semitones: float = -2.0
    character_speed: float = 0.92
    target_lufs: float = -14.5
    true_peak_db: float = -1.0
    compression: bool = True
    eq_profile: str = "grandpa_deep_clear"
    runtime_python: str = ""
    model_cache: str = ""


@dataclass(slots=True)
class AgentManagerConfig:
    """Persistent agent manager settings."""

    enabled: bool = True
    db_path: str = str(DEFAULT_CONFIG_DIR / "agents.db")


@dataclass(slots=True)
class MemoryFilesConfig:
    """Persistent memory-file paths and nudge settings."""

    soul_path: str = "~/.grandpa/SOUL.md"
    memory_path: str = "~/.grandpa/MEMORY.md"
    user_path: str = "~/.grandpa/USER.md"
    nudge_interval: int = 10


@dataclass(slots=True)
class SystemPromptConfig:
    """Limits and strategy for system-prompt assembly."""

    soul_max_chars: int = 4000
    memory_max_chars: int = 2500
    user_max_chars: int = 1500
    skill_desc_max_chars: int = 60
    truncation_strategy: str = "head_tail"


@dataclass(slots=True)
class CompressionConfig:
    """Configuration for context compression."""

    enabled: bool = True
    threshold: float = 0.50
    strategy: str = "session_consolidation"


@dataclass(slots=True)
class SkillsConfig:
    """Configuration for trusted local procedural skills."""

    enabled: bool = True
    skills_dir: str = "~/.grandpa/skills/"
    active: str = "*"
    auto_discover: bool = True
    max_depth: int = 5


@dataclass(slots=True)
class UserConfig:
    """User-facing identity used by interactive interfaces."""

    username: str = "Username"
    title: str = ""
    onboarding_completed: bool = False


@dataclass
class GrandpaConfig:
    """Top-level configuration for grandpa."""

    installed_at: str = ""
    installer_version: str = ""
    fullscreen: bool = True
    last_used_mode: str = ""
    hardware: HardwareInfo = field(default_factory=HardwareInfo)
    engine: EngineConfig = field(default_factory=EngineConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    traces: TracesConfig = field(default_factory=TracesConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    a2a: A2AConfig = field(default_factory=A2AConfig)
    operators: OperatorsConfig = field(default_factory=OperatorsConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    grandpa_voice: GrandpaVoiceConfig = field(default_factory=GrandpaVoiceConfig)
    agent_manager: AgentManagerConfig = field(default_factory=AgentManagerConfig)
    memory_files: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)
    system_prompt: SystemPromptConfig = field(default_factory=SystemPromptConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    user: UserConfig = field(default_factory=UserConfig)

    @property
    def memory(self) -> StorageConfig:
        """Backward-compatible accessor — canonical location is tools.storage."""
        return self.tools.storage

    @memory.setter
    def memory(self, value: StorageConfig) -> None:
        """Backward-compatible setter."""
        self.tools.storage = value


# ---------------------------------------------------------------------------
# Config key validation
# ---------------------------------------------------------------------------

# Sections that users may set via ``Grandpa config set``.
# ``hardware`` is auto-detected and not user-settable.
_SETTABLE_SECTIONS = frozenset(GrandpaConfig.__dataclass_fields__.keys()) - {"hardware"}


def validate_config_key(dotted_key: str) -> type:
    """Validate a dotted config key and return the leaf field's Python type.

    Raises :class:`ValueError` when the key does not map to a known field.
    The function walks the ``GrandpaConfig`` dataclass hierarchy using
    ``dataclasses.fields()``.

    Examples::

        validate_config_key("engine.ollama.host")      # -> str
        validate_config_key("intelligence.temperature") # -> float
    """
    from dataclasses import fields as dc_fields

    parts = dotted_key.split(".")
    if len(parts) < 2:
        raise ValueError(
            f"Config key must have at least two segments (e.g. engine.default), "
            f"got: {dotted_key!r}"
        )

    if parts[0] not in _SETTABLE_SECTIONS:
        raise ValueError(
            f"Unknown config key: {dotted_key!r} "
            f"(valid top-level sections: {sorted(_SETTABLE_SECTIONS)})"
        )

    # Walk the dataclass tree
    current_cls = GrandpaConfig
    for i, part in enumerate(parts):
        field_map = {f.name: f for f in dc_fields(current_cls)}
        if part not in field_map:
            path_so_far = ".".join(parts[: i + 1])
            raise ValueError(
                f"Unknown config key: {dotted_key!r} "
                f"(no field {part!r} at {path_so_far}; "
                f"valid fields: {sorted(field_map.keys())})"
            )
        fld = field_map[part]
        # Resolve the type — unwrap Optional, etc.
        fld_type = fld.type
        if isinstance(fld_type, str):
            # Evaluate forward references in the config module namespace
            import grandpa.core.config as _cfg_mod

            fld_type = eval(fld_type, vars(_cfg_mod))  # noqa: S307

        if i == len(parts) - 1:
            # Leaf — return the primitive type
            return fld_type
        else:
            # Must be a nested dataclass
            if not hasattr(fld_type, "__dataclass_fields__"):
                path_so_far = ".".join(parts[: i + 1])
                raise ValueError(
                    f"Unknown config key: {dotted_key!r} "
                    f"({path_so_far} is a leaf of type {fld_type.__name__}, "
                    f"not a section)"
                )
            current_cls = fld_type

    # Should not reach here, but satisfy type checker
    raise ValueError(f"Unknown config key: {dotted_key!r}")


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _apply_toml_section(target: Any, section: Dict[str, Any]) -> None:
    """Overlay TOML key/value pairs onto a dataclass instance.

    Recursively handles nested dicts when the target attribute is itself
    a dataclass.  Normalises TOML arrays to comma-separated strings — both
    for dataclass fields annotated as ``str`` and for backward-compat
    property setters that expect string input.
    """
    for key, value in section.items():
        if hasattr(target, key):
            if isinstance(value, dict):
                nested = getattr(target, key)
                if hasattr(nested, "__dataclass_fields__"):
                    _apply_toml_section(nested, value)
                else:
                    setattr(target, key, value)
            else:
                if isinstance(target, OllamaEngineConfig) and key == "num_ctx":
                    value = validate_ollama_num_ctx(value)
                if isinstance(target, GrandpaVoiceConfig):
                    value = validate_grandpa_voice_setting(key, value)
                # Normalise TOML arrays → comma-separated string.
                # Covers both real dataclass fields and backward-compat
                # property setters (e.g. reward_weights, default_tools).
                if isinstance(value, list):
                    is_str_field = False
                    if hasattr(target, "__dataclass_fields__"):
                        field_obj = target.__dataclass_fields__.get(key)
                        if field_obj is not None and field_obj.type in ("str", str):
                            is_str_field = True
                        elif field_obj is None:
                            # Property, not a real field — normalise to string
                            is_str_field = True
                    if is_str_field:
                        value = ",".join(str(v) for v in value)
                setattr(target, key, value)


def validate_ollama_num_ctx(value: Any) -> int:
    """Return a safe Ollama context length from configuration input."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("engine.ollama.num_ctx must be an integer")
    if not 256 <= value <= 262_144:
        raise ValueError("engine.ollama.num_ctx must be between 256 and 262144")
    return value


def validate_grandpa_voice_setting(key: str, value: Any) -> Any:
    """Validate bounded F5 inference settings loaded from user configuration."""
    if key in {"nfe_step", "cpu_threads"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"grandpa_voice.{key} must be an integer")
        upper_bound = 64
        if not 1 <= value <= upper_bound:
            raise ValueError(f"grandpa_voice.{key} must be between 1 and {upper_bound}")
    elif key == "cfg_strength":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("grandpa_voice.cfg_strength must be a number")
        value = float(value)
        if not 0.0 <= value <= 10.0:
            raise ValueError("grandpa_voice.cfg_strength must be between 0.0 and 10.0")
    elif key in {"character_voice", "compression"}:
        if not isinstance(value, bool):
            raise ValueError(f"grandpa_voice.{key} must be a boolean")
    elif key in {
        "pitch_semitones",
        "character_speed",
        "target_lufs",
        "true_peak_db",
    }:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"grandpa_voice.{key} must be a number")
        value = float(value)
        bounds = {
            "pitch_semitones": (-4.0, 2.0),
            "character_speed": (0.75, 1.25),
            "target_lufs": (-24.0, -10.0),
            "true_peak_db": (-6.0, -0.1),
        }
        lower, upper = bounds[key]
        if not lower <= value <= upper:
            raise ValueError(f"grandpa_voice.{key} must be between {lower} and {upper}")
    elif key == "eq_profile" and value not in {
        "grandpa_balanced",
        "grandpa_deep",
        "grandpa_balanced_clear",
        "grandpa_deep_clear",
        "grandpa_clarity",
        "grandpa_presence",
        "none",
        "flat",
    }:
        raise ValueError("grandpa_voice.eq_profile is not supported")
    return value


def _migrate_toml_data(data: Dict[str, Any], cfg: "GrandpaConfig") -> None:
    """Migrate old-format TOML keys to new structure in-place.

    Handles cross-section moves that can't be solved by backward-compat
    properties alone (e.g. ``agent.temperature`` → ``intelligence.temperature``).
    """
    # agent.temperature / agent.max_tokens → intelligence.*
    if "agent" in data:
        agent_data = data["agent"]
        intel_data = data.setdefault("intelligence", {})
        for moved_key in ("temperature", "max_tokens"):
            if moved_key in agent_data:
                intel_data.setdefault(moved_key, agent_data.pop(moved_key))

    # context_injection from memory / tools.storage → agent.context_from_memory
    for src_section in ("memory",):
        src = data.get(src_section, {})
        if isinstance(src, dict) and "context_injection" in src:
            data.setdefault("agent", {}).setdefault(
                "context_from_memory",
                src.pop("context_injection"),
            )

    if "tools" in data:
        tools_data = data["tools"]
        if isinstance(tools_data, dict):
            storage_sub = tools_data.get("storage", {})
            if isinstance(storage_sub, dict) and "context_injection" in storage_sub:
                data.setdefault("agent", {}).setdefault(
                    "context_from_memory",
                    storage_sub.pop("context_injection"),
                )


@functools.lru_cache(maxsize=1)
def load_config(path: Optional[Path] = None) -> GrandpaConfig:
    """Detect hardware, build defaults, overlay TOML overrides.

    Parameters
    ----------
    path:
        Explicit config file. If not set, uses ``Grandpa_CONFIG`` when set,
        otherwise ``~/.grandpa/config.toml``.
    """
    _ensure_config_dir()
    hw = detect_hardware()
    cfg = GrandpaConfig(hardware=hw)
    cfg.engine.default = recommend_engine(hw)

    if path is not None:
        config_path = Path(path)
    elif os.environ.get("Grandpa_CONFIG"):
        config_path = Path(os.environ["Grandpa_CONFIG"]).expanduser().resolve()
    else:
        config_path = DEFAULT_CONFIG_PATH
    if config_path.exists():
        try:
            raw_config = config_path.read_bytes()
            if not raw_config.strip():
                raise tomllib.TOMLDecodeError("Configuration file is empty", "", 0)
            data = tomllib.loads(raw_config.decode("utf-8-sig"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, ValueError):
            try:
                _recover_invalid_config(config_path, hw, cfg.engine.default)
            except OSError:
                _CONFIG_RECOVERY_WARNINGS.append(CONFIG_RECOVERY_FAILED_MESSAGE)
            data = {}

        # Run backward-compat migrations before applying
        _migrate_toml_data(data, cfg)

        # Tell the user about keys that are accepted-but-ignored, rather than
        # dropping them silently in _apply_toml_section's hasattr() check.
        _warn_about_removed_keys(data)

        # All supported top-level sections.
        top_sections = (
            "engine",
            "intelligence",
            "learning",
            "agent",
            "server",
            "telemetry",
            "traces",
            "security",
            "tools",
            "scheduler",
            "workflow",
            "sessions",
            "a2a",
            "operators",
            "speech",
            "tts",
            "grandpa_voice",
            "agent_manager",
            "user",
        )
        for section_name in top_sections:
            if section_name in data:
                _apply_toml_section(
                    getattr(cfg, section_name),
                    data[section_name],
                )

        # Compatibility with the short-lived [profile] display_name/title schema.
        profile_data = data.get("profile")
        user_data = data.get("user") if isinstance(data.get("user"), dict) else {}
        if isinstance(profile_data, dict):
            if "username" not in user_data and profile_data.get("display_name"):
                cfg.user.username = str(profile_data["display_name"])
            if "title" not in user_data and profile_data.get("title") is not None:
                cfg.user.title = str(profile_data["title"])

        # Memory: accept [memory] (old) → maps to tools.storage
        if "memory" in data:
            _apply_toml_section(cfg.tools.storage, data["memory"])

        # Top-level install provenance (installed_at, installer_version, fullscreen, last_used_mode)
        for key in (
            "installed_at",
            "installer_version",
            "fullscreen",
            "last_used_mode",
        ):
            if key in data:
                setattr(cfg, key, data[key])

        # Expand security profile (user TOML overrides take precedence)
        _user_security_keys = set(data.get("security", {}).keys())
        apply_security_profile(cfg.security, cfg.server, overrides=_user_security_keys)

    # Apply profile even without a config file (in case defaults set one)
    if not config_path.exists() and cfg.security.profile:
        apply_security_profile(cfg.security, cfg.server)

    return cfg


# ---------------------------------------------------------------------------
# Default TOML generation (for ``Grandpa init``)
# ---------------------------------------------------------------------------


def generate_minimal_toml(
    hw: HardwareInfo, engine: str | None = None, *, host: str | None = None
) -> str:
    """Render a minimal TOML config with only essential settings."""
    engine = engine or recommend_engine(hw)
    model = recommend_model(hw, engine)
    gpu_comment = ""
    if hw.gpu:
        mem_label = "unified memory" if hw.gpu.vendor == "apple" else "VRAM"
        gpu_comment = f"\n# GPU: {hw.gpu.name} ({hw.gpu.vram_gb} GB {mem_label})"
    if host:
        engine_host_section = f'\n[engine.{engine}]\nhost = "{host}"\n'
    else:
        engine_host_section = (
            f"\n[engine.{engine}]\n"
            f'# host = "http://localhost:11434"  '
            f"# set to remote URL if engine runs elsewhere\n"
        )
    return f"""\
# Grandpa configuration
# Hardware: {hw.cpu_brand} ({hw.cpu_count} cores, {hw.ram_gb} GB RAM){gpu_comment}
# Full reference config: Grandpa init --full

[user]
username = "Username"
onboarding_completed = false

[engine]
default = "{engine}"
{engine_host_section}
[intelligence]
default_model = "{model}"

[agent]
default_agent = "simple"

[tools]
enabled = ["code_interpreter", "web_search", "file_read", "shell_exec"]
"""


def generate_default_toml(
    hw: HardwareInfo, engine: str | None = None, *, host: str | None = None
) -> str:
    """Render the focused local-assistant configuration."""
    engine = "ollama"
    model = recommend_model(hw, engine)
    ollama_host = host or "http://127.0.0.1:11434"
    return f"""\
# Grandpa local Windows assistant configuration
# Generated by `grandpa init`

[user]
username = "Username"
onboarding_completed = false

[engine]
default = "ollama"

[engine.ollama]
host = "{ollama_host}"

[intelligence]
default_model = "{model}"
temperature = 0.7
max_tokens = 1024

[agent]
default_agent = "simple"
max_turns = 10
context_from_memory = true

[tools.storage]
default_backend = "sqlite"

[tools.mcp]
enabled = true

[server]
host = "127.0.0.1"
port = 8000
agent = "orchestrator"

[learning]
enabled = true

[learning.routing]
policy = "heuristic"
min_samples = 5

[telemetry]
enabled = true

[traces]
enabled = false

[security]
enabled = true
mode = "warn"
scan_input = true
scan_output = true
secret_scanner = true
pii_scanner = true
enforce_tool_confirmation = true
ssrf_protection = true

[speech]
backend = "auto"
model = "small"
device = "auto"
compute_type = "auto"

[scheduler]
enabled = true
poll_interval = 60
"""


__all__ = [
    "A2AConfig",
    "AgentConfig",
    "AgentManagerConfig",
    "BrowserConfig",
    "CapabilitiesConfig",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "EngineConfig",
    "GpuInfo",
    "GrandpaConfig",
    "HardwareInfo",
    "IntelligenceConfig",
    "LearningConfig",
    "MCPConfig",
    "MemoryConfig",
    "OllamaEngineConfig",
    "OperatorsConfig",
    "RoutingLearningConfig",
    "SchedulerConfig",
    "SecurityConfig",
    "ServerConfig",
    "SessionConfig",
    "SpeechConfig",
    "StorageConfig",
    "TelemetryConfig",
    "ToolsConfig",
    "TracesConfig",
    "UserConfig",
    "WorkflowConfig",
    "CONFIG_RECOVERY_MESSAGE",
    "CONFIG_RECOVERY_FAILED_MESSAGE",
    "consume_config_recovery_warnings",
    "detect_hardware",
    "generate_default_toml",
    "generate_minimal_toml",
    "load_config",
    "recommend_engine",
    "recommend_model",
    "validate_config_key",
    "validate_ollama_num_ctx",
]
