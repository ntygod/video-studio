"""Asset repository extensions with explicit partial-update semantics."""

from __future__ import annotations

from typing import Any

from .models import AssetRow
from .repositories import AssetRepository, NotFoundError

_UNSET = object()


class SemanticAssetRepository(AssetRepository):
    """Preserve the difference between omitted and explicitly cleared fields."""

    def update_scope(
        self,
        asset_id: str,
        *,
        unit_id: str | None | object = _UNSET,
        shot_id: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise NotFoundError(asset_id)
        if unit_id is not _UNSET:
            row.unit_id = unit_id or None
        if shot_id is not _UNSET:
            row.shot_id = shot_id or None
        self.session.flush()
        return self._data(row)


ASSET_SCOPE_UNSET = _UNSET

__all__ = ["ASSET_SCOPE_UNSET", "SemanticAssetRepository"]
