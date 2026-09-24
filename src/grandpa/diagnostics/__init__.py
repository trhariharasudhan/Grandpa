"""Diagnostics that help when something goes wrong in someone else's process."""

from grandpa.diagnostics.stall import arm, disarm, stall_log_path

__all__ = ["arm", "disarm", "stall_log_path"]
