# Abstract Algebra Socratic Tutoring Agent

An enterprise-ready, production-grade Abstract Algebra Educational Agent built using Google's Agent Development Kit (ADK) 2.0, Model Context Protocol (MCP), and Agent-to-Agent (A2A) protocol.

## Architecture

- **Code Entrypoint**: `main.py` (`root_agent`)
- **Specialized Subagents**:
  - `socratic_tutor`: Provides Socratic inquiry and LaTeX formulas without giving direct proofs.
  - `math_verifier`: Connects to SageMath MCP tool to verify Cayley tables and group axioms.
- **Intent Routing**: `parse_student_intent` function routes messages dynamically to Socratic tutor or verifier.
- **Model Context Protocol (MCP)**: `sagemath_mcp_server.py` exposes `verify_group_axioms` with `readOnlyHint: true`.
- **Security**: `model_armor.py` screens prompt injection overrides and PII.
- **Specification-Driven Design**: `specs/algebra-agent.feature` Gherkin feature tests run via `pytest-bdd`.
- **IaC & CI/CD**: `main.tf` (Terraform Cloud Run & Model Armor policy) and `cloudbuild.yaml` (Cloud Build pipeline).

## Setup & Running with `uv`

```bash
# Sync virtual environment & dependencies
uv sync

# Run Gherkin BDD test suite
uv run pytest specs/

# Run main agent
uv run python main.py
```

## Running MCP Manifest

```bash
uv run python -m sagemath_mcp_server --manifest
```

## Infrastructure & CI/CD

Deploy to GCP Cloud Run using Terraform:

```bash
terraform init
terraform apply -var="project_id=YOUR_PROJECT_ID"
```
