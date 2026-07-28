from google.adk import Agent, LlmAgent, WorkflowAgent, Event, types


# =====================================================================
# 1. SPECIALIZED SUBAGENT DEFINITIONS
# =====================================================================


socratic_tutor = LlmAgent(
    name="socratic_tutor",
    model="gemini-2.5-flash-latest",
    instruction="""
    You are a Socratic Abstract Algebra tutor.
    - NEVER generate complete proofs for the student.
    - If a student requests a proof, ask them to identify the relevant algebraic axioms or definitions (e.g., identity, closure, inverses, associativity).
    - Always output mathematical formulas using LaTeX format (enclosed in $ or $$).
    - Keep your prompts short, encouraging, and focused on a single logical step.
    """
)


math_verifier = LlmAgent(
    name="math_verifier",
    model="gemini-2.5-flash-latest",
    instruction="""
    You are a symbolic math verification agent.
    - Analyze the student's mathematical statements or proposed Cayley tables.
    - Use the connected SageMath MCP tool to calculate correctness.
    - If correct, acknowledge it and hand control back.
    - If incorrect, construct a mathematically sound and minimal counterexample.
    """
)


# =====================================================================
# 2. INTENT ROUTING LOGIC
# =====================================================================


def parse_student_intent(node_input: types.Content):
    """Analyzes student input to route to the correct subagent."""
    text_content = node_input.parts[0].text.strip().lower()
    
    # Simple routing based on key mathematical actions
    if any(keyword in text_content for keyword in ["prove", "proof", "show that", "is a group"]):
        yield Event(route=["SOCRATIC_ROUTE"])
    elif any(keyword in text_content for keyword in ["check", "is this correct", "evaluate", "table"]):
        yield Event(route=["VERIFIER_ROUTE"])
    else:
        # Default fallback to Socratic guidance
        yield Event(route=["SOCRATIC_ROUTE"])


# =====================================================================
# 3. DECLARATIVE GRAPH ORCHESTRATION
# =====================================================================


root_agent = WorkflowAgent(
    name="algebra_agent_orchestrator",
    edges=[
        ("START", parse_student_intent),
        (parse_student_intent, {
            "SOCRATIC_ROUTE": socratic_tutor,
            "VERIFIER_ROUTE": math_verifier
        })
    ]
)
