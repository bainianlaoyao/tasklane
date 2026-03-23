from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


RESOURCE_CLASSES = (
    "gpu-exclusive",
    "gpu-host-exclusive",
    "cpu-exclusive",
    "cpu-light",
)

ResourceClass = Literal["gpu-exclusive", "gpu-host-exclusive", "cpu-exclusive", "cpu-light"]


class CommandTask(BaseModel):
    cwd: str
    project: str | None = None
    command: list[str]
    env_overrides: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    run_name: str | None = None
    notes: str | None = None

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("cwd must not be empty")
        return stripped

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("command must not be empty")
        return value

    @model_validator(mode="after")
    def validate_resource_class(self) -> "CommandTask":
        resource_class = self.metadata.get("resource_class")
        if resource_class not in RESOURCE_CLASSES:
            valid_values = ", ".join(RESOURCE_CLASSES)
            raise ValueError(f"metadata.resource_class must be one of {valid_values}")
        return self

    @property
    def resource_class(self) -> ResourceClass:
        return self.metadata["resource_class"]
