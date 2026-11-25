"""Strict JSON schemas for tool inputs: written out for a read tool, or generated from the
Pydantic model a proposal is validated with, so the tool and the validation cannot drift apart.
"""

from datetime import date
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel


def strict_object(properties: dict[str, dict], required: list[str]) -> dict:
    """A strict object schema. Properties keep their order, so the model writes them in it."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def properties(model: type[BaseModel]) -> dict[str, dict]:
    """The JSON type of every field of a model, in the order the model declares them."""
    return {name: _json_type(field.annotation) for name, field in model.model_fields.items()}


def model_object(model: type[BaseModel]) -> dict:
    """A model as a strict object. Every field is required in the schema, so the agent never
    skips one. A field the request may not hold is nullable instead: the agent writes null
    rather than inventing a value. A list may be left out."""
    fields = model.model_fields
    required = [name for name, field in fields.items() if field.is_required()]
    nullable = [
        name
        for name, field in fields.items()
        if not field.is_required() and get_origin(field.annotation) is not list
    ]
    described = properties(model)

    for name in nullable:
        described[name]["type"] = [described[name]["type"], "null"]

    return strict_object(described, required + nullable)


def _json_type(annotation: Any) -> dict:
    annotation = _without_none(annotation)

    if annotation is str:
        return {"type": "string"}

    if annotation is float:
        return {"type": "number"}

    if annotation is date:
        return {"type": "string", "format": "date"}

    if get_origin(annotation) is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}

    if get_origin(annotation) is list:
        (item,) = get_args(annotation)

        return {"type": "array", "items": _json_type(item)}

    return model_object(annotation)


def _without_none(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, UnionType):
        (annotation,) = [option for option in get_args(annotation) if option is not NoneType]

    return annotation
