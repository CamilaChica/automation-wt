from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel


class ToolNotFoundError(LookupError):
    pass


class ToolAuthorizationError(PermissionError):
    pass


class ToolConfirmationRequired(PermissionError):
    pass


class ToolDefinition(BaseModel):
    name: str
    description: str
    arguments_model: Type[BaseModel]
    allowed_roles: frozenset[str]
    requires_confirmation: bool = False

    def realtime_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        self._definitions = {definition.name: definition for definition in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("Tool names must be unique.")

    def realtime_definitions(self) -> list[dict[str, Any]]:
        return [definition.realtime_definition() for definition in self._definitions.values()]

    def validate_call(
        self,
        name: str,
        arguments: dict,
        *,
        role: str,
        human_confirmed: bool = False,
    ) -> dict[str, Any]:
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolNotFoundError(name)
        if role not in definition.allowed_roles:
            raise ToolAuthorizationError(name)
        if definition.requires_confirmation and not human_confirmed:
            raise ToolConfirmationRequired(name)

        return definition.arguments_model.model_validate(arguments).model_dump()
