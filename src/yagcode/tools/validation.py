"""Validation is a named registered command; execution lives in CommandAdapter."""
from .commands import CommandAdapter, CommandTemplate, TemplateRegistry
__all__ = ["CommandAdapter", "CommandTemplate", "TemplateRegistry"]
