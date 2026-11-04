"""Per-user parser choices (ARCHITECTURE §8): which installed parsers detection may pick, and
each one's options, validated by the adapter's own `options_schema` (a Pydantic model)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

from finboard.db.uow import UnitOfWork
from finboard.domain.errors import NotFound, ValidationFailed
from finboard.parsers.registry import ParserRegistry
from finboard.parsers.sdk import StatementParser

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ParserChoice:
    parser: StatementParser
    enabled: bool
    options: dict[str, Any]


def options_schema(parser: StatementParser) -> type[BaseModel] | None:
    schema = getattr(parser, "options_schema", None)
    return schema if isinstance(schema, type) and issubclass(schema, BaseModel) else None


def options_json_schema(parser: StatementParser) -> dict[str, Any] | None:
    schema = options_schema(parser)
    return schema.model_json_schema() if schema else None


def parse_options(parser: StatementParser, stored: dict[str, Any]) -> BaseModel | None:
    """The options model to pass to `parse()`. Stored options that no longer validate (the
    adapter changed its schema) fall back to the adapter's defaults rather than failing."""
    schema = options_schema(parser)
    if schema is None:
        return None
    try:
        return schema.model_validate(stored)
    except ValidationError:
        log.warning("parsers.options_invalid", parser_id=parser.id)
        return schema()


class ParserSettingsService:
    def __init__(self, uow: UnitOfWork, registry: ParserRegistry) -> None:
        self.uow = uow
        self.registry = registry

    async def choices(self) -> list[ParserChoice]:
        stored = await self.uow.parser_settings.all()
        result = []
        for parser in self.registry.all():
            setting = stored.get(parser.id)
            schema = options_schema(parser)
            options = dict(setting.options) if setting else {}
            if schema is not None:
                options = parse_options(parser, options).model_dump(mode="json")  # type: ignore[union-attr]
            result.append(ParserChoice(parser, setting.enabled if setting else True, options))
        return result

    async def update(
        self, parser_id: str, *, enabled: bool | None = None, options: dict[str, Any] | None = None
    ) -> ParserChoice:
        parser = self.registry.get(parser_id)
        if parser is None:
            raise NotFound(f"No installed parser '{parser_id}'")
        current = next(c for c in await self.choices() if c.parser.id == parser_id)
        new_options = current.options
        if options is not None:
            schema = options_schema(parser)
            if schema is None:
                if options:
                    raise ValidationFailed("This parser has no options")
                new_options = {}
            else:
                try:
                    new_options = schema.model_validate(options).model_dump(mode="json")
                except ValidationError as exc:
                    first = exc.errors()[0]
                    where = ".".join(str(p) for p in first["loc"]) or "options"
                    raise ValidationFailed(f"Invalid option {where}: {first['msg']}") from None
        new_enabled = current.enabled if enabled is None else enabled
        await self.uow.parser_settings.put(parser_id, enabled=new_enabled, options=new_options)
        await self.uow.commit()
        return ParserChoice(parser, new_enabled, new_options)

    async def enabled_ids(self) -> list[str]:
        return [c.parser.id for c in await self.choices() if c.enabled]
