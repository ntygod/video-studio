"""Agent package initialization."""

from .command_tools import install_command_tool_handlers

install_command_tool_handlers()

__all__ = ["install_command_tool_handlers"]
