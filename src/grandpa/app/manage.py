"""What the desktop app's Skills, Connectors and Models pages read and change.

* **Skills** -- instruction skills in the same shape as Claude's: a folder
  with a ``SKILL.md`` (YAML front matter ``name`` / ``description``, then the
  instructions). They live in ``<grandpa home>/prompt-skills/<name>/``. Using
  one sends its instructions with the next message. Grandpa's built-in *tool*
  skills (``grandpa skill``) are listed read-only beside them.
* **Connectors** -- external MCP servers in ``mcp.toml`` (see
  :mod:`grandpa.mcp.servers`: deny-by-default allow lists, every call asks
  first, a kill switch). A server's keys go to the secret store and the file
  only says ``secret:<name>``.
* **Models & API keys** -- cloud providers (:mod:`grandpa.engine.cloud`).
  Keys go to the secret store; the app never gets a key back, only whether
  one is set.

Every function takes plain values from the page and checks them; none runs a
command the page wrote, except that a *Connector* the user adds is a program
Grandpa will start -- the page says so and asks before saving one.
"""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILL = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_DESCRIPTION = 300
MAX_INSTRUCTIONS = 12000


def _home() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home()


# --- skills -------------------------------------------------------------------------


def skills_dir() -> Path:
    return _home() / "prompt-skills"


def _slug(name: Any) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(name or "").strip().lower()).strip("-")[:48]
    if not _SKILL.match(slug):
        raise ValueError("Give the skill a name (letters, digits and dashes).")
    return slug


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    """Read the ``---`` block at the top of a SKILL.md (simple key: value lines)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4 :].lstrip("\n")


def list_skills() -> dict[str, list[dict[str, Any]]]:
    """``{"yours": [...], "builtin": [...]}`` for the Skills page."""
    yours: list[dict[str, Any]] = []
    folder = skills_dir()
    if folder.is_dir():
        for path in sorted(folder.glob("*/SKILL.md")):
            try:
                meta, body = _front_matter(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            yours.append(
                {
                    "name": path.parent.name,
                    "description": meta.get("description", "")[:MAX_DESCRIPTION],
                    "instructions": body[:MAX_INSTRUCTIONS],
                    "enabled": meta.get("enabled", "true").lower() != "false",
                }
            )
    return {"yours": yours, "builtin": builtin_skills()}


def builtin_skills() -> list[dict[str, str]]:
    import tomllib

    data_dir = Path(__file__).resolve().parents[1] / "skills" / "data"
    found = []
    for path in sorted(data_dir.glob("*.toml")):
        try:
            skill = tomllib.loads(path.read_text(encoding="utf-8")).get("skill", {})
        except (OSError, tomllib.TOMLDecodeError):
            continue
        found.append(
            {
                "name": str(skill.get("name", path.stem)),
                "description": str(skill.get("description", "")),
            }
        )
    return found


def save_skill(
    name: Any, description: Any, instructions: Any, enabled: Any = True
) -> dict[str, Any]:
    try:
        slug = _slug(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    text = str(instructions or "").strip()
    if not text:
        return {"ok": False, "error": "Write what the skill should make Grandpa do."}
    if len(text) > MAX_INSTRUCTIONS:
        return {
            "ok": False,
            "error": f"Instructions are limited to {MAX_INSTRUCTIONS} characters.",
        }
    about = " ".join(str(description or "").split())[:MAX_DESCRIPTION]
    folder = skills_dir() / slug
    folder.mkdir(parents=True, exist_ok=True)
    about_line = about.replace("\n", " ")
    body = (
        f"---\nname: {slug}\ndescription: {about_line}\n"
        f"enabled: {'true' if enabled is not False else 'false'}\n---\n\n{text}\n"
    )
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    return {"ok": True, "name": slug}


def delete_skill(name: Any) -> bool:
    try:
        slug = _slug(name)
    except ValueError:
        return False
    path = skills_dir() / slug / "SKILL.md"
    if not path.is_file():
        return False
    path.unlink()
    try:
        path.parent.rmdir()  # only when nothing else is in the folder
    except OSError:
        pass
    return True


def import_skill(path: Any, allowed: Any = ()) -> dict[str, Any]:
    """Import a SKILL.md the user picked in the file dialog."""
    resolved = str(Path(str(path)).resolve())
    if resolved not in set(allowed or ()):
        return {"ok": False, "error": "Pick the SKILL.md with the file dialog."}
    file = Path(resolved)
    if file.suffix.lower() != ".md" or file.stat().st_size > 64_000:
        return {"ok": False, "error": "A skill is a .md file under 64 KB."}
    meta, body = _front_matter(file.read_text(encoding="utf-8", errors="replace"))
    name = meta.get("name") or (
        file.parent.name if file.name.upper() == "SKILL.MD" else file.stem
    )
    return save_skill(name, meta.get("description", ""), body)


def skill_instructions(name: Any) -> str:
    try:
        slug = _slug(name)
    except ValueError:
        return ""
    path = skills_dir() / slug / "SKILL.md"
    if not path.is_file():
        return ""
    _meta, body = _front_matter(path.read_text(encoding="utf-8"))
    return body[:MAX_INSTRUCTIONS]


# --- connectors (MCP) -------------------------------------------------------------------


def mcp_status() -> dict[str, Any]:
    from grandpa.mcp.servers import is_off, load_settings

    settings = load_settings()
    return {
        "path": str(settings.path),
        "off": is_off(settings) or "",
        "problems": list(settings.problems),
        "servers": [
            {
                "name": s.name,
                "command": " ".join(s.command),
                "allow": list(s.allow),
                "enabled": s.enabled,
                "timeout": s.timeout,
                "env": [k for k, _v in s.env],
            }
            for s in settings.servers.values()
        ],
    }


def _mcp_doc():
    import tomlkit

    from grandpa.mcp.servers import config_path

    path = config_path()
    if path.is_file():
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
        doc.add(
            tomlkit.comment("External MCP servers (see docs/getting-started/mcp.md).")
        )
    return path, doc


def _mcp_write(path: Path, doc: Any) -> None:
    import tomlkit

    from grandpa.mcp.servers import parse_settings, reset_hub

    text = tomlkit.dumps(doc)
    parse_settings(
        tomlkit.parse(text).unwrap()
    )  # never write a file Grandpa can't read
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.with_suffix(".toml.bak").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    reset_hub()  # running servers restart with the new settings


def mcp_save_server(
    name: Any, command_line: Any, allow: Any, keys: Any = None
) -> dict[str, Any]:
    """Add or change ``[servers.<name>]``. ``keys``: ``{"ENV_NAME": "value"}``;
    a value goes to the secret store, an empty value keeps the stored one."""
    import tomlkit

    from grandpa.mcp.servers import _ENV_NAME, _SERVER_NAME, SECRET_PREFIX

    name = str(name or "").strip()
    if not _SERVER_NAME.match(name) or len(name) > 40:
        return {
            "ok": False,
            "error": "Name: letters, digits and '-' (like github or my-files).",
        }
    try:
        parts = shlex.split(str(command_line or ""), posix=False)
    except ValueError as exc:
        return {"ok": False, "error": f"Command: {exc}"}
    parts = [p.strip('"') for p in parts]
    if not parts:
        return {
            "ok": False,
            "error": "Give the command that starts the server, e.g. npx -y @modelcontextprotocol/server-github",
        }
    tools = [
        t.strip() for t in str(allow or "").replace("\n", ",").split(",") if t.strip()
    ]
    keys = keys if isinstance(keys, dict) else {}
    path, doc = _mcp_doc()
    servers = doc.setdefault("servers", tomlkit.table(is_super_table=True))
    entry = servers.get(name) or tomlkit.table()
    entry["command"] = parts[0]
    entry["args"] = parts[1:]
    entry["allow"] = tools
    env = entry.get("env") or tomlkit.inline_table()
    from grandpa.security.secret_store import SecretStore, SecretStoreError

    for var, value in keys.items():
        var = str(var).strip()
        if not _ENV_NAME.match(var):
            return {
                "ok": False,
                "error": f"Key name {var!r}: letters, digits and _ only.",
            }
        secret_name = f"mcp.{name}.{var}"
        if str(value or "").strip():
            try:
                SecretStore().set(secret_name, str(value).strip())
            except SecretStoreError as exc:
                return {"ok": False, "error": str(exc)}
        env[var] = SECRET_PREFIX + secret_name
    if env:
        entry["env"] = env
    servers[name] = entry
    try:
        _mcp_write(path, doc)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return {"ok": False, "error": f"Not saved: {exc}"}
    return {"ok": True}


def mcp_remove_server(name: Any) -> bool:
    path, doc = _mcp_doc()
    servers = doc.get("servers")
    if not servers or str(name) not in servers:
        return False
    env = servers[str(name)].get("env") or {}
    del servers[str(name)]
    _mcp_write(path, doc)
    from grandpa.security.secret_store import SecretStore

    for value in env.values():
        if str(value).startswith("secret:"):
            try:
                SecretStore().delete(str(value)[7:])
            except Exception:  # noqa: BLE001
                pass
    return True


def mcp_toggle_server(name: Any, enabled: Any) -> bool:
    path, doc = _mcp_doc()
    servers = doc.get("servers")
    if not servers or str(name) not in servers:
        return False
    servers[str(name)]["enabled"] = bool(enabled)
    _mcp_write(path, doc)
    return True


def mcp_set_off(off: Any) -> bool:
    from grandpa.mcp.servers import set_off

    set_off(bool(off))
    return True


def mcp_test(name: Any) -> dict[str, Any]:
    from grandpa.mcp.servers import get_hub, is_off, load_settings

    why = is_off(load_settings())
    if why:
        return {"ok": False, "error": f"Connectors are off ({why})."}
    try:
        report = get_hub().test(str(name))
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, **report}


# --- models & API keys -----------------------------------------------------------------


def providers_status() -> dict[str, Any]:
    from grandpa.engine.cloud import PRESETS, key_name, load_providers
    from grandpa.security.secret_store import SecretStore

    store = SecretStore()
    names = set(store.names())
    added = load_providers()
    return {
        "store": store.describe(),
        "presets": [
            {"id": pid, "label": label, "base_url": url, "needs_key": needs}
            for pid, (label, url, needs) in PRESETS.items()
        ],
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "base_url": p.base_url,
                "models": list(p.models),
                "needs_key": p.needs_key,
                "has_key": key_name(p.id) in names,
            }
            for p in added.values()
        ],
    }


def provider_save(
    provider_id: Any, base_url: Any, api_key: Any, models: Any, label: Any = ""
) -> dict[str, Any]:
    from grandpa.engine.cloud import (
        MAX_MODELS,
        PRESETS,
        Provider,
        check_id,
        check_url,
        key_name,
        load_providers,
        save_providers,
    )
    from grandpa.security.secret_store import SecretStore, SecretStoreError

    try:
        pid = check_id(str(provider_id or "").strip().lower())
        url = check_url(base_url or (PRESETS.get(pid, ("", "", True))[1]))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    chosen = (
        models
        if isinstance(models, list)
        else str(models or "").replace("\n", ",").split(",")
    )
    chosen = [str(m).strip() for m in chosen if str(m).strip()][:MAX_MODELS]
    preset = PRESETS.get(pid)
    has_key = bool(str(api_key or "").strip()) or key_name(pid) in set(
        SecretStore().names()
    )
    needs_key = preset[2] if preset else has_key  # a custom local server may need none
    if str(api_key or "").strip():
        try:
            SecretStore().set(key_name(pid), str(api_key).strip())
        except SecretStoreError as exc:
            return {"ok": False, "error": str(exc)}
    providers = load_providers()
    providers[pid] = Provider(
        id=pid,
        label=str(label or (preset[0] if preset else pid))[:40],
        base_url=url,
        models=tuple(chosen),
        needs_key=needs_key,
    )
    save_providers(providers)
    return {"ok": True}


def provider_remove(provider_id: Any) -> bool:
    from grandpa.engine.cloud import key_name, load_providers, save_providers
    from grandpa.security.secret_store import SecretStore

    providers = load_providers()
    pid = str(provider_id or "")
    if pid not in providers:
        return False
    del providers[pid]
    save_providers(providers)
    try:
        SecretStore().delete(key_name(pid))
    except Exception:  # noqa: BLE001
        pass
    return True


def provider_models(provider_id: Any) -> dict[str, Any]:
    """Ask the provider which models the key can use (one request)."""
    from grandpa.engine.cloud import client_for

    try:
        client, _name = client_for(f"@{provider_id}/x")
        return {"ok": True, "models": client.list_remote_models()[:500]}
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return {"ok": False, "error": str(exc)[:300]}
