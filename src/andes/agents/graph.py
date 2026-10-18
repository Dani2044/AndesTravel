"""LangGraph supervisor wiring.

The supervisor is a ``StateGraph``: a ``prepare`` node (guard, profile/memory
update, classification) routes to one of the per-intent agent nodes, which feed a
``finalize`` node (output guard + audit). The business logic lives in
:class:`andes.agents.assistant.Assistant`; this module only wires the topology.

The compiled graph is only built when LangGraph is installed, so the rest of the
package (and the fast unit suite) has no hard dependency on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from andes.agents.assistant import Assistant, AssistantReply
from andes.agents.state import TravelerState

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.graph.state import CompiledStateGraph

_HANDLERS = ("recommend", "quote", "book", "handoff", "recall", "greet")


def build_graph(assistant: Assistant) -> CompiledStateGraph:
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

    def prepare_node(state: TravelerState) -> dict:
        envelope = state["_envelope"]
        intent, attributes = assistant.prepare(envelope)
        return {"intent": intent.value, "profile": attributes}

    def recommend_node(state: TravelerState) -> dict:
        return _wrap(assistant.recommend(state["_envelope"], state.get("profile", {})))

    def quote_node(state: TravelerState) -> dict:
        return _wrap(assistant.quote(state["_envelope"], state.get("profile", {})))

    def book_node(state: TravelerState) -> dict:
        return _wrap(assistant.book(state["_envelope"], state.get("profile", {})))

    def handoff_node(state: TravelerState) -> dict:
        return _wrap(
            assistant.handoff(state["_envelope"], state.get("profile", {}), "explicit request")
        )

    def recall_node(state: TravelerState) -> dict:
        return _wrap(assistant.recall(state["_envelope"]))

    def greet_node(state: TravelerState) -> dict:
        return _wrap(assistant.greet(state["_envelope"]))

    def finalize_node(state: TravelerState) -> dict:
        reply = assistant.finalize(state["_envelope"], state["_reply"])
        return {"response": reply.text}

    def _wrap(reply: AssistantReply) -> dict:
        return {"_reply": reply, "response": reply.text}

    graph: StateGraph = StateGraph(TravelerState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("recommend", recommend_node)
    graph.add_node("quote", quote_node)
    graph.add_node("book", book_node)
    graph.add_node("handoff", handoff_node)
    graph.add_node("recall", recall_node)
    graph.add_node("greet", greet_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        lambda state: state.get("intent", "unknown"),
        {
            "recommend": "recommend",
            "quote": "quote",
            "book": "book",
            "human": "handoff",
            "profile": "recall",
            "greeting": "greet",
            "unknown": "greet",
        },
    )
    for node in _HANDLERS:
        graph.add_edge(node, "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


class GraphRunner:
    """Thin adapter so callers can use the compiled graph like ``Assistant.turn``."""

    def __init__(self, assistant: Assistant) -> None:
        self._assistant = assistant
        self._graph = build_graph(assistant)

    def run(self, envelope) -> AssistantReply:
        state = self._graph.invoke({"_envelope": envelope})
        return state["_reply"]
