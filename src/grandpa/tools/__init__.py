"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from grandpa.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import grandpa.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.docker_shell_exec  # noqa: F401
    import grandpa.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import grandpa.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import grandpa.tools.digest_collect  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
