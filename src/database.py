"""Database engine core implementation for PatchDB."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .client import OpenRouterClient
from .errors import ModelSaidNo, PatchDBError
from .query import Condition


class PatchDB:
    """A database that stores state in a local JSON file and reads via LLM API requests."""

    READ_PROMPT: str = """You are PatchDB, a read-only database. You look at the current state and answer questions about it.

Current state:
```json
{state_json}
```

Request: {operation}

Rules:
- Return ONLY a JSON object with a single key "result" containing the answer.
- For "GET" with a key: result is the value at that key (or null if not found).
- For "DUMP": result is the full state object.
- For "ALL" with a table name: result is the array of documents in that table.
- For "GET_DOC" with a doc_id: result is the document with that _id (or null).
- For "SEARCH" with a condition: result is an array of matching documents.
- For "CONTAINS" with a condition: result is true or false.

Read only. Never modify state. Valid JSON only."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "openai/gpt-5.4-nano",
        file: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 30,
        retries: int = 3,
        temperature: float = 0,
        max_tokens: int = 2048,
    ) -> None:
        """Initialize local file state and the API query client."""
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise PatchDBError("Pass api_key= or set OPENROUTER_API_KEY.")

        self.client = OpenRouterClient(
            api_key=resolved_key,
            base_url=base_url,
            timeout=timeout,
            retries=retries,
        )
        self.model = model
        self.file = Path(file).expanduser() if file else None
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.last_raw_response: Optional[str] = None
        self.last_prompt: Optional[str] = None
        self.state: Dict[str, Any] = {}

        if self.file and self.file.exists():
            try:
                raw = self.file.read_text(encoding="utf-8")
                if raw.strip():
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        self.state = parsed
            except (json.JSONDecodeError, OSError):
                # Ignore corrupt local state load attempts, fall back to empty state
                pass

    def _save(self) -> None:
        """Atomically persist current database state to the local JSON file."""
        if not self.file:
            return
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(self.file.suffix + ".tmp")
            tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
        except OSError as exc:
            raise PatchDBError(f"Failed to save state to file {self.file}: {exc}") from exc

    def _read(self, operation: str, **kwargs: Any) -> Any:
        """Execute a read-only query by requesting the AI model process the current database state."""
        state_json = json.dumps(dict(self.state), indent=2, sort_keys=True, ensure_ascii=False)
        parts = [f"{k}={v}" for k, v in kwargs.items()]
        op_desc = f"{operation}({', '.join(parts)})" if parts else operation
        prompt = self.READ_PROMPT.format(state_json=state_json, operation=op_desc)
        self.last_prompt = prompt

        messages = [
            {"role": "system", "content": "You are PatchDB. Read-only JSON database."},
            {"role": "user", "content": prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        result = self.client.request_json(payload)
        choices = result.get("choices") or []
        if not choices:
            raise ModelSaidNo("OpenRouter returned no choices.")

        content = choices[0].get("message", {}).get("content", "")
        self.last_raw_response = content
        parsed = self.client.extract_json_object(content)
        return parsed.get("result")

    def set(self, key: str, value: Any) -> Dict[str, Any]:
        """Store a serialized key-value pair locally."""
        if not isinstance(key, str) or not key:
            raise PatchDBError("Key must be a non-empty string.")
        try:
            json.dumps(value)
        except TypeError as exc:
            raise PatchDBError("Value must be JSON-serializable.") from exc
        self.state[key] = copy.deepcopy(value)
        self._save()
        return copy.deepcopy(self.state)

    def get(self, key: Optional[str] = None) -> Any:
        """Query a key's value via the external LLM model."""
        return self._read("GET", key=key)

    def delete(self, key: str) -> Dict[str, Any]:
        """Delete a key from the local state."""
        if key not in self.state:
            return copy.deepcopy(self.state)
        del self.state[key]
        self._save()
        return copy.deepcopy(self.state)

    def reset(self) -> Dict[str, Any]:
        """Wipe database state and persist the reset configuration."""
        self.state = {}
        self._save()
        return copy.deepcopy(self.state)

    def dump(self) -> Any:
        """Query the full state object from the AI model."""
        return self._read("DUMP")

    def keys(self) -> List[str]:
        """Return top-level database keys directly from local cache."""
        return list(self.state.keys())

    def close(self) -> None:
        """Finalize and persist outstanding transactions."""
        self._save()

    def insert(self, document: Mapping[str, Any], table: str = "default") -> int:
        """Insert a document locally under a specified table name."""
        if not isinstance(document, Mapping):
            raise PatchDBError("insert() expects a JSON object.")
        try:
            json.dumps(document)
        except TypeError as exc:
            raise PatchDBError("Document must be JSON-serializable.") from exc

        tables = self.state.setdefault("tables", {})
        docs = tables.setdefault(table, [])
        doc = copy.deepcopy(dict(document))
        ids = [int(d["_id"]) for d in docs if isinstance(d.get("_id"), (int, float))]
        doc["_id"] = (max(ids, default=0) + 1)
        docs.append(doc)
        self._save()
        return int(doc["_id"])

    def insert_multiple(self, documents: Iterable[Mapping[str, Any]], table: str = "default") -> List[int]:
        """Insert multiple documents locally in a single sequence of writes."""
        return [self.insert(doc, table) for doc in documents]

    def all(self, table: str = "default") -> Any:
        """Query all documents belonging to a table using the AI model."""
        return self._read("ALL", table=table)

    def search(self, condition: Condition, table: str = "default") -> Any:
        """Search table documents matching a condition structure using the AI model."""
        return self._read("SEARCH", table=table, condition=str(condition))

    def contains(self, condition: Condition, table: str = "default") -> Any:
        """Verify document existence matching a condition via the AI model."""
        return self._read("CONTAINS", table=table, condition=str(condition))

    def remove(self, condition: Condition, table: str = "default") -> int:
        """Remove matching documents from the table locally using Python condition logic."""
        tables = self.state.setdefault("tables", {})
        docs = tables.get(table, [])
        before = len(docs)
        tables[table] = [d for d in docs if not condition.matches(d)]
        self._save()
        return before - len(tables[table])

    def update(self, document: Mapping[str, Any], condition: Optional[Condition] = None, table: str = "default") -> int:
        """Update matching table documents locally applying key patches."""
        if not isinstance(document, Mapping):
            raise PatchDBError("update() expects a JSON object.")
        tables = self.state.setdefault("tables", {})
        docs = tables.setdefault(table, [])
        changes = dict(document)
        changes.pop("_id", None)
        count = 0
        for doc in docs:
            if condition is None or condition.matches(doc):
                doc.update(copy.deepcopy(changes))
                count += 1
        if count:
            self._save()
        return count

    def upsert(self, document: Mapping[str, Any], key_field: str = "id", table: str = "default") -> int:
        """Upsert a document based on field uniqueness check or generate key locally."""
        if not isinstance(document, Mapping):
            raise PatchDBError("upsert() expects a JSON object.")
        tables = self.state.setdefault("tables", {})
        docs = tables.setdefault(table, [])
        key_value = document.get(key_field)
        if key_value is None:
            return self.insert(document, table)
        for doc in docs:
            if doc.get(key_field) == key_value:
                doc.update(copy.deepcopy(dict(document)))
                self._save()
                doc_id = doc.get("_id")
                if doc_id is not None:
                    return int(doc_id)
                ids = [int(d["_id"]) for d in docs if isinstance(d.get("_id"), (int, float))]
                doc["_id"] = (max(ids, default=0) + 1)
                self._save()
                return int(doc["_id"])
        return self.insert(document, table)

    def truncate(self, table: str = "default") -> None:
        """Wipe all documents from a table locally."""
        tables = self.state.setdefault("tables", {})
        tables[table] = []
        self._save()

    def count(self, table: str = "default") -> int:
        """Get the count of documents within a table directly from local cached state."""
        tables = self.state.setdefault("tables", {})
        return len(tables.get(table, []))

    def doctor(self) -> Dict[str, Any]:
        """Diagnose communication and validation states of the backend model end-to-end."""
        probe_key = "__patchdb_doctor_probe__"
        probe_value = {"status": "praying", "vibe": "structurally unsound but functional"}
        before = copy.deepcopy(self.state)
        try:
            self.set(probe_key, probe_value)
            got = self.get(probe_key)
            self.delete(probe_key)
            ok = isinstance(got, dict) and got.get("status") == "praying"
            return {
                "ok": ok,
                "model": self.model,
                "state_keys": len(self.state),
                "message": "AI read the probe correctly." if ok else "AI lied. As predicted.",
            }
        except Exception as exc:
            self.state = before
            self._save()
            return {
                "ok": False,
                "model": self.model,
                "error": str(exc),
                "message": "Doctor mode hit a wall.",
            }
