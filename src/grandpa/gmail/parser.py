"""Parser for Gmail natural-language and slash commands."""

from __future__ import annotations

import re

from grandpa.gmail.models import GmailAction


class GmailParser:
    """Parse confident Gmail commands."""

    def parse(self, text: str) -> GmailAction | None:
        raw = _clean(text)
        command = raw.casefold()
        if not command:
            return None
        return (
            self._parse_setup(command)
            or self._parse_read(command)
            or self._parse_search(command, raw)
            or self._parse_draft(command, raw)
            or self._parse_write(command, raw)
        )

    def _parse_setup(self, command: str) -> GmailAction | None:
        if command in {"gmail setup", "email setup", "connect gmail", "connect email"}:
            return GmailAction("setup")
        if command in {"gmail disconnect", "email disconnect", "disconnect gmail", "disconnect email"}:
            return GmailAction("disconnect")
        if command in {"gmail status", "email status"}:
            return GmailAction("status")
        if command in {"show gmail labels", "show labels", "gmail labels"}:
            return GmailAction("labels")
        if "permanently delete" in command:
            return GmailAction("trash", args={"permanent_delete_blocked": True})
        return None

    def _parse_read(self, command: str) -> GmailAction | None:
        if command in {"show my unread emails", "show unread emails", "unread emails", "gmail unread"}:
            return GmailAction("list", query="is:unread")
        if command in {"count unread emails", "how many unread emails do i have"}:
            return GmailAction("search", query="is:unread", args={"count_only": True})
        if command in {"show inbox", "show my inbox", "gmail inbox"}:
            return GmailAction("list", query="in:inbox")
        if command in {"show latest emails", "latest emails", "show recent emails"}:
            return GmailAction("list", query="")
        if command in {"show emails from today", "what emails did i receive today", "summarize emails from today"}:
            action = "summarize" if command.startswith("summarize") else "list"
            return GmailAction(action, query="newer_than:1d")
        if command in {"show emails from this week", "summarize emails from this week"}:
            action = "summarize" if command.startswith("summarize") else "list"
            return GmailAction(action, query="newer_than:7d")
        if command in {"show emails with attachments", "emails with attachments"}:
            return GmailAction("list", query="has:attachment")
        if command in {"read this email", "read latest email", "read the latest email"}:
            return GmailAction("read", selector="latest")
        if command in {"summarize this email", "summarize latest email"}:
            return GmailAction("summarize", selector="latest")
        if command in {"summarize this thread", "summarize the thread"}:
            return GmailAction("summarize", selector="thread")
        if command in {"summarize unread emails", "summarize my unread emails"}:
            return GmailAction("summarize", query="is:unread")
        return None

    def _parse_search(self, command: str, raw: str) -> GmailAction | None:
        patterns = (
            (r"find emails from (.+)", "from:{value}"),
            (r"show emails from (.+)", "from:{value}"),
            (r"read latest email from (.+)", "from:{value}"),
            (r"read the latest email from (.+)", "from:{value}"),
            (r"find emails with subject (.+)", 'subject:"{value}"'),
            (r"find emails containing (.+)", "{value}"),
            (r"search gmail for (.+)", "{value}"),
            (r"search email for (.+)", "{value}"),
        )
        for pattern, template in patterns:
            match = re.fullmatch(pattern, command)
            if not match:
                continue
            value = raw[-len(match.group(1)) :].strip()
            action = "read" if pattern.startswith("read") else "search"
            return GmailAction(action, query=template.format(value=value), selector="latest" if action == "read" else "")
        return None

    def _parse_draft(self, command: str, raw: str) -> GmailAction | None:
        match = re.fullmatch(r"draft an email to ([^\s]+)(?: about (.+))?", command)
        if match:
            recipient = raw[match.start(1) : match.end(1)]
            subject = raw[match.start(2) : match.end(2)] if match.group(2) else ""
            return GmailAction("draft", recipient=recipient, subject=subject, body=subject)
        match = re.fullmatch(r"draft a reply saying (.+)", command)
        if match:
            body = raw[match.start(1) : match.end(1)]
            return GmailAction("draft", selector="reply", body=body)
        return None

    def _parse_write(self, command: str, raw: str) -> GmailAction | None:
        if command in {"send the draft", "send this email", "send the saved draft"}:
            return GmailAction("send", selector="draft")
        if command in {"reply to this email", "reply to the latest email"}:
            return GmailAction("reply", selector="latest")
        if command in {"forward this email", "forward the latest email"}:
            return GmailAction("forward", selector="latest")
        if command in {"archive this email", "archive the latest email"}:
            return GmailAction("archive", selector="latest")
        if "newsletters" in command and command.startswith("archive"):
            return GmailAction("archive", query="newsletter", bulk=True)
        if command in {"delete this email", "move this email to trash", "trash this email"}:
            return GmailAction("trash", selector="latest")
        match = re.fullmatch(r"(?:add label|label these emails as|label all .+ as) (.+)", command)
        if match:
            label = raw[match.start(1) : match.end(1)]
            return GmailAction("label", label=label, bulk="all " in command or "these emails" in command)
        match = re.fullmatch(r"remove label (.+)", command)
        if match:
            label = raw[match.start(1) : match.end(1)]
            return GmailAction("label", label=label, args={"remove": True})
        match = re.fullmatch(r"create label (.+)", command)
        if match:
            label = raw[match.start(1) : match.end(1)]
            return GmailAction("label", label=label, args={"create": True})
        return None


def _clean(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


__all__ = ["GmailParser"]
