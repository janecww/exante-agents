"""Auto-generate a human-readable JSON skeleton from a Pydantic model.

This is the single source of truth for what the LLM must return: rather
than maintaining a separate output template by hand, the expected JSON
shape is derived directly from the existing Pydantic model classes by
walking their field annotations. Whenever a model changes, the skeleton
shown to the LLM changes with it automatically — there is no schema
drift to keep in sync.

Deliberately not `model_json_schema()`: raw JSON Schema is verbose
(`$defs`, `anyOf`, `title`, ...) and harder for an LLM to follow than a
plain example of the expected JSON itself.
"""

import types
import typing

from pydantic import BaseModel

_PLACEHOLDER_BY_TYPE = {
    str: "",
    int: 0,
    float: 0.0,
    bool: False,
}


def _skeleton_for_annotation(annotation: object) -> object:
    """Build a placeholder value for a single field's type annotation."""
    origin = typing.get_origin(annotation)

    if origin in (typing.Union, types.UnionType):
        # Optional[X] / X | None -> the field is still included, using
        # the skeleton for whichever member type isn't NoneType.
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _skeleton_for_annotation(args[0]) if args else None

    if origin is list:
        (item_type,) = typing.get_args(annotation) or (str,)
        return [_skeleton_for_annotation(item_type)]

    if origin is dict:
        return {}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return build_json_skeleton(annotation)

    return _PLACEHOLDER_BY_TYPE.get(annotation)


def build_json_skeleton(model_cls: type[BaseModel]) -> dict:
    """Recursively build a deterministic JSON skeleton for a Pydantic model.

    Every field is included (optional fields are not omitted), every
    nested `BaseModel` is expanded into its own skeleton object, and
    every list field shows one representative item so the LLM can see
    the exact shape each list element must take.
    """
    return {
        name: _skeleton_for_annotation(field.annotation)
        for name, field in model_cls.model_fields.items()
    }
