from __future__ import annotations

from enum import Enum


class AgentState(str, Enum):
    SCAN = "SCAN"
    QUALIFY_COLLECTION = "QUALIFY_COLLECTION"
    QUOTE_BID = "QUOTE_BID"
    WAIT_BID = "WAIT_BID"
    FILLED_LONG_NFT = "FILLED_LONG_NFT"
    LIST_FOR_EXIT = "LIST_FOR_EXIT"
    MONITOR_EXIT = "MONITOR_EXIT"
    CANCEL_OR_REPRICE = "CANCEL_OR_REPRICE"
    PAUSE_RISK = "PAUSE_RISK"


class DeterministicStateMachine:
    def __init__(self) -> None:
        self.state = AgentState.SCAN

    def advance(self, event: str) -> AgentState:
        transitions = {
            (AgentState.SCAN, "collection_selected"): AgentState.QUALIFY_COLLECTION,
            (AgentState.QUALIFY_COLLECTION, "qualified"): AgentState.QUOTE_BID,
            (AgentState.QUALIFY_COLLECTION, "blocked"): AgentState.PAUSE_RISK,
            (AgentState.QUOTE_BID, "bid_submitted"): AgentState.WAIT_BID,
            (AgentState.QUOTE_BID, "blocked"): AgentState.PAUSE_RISK,
            (AgentState.WAIT_BID, "filled"): AgentState.FILLED_LONG_NFT,
            (AgentState.WAIT_BID, "expired"): AgentState.SCAN,
            (AgentState.FILLED_LONG_NFT, "ready_to_list"): AgentState.LIST_FOR_EXIT,
            (AgentState.LIST_FOR_EXIT, "listed"): AgentState.MONITOR_EXIT,
            (AgentState.MONITOR_EXIT, "needs_reprice"): AgentState.CANCEL_OR_REPRICE,
            (AgentState.MONITOR_EXIT, "sold"): AgentState.SCAN,
            (AgentState.CANCEL_OR_REPRICE, "repriced"): AgentState.MONITOR_EXIT,
            (AgentState.CANCEL_OR_REPRICE, "cooldown"): AgentState.MONITOR_EXIT,
            (AgentState.PAUSE_RISK, "resume"): AgentState.SCAN,
        }
        self.state = transitions.get((self.state, event), self.state)
        return self.state
