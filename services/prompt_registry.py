"""Versioned persistence and lookup for prompt techniques and policies."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.async_models import PromptSecurityRecord, PromptTechniqueRecord, ScalingPromptRecord
from schemas.rag import PromptSecurity, PromptTechnique, ScalingPromptEngineering


class PromptRegistryError(RuntimeError):
    pass


class PromptRegistry:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def save_technique(self, technique: PromptTechnique) -> None:
        try:
            async with self.session_factory() as session:
                await session.merge(PromptTechniqueRecord(
                    id=self._stable_id("technique", technique.name),
                    **technique.model_dump(),
                ))
                await session.commit()
        except Exception as exc:
            raise PromptRegistryError(f"Unable to save prompt technique '{technique.name}'.") from exc

    async def list_techniques(self) -> list[PromptTechnique]:
        try:
            async with self.session_factory() as session:
                records = (await session.scalars(select(PromptTechniqueRecord).order_by(PromptTechniqueRecord.name))).all()
            return [PromptTechnique(
                name=record.name,
                description=record.description,
                template=record.template,
                examples=record.examples or [],
            ) for record in records]
        except Exception as exc:
            raise PromptRegistryError("Unable to load prompt techniques.") from exc

    async def save_security_policy(self, name: str, policy: PromptSecurity) -> None:
        try:
            async with self.session_factory() as session:
                await session.merge(PromptSecurityRecord(
                    id=self._stable_id("security", name),
                    name=name,
                    **policy.model_dump(),
                ))
                await session.commit()
        except Exception as exc:
            raise PromptRegistryError(f"Unable to save prompt security policy '{name}'.") from exc

    async def get_security_policy(self, name: str) -> PromptSecurity | None:
        try:
            async with self.session_factory() as session:
                record = await session.scalar(select(PromptSecurityRecord).where(PromptSecurityRecord.name == name))
            if record is None:
                return None
            return PromptSecurity(
                sanitize_input=record.sanitize_input,
                detect_injection=record.detect_injection,
                mask_pii=record.mask_pii,
                prevent_jailbreaks=record.prevent_jailbreaks,
                block_injection=record.block_injection,
            )
        except Exception as exc:
            raise PromptRegistryError(f"Unable to load prompt security policy '{name}'.") from exc

    async def save_template(self, prompt: ScalingPromptEngineering) -> None:
        try:
            async with self.session_factory() as session:
                await session.merge(ScalingPromptRecord(
                    id=self._stable_id("template", f"{prompt.name}:{prompt.version}"),
                    name=prompt.name,
                    version=prompt.version,
                    template=prompt.template,
                    variables=prompt.variables,
                    prompt_metadata=prompt.metadata,
                ))
                await session.commit()
        except Exception as exc:
            raise PromptRegistryError(
                f"Unable to save prompt template '{prompt.name}' version {prompt.version}."
            ) from exc

    async def get_template(self, name: str, version: int | None = None) -> ScalingPromptEngineering | None:
        try:
            async with self.session_factory() as session:
                statement = select(ScalingPromptRecord).where(ScalingPromptRecord.name == name)
                if version is not None:
                    statement = statement.where(ScalingPromptRecord.version == version)
                statement = statement.order_by(ScalingPromptRecord.version.desc()).limit(1)
                record = await session.scalar(statement)
            if record is None:
                return None
            return ScalingPromptEngineering(
                name=record.name,
                version=record.version,
                template=record.template,
                variables=record.variables or [],
                metadata=record.prompt_metadata or {},
            )
        except Exception as exc:
            raise PromptRegistryError(f"Unable to load prompt template '{name}'.") from exc

    @staticmethod
    def _stable_id(kind: str, name: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"winged-tycoons:{kind}:{name}").hex