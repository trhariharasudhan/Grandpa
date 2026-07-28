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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Hardware dataclasses
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path(os.environ.get("GRANDPA_HOME", Path.home() / ".grandpa")).expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"


def _ensure_config_dir() -> Path:
    """Ensure the config directory exists with restrictive permissions."""
    from grandpa.security.file_utils import secure_mkdir

    return secure_mkdir(DEFAULT_CONFIG_DIR)


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


# Explicit tier table: (max_ram_gb, model_id).
# Walked in order — first tier where available_gb <= max_ram is chosen.
# Uses Qwen3.5 MoE models — better quality per GB than dense models since
# only a fraction of parameters are active per token.
_MODEL_TIERS = [
    (8, "qwen3.5:2b"),
    (16, "qwen3.5:4b"),
    (32, "qwen3.5:9b"),
    (64, "qwen3.5:27b"),
]
_MODEL_TIER_FALLBACK = "qwen3.5:27b"


def recommend_model(hw: HardwareInfo, engine: str) -> str:
    """Suggest a default model for the selected engine and hardware.

    Uses the local Ollama-compatible Qwen3.5 tier mapping.
    """
    from grandpa.intelligence.model_catalog import BUILTIN_MODELS

    available_gb = _available_memory_gb(hw)
    if available_gb <= 0:
        return ""

    # Build a lookup for quick engine-compatibility checks
    catalog = {spec.model_id: spec for spec in BUILTIN_MODELS}

    # Try explicit tier mapping first
    model_id = _MODEL_TIER_FALLBACK
    for max_ram, tier_model in _MODEL_TIERS:
        if available_gb <= max_ram:
            model_id = tier_model
            break

    spec = catalog.get(model_id)
    if spec and engine in spec.supported_engines:
        return model_id

    # Fallback: scan all Qwen3.5 models for engine compatibility
    candidates = [
        s
        for s in BUILTIN_MODELS
        if s.provider == "alibaba"
        and s.model_id.startswith("qwen3.5:")
        and engine in s.supported_engines
    ]
    candidates.sort(key=lambda s: s.parameter_count_b, reverse=True)
    for s in candidates:
        estimated_gb = s.parameter_count_b * 0.5 * 1.1
        if estimated_gb <= available_gb:
            return s.model_id

    return ""


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


@dataclass
class EngineConfig:
    """Local Ollama inference settings."""

    default: str = "ollama"
    ollama: OllamaEngineConfig = field(default_factory=OllamaEngineConfig)

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

    default_model: str = ""
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
class ServerConfig:
    """API server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    agent: str = "orchestrator"
    model: str = ""
    workers: int = 1
    cors_origins: list = field(default_factory=list)


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
    """Security guardrails settings."""

    enabled: bool = True
    scan_input: bool = True
    scan_output: bool = True
    mode: str = "redact"  # "redact" | "warn" | "block"
    secret_scanner: bool = True
    pii_scanner: bool = True
    audit_log_path: str = str(DEFAULT_CONFIG_DIR / "audit.db")
    enforce_tool_confirmation: bool = True
    merkle_audit: bool = True
    signing_key_path: str = ""
    ssrf_protection: bool = True
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    local_engine_bypass: bool = False
    local_tool_bypass: bool = False
    profile: str = ""
    vault_key_path: str = str(DEFAULT_CONFIG_DIR / ".vault_key")
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)


# ---------------------------------------------------------------------------
# Security profile presets
# ---------------------------------------------------------------------------

_SECURITY_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "personal": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "shared": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "server": {
        "security": {
            "mode": "block",
            "rate_limit_enabled": True,
            "rate_limit_rpm": 30,
            "rate_limit_burst": 5,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "0.0.0.0",
        },
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


@dataclass
class GrandpaConfig:
    """Top-level configuration for grandpa."""

    installed_at: str = ""
    installer_version: str = ""
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
    agent_manager: AgentManagerConfig = field(default_factory=AgentManagerConfig)
    memory_files: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)
    system_prompt: SystemPromptConfig = field(default_factory=SystemPromptConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)

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
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)

        # Run backward-compat migrations before applying
        _migrate_toml_data(data, cfg)

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
            "agent_manager",
        )
        for section_name in top_sections:
            if section_name in data:
                _apply_toml_section(
                    getattr(cfg, section_name),
                    data[section_name],
                )

        # Memory: accept [memory] (old) → maps to tools.storage
        if "memory" in data:
            _apply_toml_section(cfg.tools.storage, data["memory"])

        # Top-level install provenance (installed_at, installer_version)
        for key in ("installed_at", "installer_version"):
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
    "WorkflowConfig",
    "detect_hardware",
    "generate_default_toml",
    "generate_minimal_toml",
    "load_config",
    "recommend_engine",
    "recommend_model",
    "validate_config_key",
]
