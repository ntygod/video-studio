"""Add runtime admission slots and semantic Agent event deduplication."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from alembic import op
import sqlalchemy as sa

revision = "20260812_0011"
down_revision = "20260812_0010"
branch_labels = None
depends_on = None

AGENT_PLAN_KIND = "agent.turn"
DEFAULT_AGENT_CAPACITY = 10


def _dedupe_key(event_type: str, payload: dict[str, Any]) -> str | None:
    turn_id = str(payload.get("turn_id") or "")
    if event_type in {"agent.step.start", "agent.step.done"}:
        step_id = str(payload.get("step_id") or "")
        return f"{event_type}:{step_id}" if step_id else None
    if event_type == "agent.entity":
        entity = payload.get("entity") or {}
        entity_type = str(entity.get("type") or "")
        entity_id = str(entity.get("id") or "")
        if entity_type and entity_id:
            return f"{event_type}:{entity_type}:{entity_id}"
        return None
    if event_type == "agent.proposal":
        proposal = payload.get("proposal") or {}
        proposal_id = str(proposal.get("id") or "")
        return f"{event_type}:{proposal_id}" if proposal_id else None
    if event_type in {"agent.message", "agent.done"}:
        return f"{event_type}:{turn_id or 'plan'}"
    return None


def upgrade() -> None:
    op.create_table(
        "runtime_admission_buckets",
        sa.Column("key", sa.String(length=160), primary_key=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "runtime_admission_reservations",
        sa.Column("plan_id", sa.String(length=64), primary_key=True),
        sa.Column("bucket_key", sa.String(length=160), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.Float(), nullable=False),
        sa.Column("released_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bucket_key"],
            ["runtime_admission_buckets.key"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_runtime_admission_reservations_bucket_key",
        "runtime_admission_reservations",
        ["bucket_key"],
    )
    op.create_index(
        "ix_runtime_admission_reservations_bucket_release",
        "runtime_admission_reservations",
        ["bucket_key", "released_at"],
    )
    op.create_index(
        "uq_runtime_admission_active_slot",
        "runtime_admission_reservations",
        ["bucket_key", "slot"],
        unique=True,
        sqlite_where=sa.text("released_at IS NULL"),
        postgresql_where=sa.text("released_at IS NULL"),
    )

    op.create_table(
        "runtime_event_dedupes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["runtime_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["runtime_task_events.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "dedupe_key",
            name="uq_runtime_event_dedupe_plan_key",
        ),
    )
    op.create_index(
        "ix_runtime_event_dedupes_plan_id",
        "runtime_event_dedupes",
        ["plan_id"],
    )
    op.create_index(
        "ix_runtime_event_dedupes_event",
        "runtime_event_dedupes",
        ["event_id"],
    )

    bind = op.get_bind()
    now = time.time()
    active_plans = list(
        bind.execute(
            sa.text(
                """
                SELECT id
                FROM runtime_plans
                WHERE kind = :kind
                  AND status IN ('queued', 'running')
                ORDER BY created_at, id
                """
            ),
            {"kind": AGENT_PLAN_KIND},
        ).mappings()
    )
    capacity = max(DEFAULT_AGENT_CAPACITY, len(active_plans))
    bind.execute(
        sa.text(
            """
            INSERT INTO runtime_admission_buckets(
                key, capacity, created_at, updated_at
            ) VALUES(:key, :capacity, :created_at, :updated_at)
            """
        ),
        {
            "key": AGENT_PLAN_KIND,
            "capacity": capacity,
            "created_at": now,
            "updated_at": now,
        },
    )
    for slot, plan in enumerate(active_plans):
        bind.execute(
            sa.text(
                """
                INSERT INTO runtime_admission_reservations(
                    plan_id, bucket_key, slot, acquired_at, released_at
                ) VALUES(:plan_id, :bucket_key, :slot, :acquired_at, NULL)
                """
            ),
            {
                "plan_id": plan["id"],
                "bucket_key": AGENT_PLAN_KIND,
                "slot": slot,
                "acquired_at": now,
            },
        )

    seen: set[tuple[str, str]] = set()
    events = bind.execute(
        sa.text(
            """
            SELECT id, plan_id, event_type, payload_json, created_at
            FROM runtime_task_events
            WHERE event_type LIKE 'agent.%'
            ORDER BY plan_id, seq
            """
        )
    ).mappings()
    for event in events:
        try:
            payload = json.loads(event["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        key = _dedupe_key(str(event["event_type"]), payload)
        key = key[:240] if key else None
        identity = (str(event["plan_id"]), str(key or ""))
        if not key or identity in seen:
            continue
        seen.add(identity)
        bind.execute(
            sa.text(
                """
                INSERT INTO runtime_event_dedupes(
                    id, plan_id, dedupe_key, event_id, created_at
                ) VALUES(:id, :plan_id, :dedupe_key, :event_id, :created_at)
                """
            ),
            {
                "id": uuid.uuid4().hex,
                "plan_id": event["plan_id"],
                "dedupe_key": key,
                "event_id": event["id"],
                "created_at": float(event["created_at"] or now),
            },
        )


def downgrade() -> None:
    op.drop_table("runtime_event_dedupes")
    op.drop_table("runtime_admission_reservations")
    op.drop_table("runtime_admission_buckets")
