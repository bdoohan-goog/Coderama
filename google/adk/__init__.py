"""Google Agent Development Kit (ADK) 2.0 Core Module with Async Memory & Compaction Support."""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from memory import AsyncSessionMemory, SessionState, HistoryCompactor

# =====================================================================
# TYPES DEFINITIONS
# =====================================================================

class Part(BaseModel):
    text: str

class Content(BaseModel):
    parts: List[Part]

    @classmethod
    def from_text(cls, text: str) -> "Content":
        return cls(parts=[Part(text=text)])

class TypesModule:
    Content = Content
    Part = Part

types = TypesModule()

# =====================================================================
# EVENT & AGENT DEFINITIONS
# =====================================================================

class Event(BaseModel):
    route: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)

class Agent:
    """Base class for ADK 2.0 Agents."""
    def __init__(self, name: str):
        self.name = name

class LlmAgent(Agent):
    """LLM powered specialized agent."""
    def __init__(self, name: str, model: str, instruction: str, tools: Optional[List[Any]] = None):
        super().__init__(name=name)
        self.model = model
        self.instruction = instruction
        self.tools = tools or []

    def generate_response(self, user_text: str, context: Optional[Dict[str, Any]] = None, session_state: Optional[SessionState] = None) -> str:
        """Simulates LLM response based on Socratic instruction, MCP verifier context, & session history summary."""
        lowered = user_text.lower()

        # If in verifier context or table input
        if self.name == "math_verifier":
            if context and "mcp_tool_result" in context:
                mcp_res = context["mcp_tool_result"]
                return f"SageMath Symbolic Verification Output:\n{mcp_res}\n\nSocratic Inquiry: Look closely at rows $a$ and $b$. What definition or property of group inverses does this table violate?"
            return "Let me check the mathematical structure using the SageMath verifier. Please provide the operational table."

        # Socratic Tutor logic
        if self.name == "socratic_tutor":
            if "proof" in lowered or "prove" in lowered or "show that" in lowered:
                prefix = ""
                if session_state and session_state.summary:
                    prefix = f"[Prior Context Summary: {session_state.summary}]\n"
                return (
                    f"{prefix}To prove this property, let's step back and inspect the definitions.\n"
                    "What is the definition of normal subgroup? "
                    "How do we show a subgroup is normal? "
                    "Let's choose an arbitrary element $g \\in G$ and $h \\in H \\cap K$."
                )
            return "What algebraic axiom or property applies to this step? Consider identity, closure, inverses, or associativity."

        return "Could you elaborate on the mathematical definitions involved?"

class WorkflowAgent(Agent):
    """Stateful Graph Workflow Agent supporting Async Session Persistence and Compaction."""
    def __init__(self, name: str, edges: List[Any], memory: Optional[AsyncSessionMemory] = None):
        super().__init__(name=name)
        self.edges = edges
        self.routes: Dict[str, Union[Agent, Callable]] = {}
        self.intent_parser: Optional[Callable] = None
        self.memory = memory or AsyncSessionMemory()

        # Unpack edges graph structure
        for edge in edges:
            if edge[0] == "START":
                self.intent_parser = edge[1]
            elif callable(edge[0]) or isinstance(edge[0], str):
                if isinstance(edge[1], dict):
                    for route_key, target_agent in edge[1].items():
                        self.routes[route_key] = target_agent

    async def process_async(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Asynchronously executes graph workflow with persistent memory & history compaction."""
        # 1. Asynchronously load & update persistent session memory
        await self.memory.save_turn(session_id=session_id, role="user", content=user_text)
        session_state = await self.memory.get_session(session_id)

        # 2. Run intent parser
        node_input = types.Content.from_text(user_text)
        events = list(self.intent_parser(node_input))
        selected_route = "SOCRATIC_ROUTE"
        if events and events[0].route:
            selected_route = events[0].route[0]

        target_agent = self.routes.get(selected_route)

        # 3. Handle MCP tool calls
        context = {}
        if selected_route == "VERIFIER_ROUTE" and mcp_server:
            tool_output = mcp_server.execute_tool(
                tool_name="verify_group_axioms",
                arguments={"set_definition": "{e, a, b}", "operation": user_text}
            )
            context["mcp_tool_result"] = tool_output

        # 4. Generate response incorporating session summary
        if isinstance(target_agent, LlmAgent):
            response = target_agent.generate_response(user_text, context=context, session_state=session_state)
        else:
            response = "Agent routing failed."

        # 5. Asynchronously persist agent response turn
        await self.memory.save_turn(session_id=session_id, role="assistant", content=response)
        updated_session = await self.memory.get_session(session_id)

        return {
            "route": selected_route,
            "agent": target_agent.name if isinstance(target_agent, LlmAgent) else "unknown",
            "response": response,
            "context": context,
            "session_summary": updated_session.summary,
            "turn_count": len(updated_session.turns)
        }

    def process(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Synchronous wrapper around process_async."""
        return asyncio.run(self.process_async(user_text=user_text, session_id=session_id, mcp_server=mcp_server))
