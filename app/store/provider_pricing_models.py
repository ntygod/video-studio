"""Private ORM mapping for optional Provider model pricing.

Alembic owns the table. Keeping the mapping outside ``Base`` preserves the
historical pre-control-plane schema used by legacy migration fixtures.
"""

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, registry

provider_pricing_registry = registry()


@provider_pricing_registry.mapped
class ModelPricingProfileRow:
    __tablename__ = "model_pricing_profiles"

    model_profile_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    pricing_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = ["ModelPricingProfileRow", "provider_pricing_registry"]
