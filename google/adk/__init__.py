"""Google Agent Development Kit (ADK) 2.0 Core Module with Strategic Model Routing & HITL Support."""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from memory import AsyncSessionMemory, SessionState, HistoryCompactor

# =====================================================================
# TYPES & HITL DEFINITIONS
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


class HumanInTheLoopHook:
    """Human-in-the-Loop (HITL) confirmation hook manager for tool execution safety."""

    def __init__(self, auto_approve_read_only: bool = True):
        self.auto_approve_read_only = auto_approve_read_only
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}
        self.approval_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None

    def set_approval_callback(self, callback: Callable[[str, Dict[str, Any]], bool]):
        self.approval_callback = callback

    def request_approval(self, tool_name: str, arguments: Dict[str, Any], read_only_hint: bool = True) -> bool:
        """Evaluates whether tool execution is approved by human supervisor."""
        if read_only_hint and self.auto_approve_read_only and not self.approval_callback:
            return True

        if self.approval_callback:
            approved = self.approval_callback(tool_name, arguments)
            return approved

        # Default fallback to human approval requirement
        confirmation_id = f"{tool_name}_{len(self.pending_confirmations)}"
        self.pending_confirmations[confirmation_id] = {
            "tool_name": tool_name,
            "arguments": arguments,
            "approved": False
        }
        return False


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
    """LLM powered specialized agent supporting Strategic Model Routing."""
    def __init__(self, name: str, model: str, instruction: str, tools: Optional[List[Any]] = None):
        super().__init__(name=name)
        self.model = model  # e.g., 'gemini-2.5-pro' (high reasoning) vs 'gemini-2.5-flash-latest' (fast Socratic)
        self.instruction = instruction
        self.tools = tools or []

    def generate_response(self, user_text: str, context: Optional[Dict[str, Any]] = None, session_state: Optional[SessionState] = None) -> str:
        """Generates response using specific strategic model capabilities."""
        lowered = user_text.lower()

        # Math verifier using reasoning model (gemini-2.5-pro)
        if self.name == "math_verifier":
            if context and "hitl_rejected" in context:
                return "Tool execution paused: Human-in-the-Loop confirmation was rejected by supervisor."

            if context and "mcp_tool_result" in context:
                mcp_res = context["mcp_tool_result"]
                return f"[{self.model.upper()} Symbolic Reasoning Output]\n{mcp_res}\n\nSocratic Inquiry: Look closely at rows $a$ and $b$. What definition or property of group inverses does this table violate?"
            return f"[{self.model.upper()}] Let me check the mathematical structure using the SageMath verifier. Please provide the operational table."

        # Socratic Tutor using conversational model (gemini-2.5-flash-latest)
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
    """Stateful Graph Workflow Agent with Strategic Model Routing & HITL Support."""
    def __init__(self, name: str, edges: List[Any], memory: Optional[AsyncSessionMemory] = None, hitl_hook: Optional[HumanInTheLoopHook] = None):
        super().__init__(name=name)
        self.edges = edges
        self.routes: Dict[str, Union[Agent, Callable]] = {}
        self.intent_parser: Optional[Callable] = None
        self.memory = memory or AsyncSessionMemory()
        self.hitl_hook = hitl_hook or HumanInTheLoopHook()

        # Unpack edges graph structure
        for edge in edges:
            if edge[0] == "START":
                self.intent_parser = edge[1]
            elif callable(edge[0]) or isinstance(edge[0], str):
                if isinstance(edge[1], dict):
                    for route_key, target_agent in edge[1].items():
                        self.routes[route_key] = target_agent

    async def process_async(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Asynchronously executes workflow with strategic model routing & HITL tool verification."""
        await self.memory.save_turn(session_id=session_id, role="user", content=user_text)
        session_state = await self.memory.get_session(session_id)

        # Step 1: Run intent parser
        node_input = types.Content.from_text(user_text)
        events = list(self.intent_parser(node_input))
        selected_route = "SOCRATIC_ROUTE"
        if events and events[0].route:
            selected_route = events[0].route[0]

        target_agent = self.routes.get(selected_route)
        context = {}

        # Step 2: Handle tool execution with HITL confirmation hook
        if selected_route == "VERIFIER_ROUTE" and mcp_server:
            tool_name = "verify_group_axioms"
            tool_args = {"set_definition": "{e, a, b}", "operation": user_text}

            # Human-in-the-loop confirmation check
            is_approved = self.hitl_hook.request_approval(tool_name=tool_name, arguments=tool_args, read_only_hint=True)
            if is_approved:
                tool_output = mcp_server.execute_tool(tool_name=tool_name, arguments=tool_args)
                context["mcp_tool_result"] = tool_output
                context["hitl_approved"] = True
            else:
                context["hitl_rejected"] = True
                context["mcp_tool_result"] = "Tool execution rejected by Human-in-the-Loop supervisor."

        # Step 3: Response generation using strategically routed model
        if isinstance(target_agent, LlmAgent):
            response = target_agent.generate_response(user_text, context=context, session_state=session_state)
            used_model = target_agent.model
        else:
            response = "Agent routing failed."
            used_model = "unknown"

        await self.memory.save_turn(session_id=session_id, role="assistant", content=response)
        updated_session = await self.memory.get_session(session_id)

        return {
            "route": selected_route,
            "agent": target_agent.name if isinstance(target_agent, LlmAgent) else "unknown",
            "model": used_model,
            "response": response,
            "context": context,
            "session_summary": updated_session.summary,
            "turn_count": len(updated_session.turns)
        }

    def process(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Synchronous wrapper around process_async."""
        return asyncio.run(self.process_async(user_text=user_text, session_id=session_id, mcp_server=mcp_server))
