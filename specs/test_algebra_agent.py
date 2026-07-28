"""Pytest-BDD Test Suite for Abstract Algebra Socratic Agent Specification."""

import os
import time
import asyncio
import pytest
from pytest_bdd import scenarios, given, when, then, parsers

from main import root_agent, hitl_gateway, socratic_tutor, math_verifier
from sagemath_mcp_server import SageMathMCPServer
from model_armor import ModelArmorGateway
from memory import AsyncSessionMemory
from observability import PIIRedactor, OpenTelemetryTracer

# Load Gherkin feature file
scenarios('algebra-agent.feature')


@pytest.fixture
def context():
    """Shared test execution context."""
    return {
        "mcp_server": SageMathMCPServer(),
        "model_armor": ModelArmorGateway(),
        "last_response": None,
        "last_mcp_result": None,
        "flagged": False,
        "memory": AsyncSessionMemory(db_path="test_memory.db")
    }


# =====================================================================
# SCENARIO 1: Prevent direct proof generation
# =====================================================================

@given('a clean conversational session with the "algebra_agent_orchestrator"')
def clean_session(context):
    context["session_agent"] = root_agent


@when(parsers.parse('the student asks "{question}"'))
def student_asks(context, question):
    res = root_agent.process(question, mcp_server=context["mcp_server"])
    context["last_response"] = res["response"]


@then(parsers.parse('the agent response must NOT contain "{forbidden_text}"'))
def response_must_not_contain(context, forbidden_text):
    assert forbidden_text not in context["last_response"], (
        f"Response generated direct proof text: '{forbidden_text}'"
    )


@then('the agent response must contain at least one of the following Socratic prompts:')
def response_contains_socratic_prompt(context, datatable):
    prompts = [
        "How do we show a subgroup is normal?",
        "What is the definition of normal?",
        "Let's choose an arbitrary element"
    ]
    response = context["last_response"]
    found = any(p in response for p in prompts)
    assert found, f"Response did not contain any expected Socratic prompt: {response}"


# =====================================================================
# SCENARIO 2: Verify Cayley Table correctness with SageMath
# =====================================================================

@given('a session routing to "math_verifier"')
def session_verifier(context):
    context["route_target"] = "math_verifier"


@when('the student inputs the following Cayley table for a set {e, a}:')
def student_inputs_cayley_table(context, datatable):
    table_str = "* | e | a\ne | e | a\na | a | a"
    res = root_agent.process(f"check table {table_str}", mcp_server=context["mcp_server"])
    context["last_response"] = res["response"]
    context["last_mcp_result"] = res["context"].get("mcp_tool_result", "")


@then(parsers.parse('the connected "{tool_name}" MCP tool must return "{expected_result}"'))
def mcp_returns_expected(context, tool_name, expected_result):
    assert context["last_mcp_result"] == expected_result, (
        f"MCP Tool returned '{context['last_mcp_result']}', expected '{expected_result}'"
    )


@then('the agent must respond with a Socratic counterexample regarding the lack of identity inverses.')
def agent_responds_counterexample(context):
    resp = context["last_response"]
    assert "inverse" in resp.lower() or "lack" in resp.lower() or "violate" in resp.lower()


# =====================================================================
# SCENARIO 3: Mitigate prompt injection bypasses
# =====================================================================

@given('an active agent session protected by "Model Armor"')
def session_protected_model_armor(context):
    context["protected"] = True


@when(parsers.parse('the student attempts an injection: "{injection_text}"'))
def student_attempts_injection(context, injection_text):
    is_flagged, message = context["model_armor"].inspect_prompt(injection_text)
    context["flagged"] = is_flagged
    context["last_response"] = message


@then('the Model Armor gateway must flag the request')
def model_armor_flags(context):
    assert context["flagged"] is True, "Model Armor failed to flag prompt injection attempt."


@then('the agent must refuse the override and output the standard Socratic introduction')
def refuse_override(context):
    resp = context["last_response"]
    assert "flagged by Model Armor" in resp or "Socratic Abstract Algebra tutor" in resp


# =====================================================================
# SCENARIO 4: Maintain persistent session state, history compaction, & async memory
# =====================================================================

@given(parsers.parse('a multi-turn session "{session_id}" with async SQLite memory store'))
def session_with_async_memory(context, session_id):
    unique_id = f"{session_id}_{time.time()}"
    context["session_id"] = unique_id


@when('the student sends 5 sequential questions to the agent')
def student_sends_5_questions(context):
    session_id = context["session_id"]
    questions = [
        "What is a group in abstract algebra?",
        "Define Lagrange theorem.",
        "What is a coset?",
        "Define normal subgroup.",
        "Prove that the intersection of two normal subgroups is a normal subgroup"
    ]
    for q in questions:
        root_agent.process(q, session_id=session_id, mcp_server=context["mcp_server"])


@then('the persistent session state must compact older turns into a summary')
def persistent_session_compacted(context):
    session_id = context["session_id"]
    state = asyncio.run(root_agent.memory.get_session(session_id))
    assert state.summary != "", "Session history compaction summary was not generated."
    assert len(state.turns) <= 4, f"Turn count expected <= 4 after compaction, got {len(state.turns)}"


@then('the vector memory search must find past mathematical context asynchronously')
def vector_memory_search_finds_context(context):
    session_id = context["session_id"]
    results = asyncio.run(root_agent.memory.search_memory(session_id, query="normal subgroup"))
    assert len(results) > 0, "Vector memory search returned no results."
    assert any("normal subgroup" in r.lower() for r in results)


# =====================================================================
# SCENARIO 5: Strategic Model Routing based on Task Complexity
# =====================================================================

@given(parsers.parse('a student query requiring complex symbolic verification "{query}"'))
def student_query_complex(context, query):
    context["complex_query"] = query


@when(parsers.parse('the orchestrator routes the request to "{target_route}"'))
def orchestrator_routes_request(context, target_route):
    res = root_agent.process(context["complex_query"], mcp_server=context["mcp_server"])
    context["last_run_res"] = res


@then(parsers.parse('the system must strategically route the task to the high-reasoning model "{expected_model}"'))
def verify_strategic_model_used(context, expected_model):
    res = context["last_run_res"]
    assert res["model"] == expected_model, f"Expected model '{expected_model}', got '{res['model']}'"
    assert math_verifier.model == "gemini-2.5-pro"


@then(parsers.parse('Socratic conversational turns must route to "{expected_flash_model}"'))
def verify_socratic_flash_model(context, expected_flash_model):
    res = root_agent.process("How do I show a subgroup is normal?", mcp_server=context["mcp_server"])
    assert res["model"] == expected_flash_model, f"Expected Socratic model '{expected_flash_model}', got '{res['model']}'"
    assert socratic_tutor.model == "gemini-2.5-flash-latest"


# =====================================================================
# SCENARIO 6: Human-in-the-Loop confirmation hooks for tool execution
# =====================================================================

@given('an active session with Human-in-the-Loop tool verification enabled')
def session_with_hitl_enabled(context):
    def reject_callback(tool_name, args):
        return False

    root_agent.hitl_hook.set_approval_callback(reject_callback)


@when('a tool execution is rejected by the human supervisor callback')
def tool_execution_rejected(context):
    res = root_agent.process("check table: * | e | a; e | e | a; a | a | a", mcp_server=context["mcp_server"])
    context["last_response"] = res["response"]
    context["last_context"] = res["context"]
    root_agent.hitl_hook.set_approval_callback(None)


@then('the agent must pause tool execution and notify that confirmation was rejected')
def agent_notifies_rejection(context):
    assert context["last_context"].get("hitl_rejected") is True
    assert "Human-in-the-Loop confirmation was rejected" in context["last_response"]


# =====================================================================
# SCENARIO 7: Emit structured JSON logging, OpenTelemetry tracing spans, & active PII redaction
# =====================================================================

@given(parsers.parse('a student message containing sensitive PII "{pii_input}"'))
def student_input_pii(context, pii_input):
    context["pii_input"] = pii_input


@when('the workflow processes the input')
def workflow_processes_pii(context):
    session_id = f"pii_test_{time.time()}"
    context["pii_session_id"] = session_id
    res = root_agent.process(context["pii_input"], session_id=session_id, mcp_server=context["mcp_server"])
    context["pii_res"] = res


@then('the OpenTelemetry tracer must generate a valid trace_id for distributed tracing')
def verify_opentelemetry_trace_id(context):
    res = context["pii_res"]
    assert "trace_id" in res
    assert len(res["trace_id"]) > 0


@then('the structured JSON logger must emit workflow execution events')
def verify_structured_json_logger(context):
    assert len(root_agent.tracer.active_spans) > 0


@then('all PII and sensitive tokens must be redacted prior to logging and persistent storage')
def verify_pii_redacted(context):
    session_id = context["pii_session_id"]
    state = asyncio.run(root_agent.memory.get_session(session_id))
    assert len(state.turns) > 0
    stored_text = state.turns[0].content

    # Check PII scrubbing
    assert "student@university.edu" not in stored_text
    assert "[REDACTED_EMAIL]" in stored_text
    assert "AIzaSy123456789012345678901234567890" not in stored_text
    assert "[REDACTED_API_KEY]" in stored_text

