"""Compatibility module for agy_runner.

Redirects to agent_manager.agent_mgr.
"""
from agent_base import AgentEvent, AgentSession, AgentType
from agent_manager import AgentManager, agent_mgr
from antigravity_runner import AntigravityRunner

# Aliases for backward compatibility
UserSession = AgentSession
AntigravityRunner = AntigravityRunner
agy_runner = agent_mgr
