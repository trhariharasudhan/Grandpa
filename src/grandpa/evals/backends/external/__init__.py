"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from grandpa.evals.backends.external.hermes_agent import HermesBackend
from grandpa.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
