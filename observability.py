"""Observability, OpenTelemetry Tracing, Structured JSON Logging, and PII Redaction Module."""

import re
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional

# Configure standard Python logger for JSON formatting
logger = logging.getLogger("adk_observability")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    logger.addHandler(handler)


class PIIRedactor:
    """Active PII & Sensitive Credential Redactor for logs and persistent storage."""

    EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
    SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    API_KEY_REGEX = re.compile(r"(?:AIza[0-9A-Za-z-_]{30,35}|sk-[0-9A-Za-z]{20,}|bearer\s+[0-9A-Za-z._-]+)", re.IGNORECASE)

    @classmethod
    def redact(cls, text: str) -> str:
        """Scrubs email, phone, SSN, and API key credentials from text."""
        if not isinstance(text, str):
            return text

        scrubbed = cls.EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
        scrubbed = cls.PHONE_REGEX.sub("[REDACTED_PHONE]", scrubbed)
        scrubbed = cls.SSN_REGEX.sub("[REDACTED_SSN]", scrubbed)
        scrubbed = cls.API_KEY_REGEX.sub("[REDACTED_API_KEY]", scrubbed)
        return scrubbed


class StructuredLogger:
    """Emits structured JSON logs for agent intent, routing decisions, tool calls, and outcomes."""

    def __init__(self, service_name: str = "algebra_socratic_agent"):
        self.service_name = service_name

    def log_event(self, event_type: str, trace_id: str, span_id: str, data: Dict[str, Any]):
        """Logs a structured JSON log entry after redacting PII."""
        sanitized_data = {
            k: PIIRedactor.redact(str(v)) if isinstance(v, str) else v
            for k, v in data.items()
        }

        log_record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "service": self.service_name,
            "event_type": event_type,
            "trace_id": trace_id,
            "span_id": span_id,
            "payload": sanitized_data
        }
        logger.info(json.dumps(log_record))
        return log_record


class OpenTelemetrySpan:
    """Simulates an OpenTelemetry distributed tracing span."""

    def __init__(self, name: str, trace_id: str, parent_span_id: Optional[str] = None):
        self.name = name
        self.trace_id = trace_id
        self.span_id = str(uuid.uuid4())[:8]
        self.parent_span_id = parent_span_id
        self.start_time = time.time()
        self.attributes: Dict[str, Any] = {}
        self.end_time: Optional[float] = None

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = PIIRedactor.redact(str(value)) if isinstance(value, str) else value

    def end(self):
        self.end_time = time.time()


class OpenTelemetryTracer:
    """OpenTelemetry distributed tracer managing spans and context propagation."""

    def __init__(self, service_name: str = "algebra_socratic_agent"):
        self.service_name = service_name
        self.active_spans: List[OpenTelemetrySpan] = []

    def start_span(self, name: str, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None) -> OpenTelemetrySpan:
        t_id = trace_id or str(uuid.uuid4())
        span = OpenTelemetrySpan(name=name, trace_id=t_id, parent_span_id=parent_span_id)
        self.active_spans.append(span)
        return span
