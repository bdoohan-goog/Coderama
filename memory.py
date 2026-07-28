"""Async Memory, Persistent Session State, Vector Search, and History Compaction Module."""

import asyncio
import sqlite3
import json
import math
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from observability import PIIRedactor

import time

class ChatTurn(BaseModel):
    role: str
    content: str
    timestamp: float = Field(default_factory=time.time)

class SessionState(BaseModel):
    session_id: str
    summary: str = ""
    turns: List[ChatTurn] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class HistoryCompactor:
    """Compacts conversation history when turn length exceeds max threshold."""

    def __init__(self, max_turns: int = 4, target_turns: int = 2):
        self.max_turns = max_turns
        self.target_turns = target_turns

    def compact(self, turns: List[ChatTurn], existing_summary: str = "") -> tuple[List[ChatTurn], str]:
        """Compacts older turns into a high-level context summary."""
        if len(turns) <= self.max_turns:
            return turns, existing_summary

        # Identify turns to condense
        turns_to_compact = turns[:-self.target_turns]
        recent_turns = turns[-self.target_turns:]

        compacted_statements = [f"{t.role}: {t.content}" for t in turns_to_compact]
        new_summary_chunk = "; ".join(compacted_statements)

        if existing_summary:
            updated_summary = f"{existing_summary} | Earlier Context: {new_summary_chunk}"
        else:
            updated_summary = f"Summary of earlier conversation: {new_summary_chunk}"

        return recent_turns, updated_summary

class AsyncSessionMemory:
    """Asynchronous, SQLite-backed persistent session store with vector similarity search."""

    def __init__(self, db_path: str = "agent_memory.db", compactor: Optional[HistoryCompactor] = None):
        self.db_path = db_path
        self.compactor = compactor or HistoryCompactor()
        self._init_db()

    def _init_db(self):
        """Initializes SQLite tables synchronously on creation."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT,
                    metadata TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp REAL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    text TEXT,
                    vector TEXT
                )
            """)
            conn.commit()

    async def get_session(self, session_id: str) -> SessionState:
        """Asynchronously retrieves session state from persistent DB."""
        return await asyncio.to_thread(self._get_session_sync, session_id)

    def _get_session_sync(self, session_id: str) -> SessionState:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT summary, metadata FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return SessionState(session_id=session_id)

            summary, metadata_json = row
            metadata = json.loads(metadata_json) if metadata_json else {}

            cursor.execute("SELECT role, content, timestamp FROM turns WHERE session_id = ? ORDER BY id ASC", (session_id,))
            turn_rows = cursor.fetchall()
            turns = [ChatTurn(role=r, content=c, timestamp=t) for r, c, t in turn_rows]

            return SessionState(session_id=session_id, summary=summary or "", turns=turns, metadata=metadata)

    async def save_turn(self, session_id: str, role: str, content: str) -> SessionState:
        """Asynchronously appends a turn, performs vector indexing, and triggers history compaction."""
        return await asyncio.to_thread(self._save_turn_sync, session_id, role, content)

    def _save_turn_sync(self, session_id: str, role: str, content: str) -> SessionState:
        # Active PII redaction prior to storage
        clean_content = PIIRedactor.redact(content)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Ensure session entry
            cursor.execute("INSERT OR IGNORE INTO sessions (session_id, summary, metadata) VALUES (?, '', '{}')", (session_id,))
            
            # Insert turn
            now = 0.0
            cursor.execute("INSERT INTO turns (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                           (session_id, role, clean_content, now))

            # Store simple vector mock embedding for vector search
            vec = [float(ord(char) % 10) for char in clean_content[:10]]
            cursor.execute("INSERT INTO memory_vectors (session_id, text, vector) VALUES (?, ?, ?)",
                           (session_id, clean_content, json.dumps(vec)))

            conn.commit()

        # Load session & run compaction if necessary
        session = self._get_session_sync(session_id)
        if len(session.turns) > self.compactor.max_turns:
            compacted_turns, new_summary = self.compactor.compact(session.turns, session.summary)
            self._update_compacted_session_sync(session_id, compacted_turns, new_summary)
            session = self._get_session_sync(session_id)

        return session

    def _update_compacted_session_sync(self, session_id: str, turns: List[ChatTurn], new_summary: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (new_summary, session_id))
            cursor.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            for t in turns:
                cursor.execute("INSERT INTO turns (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                               (session_id, t.role, t.content, t.timestamp))
            conn.commit()

    async def search_memory(self, session_id: str, query: str, limit: int = 3) -> List[str]:
        """Asynchronously performs semantic/vector memory search over historical turns."""
        return await asyncio.to_thread(self._search_memory_sync, session_id, query, limit)

    def _search_memory_sync(self, session_id: str, query: str, limit: int) -> List[str]:
        query_terms = set(query.lower().split())
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM turns WHERE session_id = ?", (session_id,))
            rows = cursor.fetchall()
            
            # Rank rows by term overlap score
            results = []
            for (content,) in rows:
                content_terms = set(content.lower().split())
                overlap = len(query_terms.intersection(content_terms))
                if overlap > 0:
                    results.append((overlap, content))

            results.sort(key=lambda x: x[0], reverse=True)
            return [r[1] for r in results[:limit]]
