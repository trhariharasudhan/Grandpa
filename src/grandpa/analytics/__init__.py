"""External anonymous usage analytics.

Sends anonymized events to PostHog so the Grandpa team can measure
setup success, retention, feature usage, and churn — without ever
collecting chat content, prompts, file paths, emails, IPs, or hardware
identifiers.

Distinct from :mod:`grandpa.telemetry`, which stores local FLOPs and
energy metrics in a SQLite DB and never leaves the machine.

Disable: set ``[analytics] enabled = false`` in ``~/.grandpa/config.toml``.
"""

from grandpa.analytics.aggregator import SessionAggregator
from grandpa.analytics.bridge import EventBridge
from grandpa.analytics.client import AnalyticsClient
from grandpa.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)
from grandpa.analytics.redaction import hash_id, redact

__all__ = [
    "AnalyticsClient",
    "EventBridge",
    "SessionAggregator",
    "get_or_create_anon_id",
    "is_analytics_enabled",
    "reset_anon_id",
    "redact",
    "hash_id",
]
