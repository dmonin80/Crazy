"""Validate boundary data before passing it to the domain layer."""

from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from fastapi import HTTPException

Text = Annotated[StrictStr, Field(min_length=1, max_length=4096)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class Login(Payload):
    name: Text
    password: Annotated[StrictStr, Field(max_length=1024)]


class Command(Payload):
    request_id: StrictStr


class Location(Command):
    name: Text
    parent: StrictStr | None = None


class AssetVersion(Payload):
    id: Text
    version: Annotated[int, Field(ge=1)]


class Movement(Command):
    date: Text
    destination: Text


class Allocate(Movement):
    item_id: Text
    quantity: int | float | str
    suffixes: Annotated[list[StrictStr], Field(min_length=1, max_length=10000)]


class Move(Movement):
    source: Text
    assets: Annotated[list[AssetVersion], Field(min_length=1, max_length=10000)]


class BatchLine(Payload):
    kind: Literal["allocate", "move"]
    item_id: Text
    assets: list[AssetVersion] = Field(default_factory=list)


class Batch(Movement):
    lines: Annotated[list[BatchLine], Field(min_length=1, max_length=500)]


class Session(Command):
    name: Text


class Check(Command):
    actual: StrictStr | None = None
    fast: bool = False
    asset_id: Text
    version: Annotated[int, Field(ge=1)]
    status: Literal[
        "В наличии", "Не найдено", "Обнаружено в другом месте", "Не проверено"
    ]


class Scan(Command):
    text: Text
    actual: Text
    fast: bool = False


class Finding(Command):
    description: Text


class Finish(Command):
    confirm: bool


class Import(Payload):
    filename: Text
    data: Annotated[StrictStr, Field(max_length=28_000_000)]


class ImportPreview(Import):
    mapping: dict[str, int]


class Labels(Payload):
    copies: Annotated[int, Field(ge=1, le=100)] = 1
    skip: Annotated[int, Field(ge=0, lt=24)] = 0
    template: Literal["58x40", "40x30", "A4"] = "58x40"
    assets: Annotated[list[StrictStr], Field(min_length=1, max_length=10000)]


class Resolve(Payload):
    text: Text


class User(Payload):
    name: Text
    password: Annotated[StrictStr, Field(max_length=1024)] = ""
    permissions: list[StrictStr] = Field(default_factory=list)
    active: bool = True


def validate(model, payload):
    try:
        validated = model.model_validate(payload)
        payload.update(validated.model_dump())
        if "request_id" in payload:
            UUID(payload["request_id"])
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, ValidationError):
            # Do not return input values: they may contain passwords or file contents.
            detail = "; ".join(
                ".".join(map(str, e["loc"])) + ": " + e["msg"]
                for e in exc.errors(include_input=False)
            )
        else:
            detail = "request_id: требуется UUID"
        raise HTTPException(422, "Проверьте поля запроса: " + detail) from exc
    return payload


def validate_command(action, payload):
    model = {
        "allocate": Allocate,
        "move": Move,
        "return": Move,
        "batch-transfer": Batch,
        "location": Location,
        "session.start": Session,
    }.get(action, Command)
    if action.startswith("session.scan:"):
        model = Scan
    elif action.startswith("session.check:"):
        model = Check
    elif action.startswith("session.finish:"):
        model = Finish
    elif action.startswith("finding:"):
        model = Finding
    elif action.startswith("catalog.create:"):
        model = Location
    validate(model, payload)
