"""Web Application Server for Abstract Algebra Socratic Agent."""

import os
import sys
import json
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Ensure local directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import root_agent, hitl_gateway
from sagemath_mcp_server import SageMathMCPServer
from model_armor import ModelArmorGateway
from observability import PIIRedactor, logger

mcp_server = SageMathMCPServer()
model_armor = ModelArmorGateway()

# Store recent JSON logs for UI live log viewer
recent_logs = []

class AgentWebHandler(BaseHTTPRequestHandler):

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            with open("index.html", "rb") as f:
                self.wfile.write(f.read())
        elif parsed.path == "/api/logs":
            self._set_headers(200)
            self.wfile.write(json.dumps({"logs": recent_logs[-20:]}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8"))
        except Exception:
            payload = {}

        if parsed.path == "/api/chat":
            user_message = payload.get("message", "")
            session_id = payload.get("session_id", "web_session")

            # Check Model Armor security gateway first
            is_flagged, armor_msg = model_armor.inspect_prompt(user_message)
            if is_flagged:
                log_entry = {
                    "timestamp": "NOW",
                    "event_type": "MODEL_ARMOR_FLAGGED",
                    "user_input": PIIRedactor.redact(user_message),
                    "response": armor_msg
                }
                recent_logs.append(log_entry)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "response": armor_msg,
                    "model": "model-armor-gateway",
                    "route": "SAFETY_INTERCEPT",
                    "flagged": True,
                    "trace_id": "armor_intercept_001"
                }).encode("utf-8"))
                return

            # Process through ADK 2.0 root agent graph
            res = asyncio.run(root_agent.process_async(user_message, session_id=session_id, mcp_server=mcp_server))
            recent_logs.append({
                "timestamp": "NOW",
                "event_type": "WORKFLOW_COMPLETE",
                "route": res["route"],
                "model": res["model"],
                "trace_id": res.get("trace_id", "")
            })

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "response": res["response"],
                "model": res["model"],
                "route": res["route"],
                "trace_id": res.get("trace_id", ""),
                "session_summary": res.get("session_summary", ""),
                "turn_count": res.get("turn_count", 0),
                "context": res.get("context", {})
            }).encode("utf-8"))

        elif parsed.path == "/api/verify_table":
            table_str = payload.get("table", "")
            result = mcp_server.verify_group_axioms("{e, a, b}", table_str)
            self._set_headers(200)
            self.wfile.write(json.dumps({"result": result}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Unknown Endpoint"}).encode("utf-8"))

def run_server(port=8080):
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, AgentWebHandler)
    print(f"Server listening on 0.0.0.0:{port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_server(port=port)
