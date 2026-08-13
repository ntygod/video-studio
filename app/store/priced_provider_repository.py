"""Provider repository extension that persists normalized model pricing."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from app.domain.provider_pricing import normalize_model_pricing

from .json_codec import dumps, loads
from .provider_pricing_models import ModelPricingProfileRow
from .repositories import ProviderRepository


class PricedProviderRepository(ProviderRepository):
    def _pricing_by_model(self, model_ids: list[str]):
        if not model_ids:
            return {}
        rows = self.session.scalars(
            select(ModelPricingProfileRow).where(
                ModelPricingProfileRow.model_profile_id.in_(model_ids)
            )
        ).all()
        return {row.model_profile_id: row for row in rows}

    def _data(self, row, include_secret: bool = False) -> dict[str, Any]:
        data = super()._data(row, include_secret=include_secret)
        pricing = self._pricing_by_model(
            [str(model["id"]) for model in data.get("models") or []]
        )
        for model in data.get("models") or []:
            price_row = pricing.get(str(model["id"]))
            model["pricing"] = (
                loads(price_row.pricing_json, {}) if price_row else {}
            )
            model["pricing_updated_at"] = (
                price_row.updated_at if price_row else None
            )
        return data

    def add_model(
        self,
        provider_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = normalize_model_pricing(data.get("pricing"))
        saved = super().add_model(provider_id, data)
        if normalized:
            now = time.time()
            self.session.add(
                ModelPricingProfileRow(
                    model_profile_id=str(saved["id"]),
                    pricing_json=dumps(normalized),
                    updated_at=now,
                )
            )
            self.session.flush()
            saved["pricing"] = normalized
            saved["pricing_updated_at"] = now
        else:
            saved["pricing"] = {}
            saved["pricing_updated_at"] = None
        return saved


__all__ = ["PricedProviderRepository"]
