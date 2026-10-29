# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Parse one Pi session branch and capture its visible events as Sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, JsonValue, field_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_VERSION = "1"
_CONTROL_RECORD_TYPES = frozenset({"session"})


def pi_event_source_id(session_id: str, event_id: str, /) -> str:
    """Build the stable Source identity of one visible Pi session event."""

    if not isinstance(session_id, str) or not session_id or session_id != session_id.strip():
        raise ValueError("session_id must be non-empty and must not contain surrounding whitespace")
    if not isinstance(event_id, str) or not event_id or event_id != event_id.strip():
        raise ValueError("event_id must be non-empty and must not contain surrounding whitespace")
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pi-event source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


class PiSessionInput(BaseModel):
    """One Pi session archive and the branch leaf to read from it."""

    content: bytes
    leaf_id: str | None = None

    @field_validator("leaf_id")
    @classmethod
    def validate_leaf_id(cls, value: str | None) -> str | None:
        if value is not None and (not value or not value.strip() or value != value.strip()):
            raise ValueError("leaf_id must be a non-empty trimmed string when provided")
        return value


class PiEventInput(BaseModel):
    """One visible event on the selected branch, with its complete input record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Source that keeps the original event text and identity."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @property
    def source_id(self) -> str:
        """Expose the identity as a reference part without duplicating the field."""

        return self.name


class PiEventTextEvidenceProjection:
    """Project one Pi event as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


class PiEventSourceAdapter:
    """Resolve and read the Pi event Source."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=pi_event_source_id(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PiEventSourceAdapter(),
    projections=(PiEventTextEvidenceProjection(),),
)


def parse_pi_session(document: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Return the visible events of the selected branch ordered from root to leaf."""

    _, events = _parse_document(document.content, document.leaf_id)
    return events


class PiSessionConnector:
    """Incrementally import one Pi session branch through the Connector lifecycle."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        session_id, events = _parse_document(self._path.read_bytes(), self._leaf_id)
        checkpoint_session, imported = _read_checkpoint(session.checkpoint)
        if checkpoint_session != session_id:
            imported = {}

        fingerprints: dict[str, str] = {}
        pending: list[PiEventInput] = []
        for event in events:
            fingerprint = _record_fingerprint(event.record)
            known = imported.get(event.event_id)
            if known is not None:
                if known != fingerprint:
                    raise ValueError(f"Pi event {event.event_id!r} was rewritten after it was imported")
                continue
            pending.append(event)
            fingerprints[event.event_id] = fingerprint

        for event in pending:
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)

        merged = {**imported, **fingerprints}
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"session_id": session_id, "events": dict(sorted(merged.items()))},
        )


def _parse_document(content: bytes, leaf_id: str | None) -> tuple[str, tuple[PiEventInput, ...]]:
    records = _read_records(content)
    session_id = _read_session_id(records[0])

    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("every Pi record must declare a non-empty string id")
        if event_id in nodes:
            raise ValueError(f"duplicate Pi record id {event_id!r}")
        parent_id = _parent_id(record)
        if parent_id is not None and parent_id not in nodes:
            raise ValueError(f"Pi record {event_id!r} references a parent that was not seen before it")
        nodes[event_id] = record
        order.append(event_id)

    leaf = leaf_id if leaf_id is not None else (order[-1] if order else None)
    if leaf is None or leaf not in nodes:
        raise ValueError("the selected Pi leaf does not exist in the session archive")

    chain: list[dict[str, Any]] = []
    current: str | None = leaf
    while current is not None:
        record = nodes[current]
        chain.append(record)
        current = _parent_id(record)
    chain.reverse()

    events: list[PiEventInput] = []
    for record in chain:
        event = _render_event(session_id, record)
        if event is not None:
            pi_event_source_id(event.session_id, event.event_id)
            events.append(event)
    return session_id, tuple(events)


def _read_records(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session content must be JSON Lines") from error
        if not isinstance(record, dict):
            raise ValueError("every Pi session line must be a JSON object")
        records.append(record)
    if not records:
        raise ValueError("Pi session archive is empty")
    return records


def _read_session_id(header: dict[str, Any]) -> str:
    if header.get("type") != "session":
        raise ValueError("the first Pi record must be the session header")
    if header.get("version") != 3:
        raise ValueError("the Pi session header must declare version 3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("the Pi session header must declare a non-empty string id")
    return session_id


def _parent_id(record: dict[str, Any]) -> str | None:
    parent_id = record.get("parentId")
    if parent_id is None or parent_id == "":
        return None
    if not isinstance(parent_id, str):
        raise ValueError("Pi parentId must be a string or null")
    return parent_id


def _render_event(session_id: str, record: dict[str, Any]) -> PiEventInput | None:
    record_type = record.get("type")
    if not isinstance(record_type, str):
        return None
    if record_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        body = _message_body(role, message)
    elif record_type in {"compaction", "branch_summary"}:
        role = record_type
        body = _content_body(record.get("summary"))
    elif record_type == "custom_message":
        role = "custom"
        body = _content_body(record.get("content"))
    else:
        return None
    if role in _CONTROL_RECORD_TYPES or not body.strip():
        return None
    event_id = record.get("id")
    if not isinstance(event_id, str):
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=_parent_id(record),
        event_type=record_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(role: str, message: dict[str, Any]) -> str:
    if role == "toolResult":
        name = message.get("toolName")
        call_id = message.get("toolCallId")
        text = _content_body(message.get("content"))
        return f"[tool_result {name} {call_id}] {text}"
    if role == "bashExecution":
        command = message.get("command")
        output = message.get("output")
        return f"$ {command}\n{output}"
    return _content_body(message.get("content"))


def _content_body(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "toolCall":
            parts.append(
                f"[tool_call {block.get('name')} {block.get('id')}] {_compact_json(block.get('arguments'))}"
            )
    return "\n".join(parts)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_fingerprint(record: dict[str, Any]) -> str:
    encoded = _compact_json(record).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_checkpoint(checkpoint: JsonValue | None) -> tuple[str | None, dict[str, str]]:
    if not isinstance(checkpoint, dict):
        return None, {}
    session_id = checkpoint.get("session_id")
    events = checkpoint.get("events")
    imported = {
        event_id: fingerprint
        for event_id, fingerprint in (events.items() if isinstance(events, dict) else ())
        if isinstance(event_id, str) and isinstance(fingerprint, str)
    }
    return (session_id if isinstance(session_id, str) else None), imported


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PI_SESSION_VERSION",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
