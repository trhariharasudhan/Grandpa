"""Service facades that keep API routes thin and domain-owned."""

from grandpa.services.registry import service_diagnostics, service_names

__all__ = ["service_diagnostics", "service_names"]
