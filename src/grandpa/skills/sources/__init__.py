"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from grandpa.skills.sources.base import ResolvedSkill, SourceResolver
from grandpa.skills.sources.github import GitHubResolver
from grandpa.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from grandpa.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
