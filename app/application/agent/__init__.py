"""Agent package initialization."""

from .command_tools import install_command_tool_handlers
from .explicit_input_schema import install_explicit_input_schema

install_command_tool_handlers()
install_explicit_input_schema()

__all__ = [
    "install_command_tool_handlers",
    "install_explicit_input_schema",
]
