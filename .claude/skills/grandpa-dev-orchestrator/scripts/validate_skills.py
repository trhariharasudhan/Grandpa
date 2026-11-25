#!/usr/bin/env python3
"""Validate the GRANDPA Claude Code skills under .claude/skills/.

Checks, per skill directory:
  * SKILL.md exists and starts with a YAML frontmatter block on line 1
  * frontmatter parses, has `name` and `description`, and only portable keys
  * name is kebab-case, <= 64 chars, matches the folder, avoids reserved words
  * description is 40..1024 chars and has no angle brackets
  * SKILL.md body is under 500 lines
  * every relative markdown link in any .md file of the skill resolves
  * every scripts/*.py file compiles
  * no obvious secret-looking strings (API key prefixes, private keys)
Also checks that every skill named in the master index exists and vice versa.

Standard library only (PyYAML is used if importable, else a minimal parser), so
it runs without the project venv:  python .claude/skills/grandpa-dev-orchestrator/scripts/validate_skills.py
Exit code 0 = all checks passed, 1 = at least one failure.
"""

from __future__ import annotations

import py_compile
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
INDEX = SKILLS_DIR / "GRANDPA_SKILLS_MASTER_INDEX.md"
# Keys accepted by every Skills surface (claude.ai, API, Claude Code). Claude Code
# accepts more, but these skills stay portable on purpose.
PORTABLE_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = ("anthropic", "claude")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SECRET_RES = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gp_sk_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
]


def parse_frontmatter(text: str) -> tuple[dict | None, str, str]:
    """Return (fields, body, error)."""
    if not text.startswith("---\n"):
        return None, text, "frontmatter must start on line 1 with ---"
    end = text.find("\n---", 4)
    if end == -1:
        return None, text, "frontmatter is not closed with ---"
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw)
    except ImportError:
        data = {}
        for line in raw.splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip()
    except Exception as exc:  # yaml.YAMLError
        return None, body, f"frontmatter YAML error: {exc}"
    if not isinstance(data, dict):
        return None, body, "frontmatter is not a mapping"
    return data, body, ""


def check_skill(skill: Path) -> list[str]:
    problems: list[str] = []
    md = skill / "SKILL.md"
    if not md.is_file():
        return [f"{skill.name}: SKILL.md missing"]
    text = md.read_text(encoding="utf-8")
    fields, body, error = parse_frontmatter(text)
    if error:
        return [f"{skill.name}: {error}"]
    assert fields is not None
    extra = set(fields) - PORTABLE_KEYS
    if extra:
        problems.append(f"{skill.name}: non-portable frontmatter keys {sorted(extra)}")
    name = str(fields.get("name", ""))
    desc = str(fields.get("description", ""))
    if not name:
        problems.append(f"{skill.name}: missing name")
    elif not NAME_RE.match(name) or len(name) > 64:
        problems.append(
            f"{skill.name}: name {name!r} must be kebab-case and <= 64 chars"
        )
    elif name != skill.name:
        problems.append(f"{skill.name}: name {name!r} does not match folder")
    if any(word in name for word in RESERVED):
        problems.append(f"{skill.name}: name uses a reserved word")
    if not 40 <= len(desc) <= 1024:
        problems.append(f"{skill.name}: description length {len(desc)} not in 40..1024")
    if "<" in desc or ">" in desc:
        problems.append(f"{skill.name}: description contains angle brackets")
    lines = body.count("\n") + 1
    if lines > 500:
        problems.append(f"{skill.name}: SKILL.md body has {lines} lines (> 500)")

    for doc in skill.rglob("*.md"):
        content = doc.read_text(encoding="utf-8")
        for target in LINK_RE.findall(content):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).resolve().exists():
                problems.append(f"{doc.relative_to(SKILLS_DIR)}: broken link {target}")
    for path in skill.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".toml", ".yaml", ".txt"}:
            content = path.read_text(encoding="utf-8", errors="replace")
            for rx in SECRET_RES:
                if rx.search(content):
                    problems.append(
                        f"{path.relative_to(SKILLS_DIR)}: looks like a secret ({rx.pattern})"
                    )
    for script in (
        (skill / "scripts").glob("*.py") if (skill / "scripts").is_dir() else []
    ):
        try:
            py_compile.compile(str(script), doraise=True, cfile=None)
        except py_compile.PyCompileError as exc:
            problems.append(
                f"{script.relative_to(SKILLS_DIR)}: does not compile: {exc.msg}"
            )
    return problems


def main() -> int:
    skills = sorted(
        p
        for p in SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    )
    problems: list[str] = []
    for skill in skills:
        found = check_skill(skill)
        status = "ok" if not found else f"{len(found)} problem(s)"
        print(f"{skill.name:<34} {status}")
        problems.extend(found)
    if INDEX.is_file():
        index_text = INDEX.read_text(encoding="utf-8")
        listed = set(re.findall(r"`(grandpa-[a-z0-9-]+)`", index_text))
        names = {s.name for s in skills}
        for missing in sorted(listed - names):
            problems.append(f"index names {missing!r} but no such skill folder exists")
        for unlisted in sorted(names - listed):
            problems.append(f"skill {unlisted!r} is not described in the master index")
    else:
        problems.append("GRANDPA_SKILLS_MASTER_INDEX.md missing")
    print()
    if problems:
        print(f"FAILED: {len(problems)} problem(s)")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"PASSED: {len(skills)} skills validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
