"""Agent package initialization."""

from .command_tools import install_command_tool_handlers
from .explicit_input_schema import install_explicit_input_schema
from .governed_executor_patch import install_governed_agent_executor
from .governed_tools import install_governed_tool_handlers

install_command_tool_handlers()
install_explicit_input_schema()
install_governed_tool_handlers()
install_governed_agent_executor()

__all__ = [
    "install_command_tool_handlers",
    "install_explicit_input_schema",
    "install_governed_agent_executor",
    "install_governed_tool_handlers",
]
