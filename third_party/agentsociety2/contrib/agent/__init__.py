"""
Agent implementations for AgentSociety v2.

Available agents:
"""

from other.agentsociety2.contrib.agent.commons_tragedy_agent import CommonsTragedyAgent
from other.agentsociety2.contrib.agent.public_goods_agent import PublicGoodsAgent
from other.agentsociety2.contrib.agent.prisoners_dilemma_agent import PrisonersDilemmaAgent
from other.agentsociety2.contrib.agent.trust_game_agent import TrustGameAgent
from other.agentsociety2.contrib.agent.volunteer_dilemma_agent import VolunteerDilemmaAgent

__all__ = [
    "CommonsTragedyAgent",
    "PrisonersDilemmaAgent",
    "PublicGoodsAgent",
    "TrustGameAgent",
    "VolunteerDilemmaAgent",
]
