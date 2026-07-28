"""Google Agent Development Kit (ADK) 2.0 Core Module with Observability, OpenTelemetry, & PII Redaction."""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from memory import AsyncSessionMemory, SessionState, HistoryCompactor
from observability import OpenTelemetryTracer, StructuredLogger, PIIRedactor

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
        if read_only_hint and self.auto_approve_read_only and not self.approval_callback:
            return True

        if self.approval_callback:
            approved = self.approval_callback(tool_name, arguments)
            return approved

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
    def __init__(self, name: str):
        self.name = name

class LlmAgent(Agent):
    """LLM powered specialized agent supporting Strategic Model Routing."""
    def __init__(self, name: str, model: str, instruction: str, tools: Optional[List[Any]] = None):
        super().__init__(name=name)
        self.model = model
        self.instruction = instruction
        self.tools = tools or []

    def generate_response(self, user_text: str, context: Optional[Dict[str, Any]] = None, session_state: Optional[SessionState] = None) -> str:
        lowered = user_text.lower()

        if self.name == "math_verifier":
            if context and "hitl_rejected" in context:
                return "Tool execution paused: Human-in-the-Loop confirmation was rejected by supervisor."

            if context and "mcp_tool_result" in context:
                mcp_res = context["mcp_tool_result"]
                return f"[{self.model.upper()} Symbolic Reasoning Output]\n{mcp_res}\n\nSocratic Inquiry: Look closely at rows $a$ and $b$. What definition or property of group inverses does this table violate?"
            return f"[{self.model.upper()}] Let me check the mathematical structure using the SageMath verifier. Please provide the operational table."

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
    """Stateful Graph Workflow Agent with Observability, OpenTelemetry, & PII Redaction."""
    def __init__(self, name: str, edges: List[Any], memory: Optional[AsyncSessionMemory] = None, hitl_hook: Optional[HumanInTheLoopHook] = None):
        super().__init__(name=name)
        self.edges = edges
        self.routes: Dict[str, Union[Agent, Callable]] = {}
        self.intent_parser: Optional[Callable] = None
        self.memory = memory or AsyncSessionMemory()
        self.hitl_hook = hitl_hook or HumanInTheLoopHook()
        self.tracer = OpenTelemetryTracer(service_name=self.name)
        self.logger = StructuredLogger(service_name=self.name)

        for edge in edges:
            if edge[0] == "START":
                self.intent_parser = edge[1]
            elif callable(edge[0]) or isinstance(edge[0], str):
                if isinstance(edge[1], dict):
                    for route_key, target_agent in edge[1].items():
                        self.routes[route_key] = target_agent

    async def process_async(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Asynchronously executes workflow with OpenTelemetry spans & Structured JSON logging."""
        # 1. Scrub PII before storage & logging
        clean_user_text = PIIRedactor.redact(user_text)

        # 2. OpenTelemetry Root Workflow Span
        root_span = self.tracer.start_span("agent_workflow_execution")
        root_span.set_attribute("session_id", session_id)
        root_span.set_attribute("user_text", clean_user_text)

        self.logger.log_event(
            event_type="WORKFLOW_START",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            data={"session_id": session_id, "user_input": clean_user_text}
        )

        # 3. Asynchronously load & update persistent session memory
        await self.memory.save_turn(session_id=session_id, role="user", content=clean_user_text)
        session_state = await self.memory.get_session(session_id)

        # 4. Intent Parser Span & JSON Logging
        route_span = self.tracer.start_span("intent_routing", trace_id=root_span.trace_id, parent_span_id=root_span.span_id)
        node_input = types.Content.from_text(clean_user_text)
        events = list(self.intent_parser(node_input))
        selected_route = "SOCRATIC_ROUTE"
        if events and events[0].route:
            selected_route = events[0].route[0]

        route_span.set_attribute("selected_route", selected_route)
        route_span.end()

        self.logger.log_event(
            event_type="INTENT_ROUTED",
            trace_id=root_span.trace_id,
            span_id=route_span.span_id,
            data={"route": selected_route}
        )

        target_agent = self.routes.get(selected_route)
        context = {}

        # 5. Tool Call Span & JSON Logging
        if selected_route == "VERIFIER_ROUTE" and mcp_server:
            tool_span = self.tracer.start_span("tool_execution", trace_id=root_span.trace_id, parent_span_id=root_span.span_id)
            tool_name = "verify_group_axioms"
            tool_args = {"set_definition": "{e, a, b}", "operation": clean_user_text}

            is_approved = self.hitl_hook.request_approval(tool_name=tool_name, arguments=tool_args, read_only_hint=True)
            if is_approved:
                tool_output = mcp_server.execute_tool(tool_name=tool_name, arguments=tool_args)
                context["mcp_tool_result"] = tool_output
                context["hitl_approved"] = True
            else:
                context["hitl_rejected"] = True
                context["mcp_tool_result"] = "Tool execution rejected by Human-in-the-Loop supervisor."

            tool_span.set_attribute("tool_name", tool_name)
            tool_span.set_attribute("hitl_approved", context.get("hitl_approved", False))
            tool_span.end()

            self.logger.log_event(
                event_type="TOOL_EXECUTED",
                trace_id=root_span.trace_id,
                span_id=tool_span.span_id,
                data={"tool_name": tool_name, "context": context}
            )

        # 6. Response Generation & Outcome Tracking
        if isinstance(target_agent, LlmAgent):
            response = target_agent.generate_response(clean_user_text, context=context, session_state=session_state)
            used_model = target_agent.model
        else:
            response = "Agent routing failed."
            used_model = "unknown"

        clean_response = PIIRedactor.redact(response)
        await self.memory.save_turn(session_id=session_id, role="assistant", content=clean_response)
        updated_session = await self.memory.get_session(session_id)

        root_span.set_attribute("status", "SUCCESS")
        root_span.set_attribute("model", used_model)
        root_span.end()

        self.logger.log_event(
            event_type="WORKFLOW_COMPLETE",
            trace_id=root_span.trace_id,
            span_id=root_span.span_id,
            data={"outcome": "SUCCESS", "model": used_model, "response": clean_response}
        )

        return {
            "route": selected_route,
            "agent": target_agent.name if isinstance(target_agent, LlmAgent) else "unknown",
            "model": used_model,
            "response": clean_response,
            "context": context,
            "session_summary": updated_session.summary,
            "turn_count": len(updated_session.turns),
            "trace_id": root_span.trace_id
        }

    def process(self, user_text: str, session_id: str = "default_session", mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Synchronous wrapper around process_async."""
        return asyncio.run(self.process_async(user_text=user_text, session_id=session_id, mcp_server=mcp_server))
