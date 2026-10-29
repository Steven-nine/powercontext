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

"""Row-level CSV Sources that keep exact records behind stable identities."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, field_validator, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_SOURCE_VERSION = "1"


def csv_row_source_id(document_id: str, primary_key_value: str, /) -> str:
    """Build the stable, delimiter-safe Source identity for one CSV record."""

    if not isinstance(document_id, str) or not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and must not contain leading or trailing whitespace")
    if not isinstance(primary_key_value, str) or not primary_key_value or not primary_key_value.strip():
        raise ValueError("primary key value must be a non-blank string")
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"csv-row source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


class CSVDocumentInput(BaseModel):
    """One fully offline CSV document addressed by document identity and primary key."""

    document_id: str
    primary_key: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("document_id must be non-empty and must not contain leading or trailing whitespace")
        return value

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("primary_key must be a non-blank column name")
        return value


class CSVRowInput(BaseModel):
    """One parsed CSV record with its document, primary key and exact field values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_width(self) -> CSVRowInput:
        if len(self.columns) != len(self.values):
            raise ValueError("columns and values must have the same length")
        return self


class CSVRowSource(Source):
    """Captured Source for one CSV record that keeps column order and raw values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @property
    def source_id(self) -> str:
        """Expose the identity as a reference part without duplicating the field."""

        return self.name

    @model_validator(mode="after")
    def validate_width(self) -> CSVRowSource:
        if len(self.columns) != len(self.values):
            raise ValueError("columns and values must have the same length")
        return self


class CSVRowTextEvidenceProjection:
    """Project one row as canonical text evidence with its full record metadata."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.name,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class CSVRowSourceAdapter:
    """Resolve and read the row-level captured CSV Source."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        return CSVRowSource(
            name=csv_row_source_id(value.document_id, value.primary_key_value),
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    projections=(CSVRowTextEvidenceProjection(),),
)


def parse_csv_document(document: CSVDocumentInput, /) -> tuple[CSVRowInput, ...]:
    """Parse one offline CSV document into row Sources, or fail without partial rows."""

    records = _read_records(_decode_content(document.content))
    if not records:
        raise ValueError("CSV document must contain a header record")
    header = records[0]
    _validate_header(header)
    try:
        key_index = header.index(document.primary_key)
    except ValueError:
        raise ValueError(f"primary key {document.primary_key!r} is not a header column") from None

    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for record in records[1:]:
        if not record:
            continue
        if len(record) != len(header):
            raise ValueError("CSV record width must match the header width")
        primary_key_value = record[key_index]
        if not primary_key_value.strip():
            raise ValueError("CSV primary key value must not be blank")
        if primary_key_value in seen_keys:
            raise ValueError("CSV primary key value must be unique within one document")
        seen_keys.add(primary_key_value)
        row = CSVRowInput(
            document_id=document.document_id,
            primary_key=document.primary_key,
            primary_key_value=primary_key_value,
            columns=tuple(header),
            values=tuple(record),
        )
        # Identity bounds are part of document validity, so reject oversized rows while parsing.
        csv_row_source_id(row.document_id, row.primary_key_value)
        rows.append(row)
    return tuple(rows)


def _decode_content(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error


def _read_records(text: str) -> list[tuple[str, ...]]:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        return [tuple(record) for record in reader]
    except csv.Error as error:
        raise ValueError("CSV content is not a well-formed quoted document") from error


def _validate_header(header: tuple[str, ...]) -> None:
    if not header:
        raise ValueError("CSV header must not be empty")
    for column in header:
        if not column or not column.strip():
            raise ValueError("CSV header columns must be non-blank")
    if len(set(header)) != len(header):
        raise ValueError("CSV header columns must be unique")


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSV_ROW_SOURCE_VERSION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]
