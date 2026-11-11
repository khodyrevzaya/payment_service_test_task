"""initial

Revision ID: 0001
Revises:
Create Date: 2026-11-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create enum types safely (PostgreSQL doesn't support CREATE TYPE IF NOT EXISTS)
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE currency_enum AS ENUM ('RUB', 'USD', 'EUR'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE payment_status_enum AS ENUM ('pending', 'succeeded', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE notification_status_enum AS ENUM ('pending', 'delivered', 'exhausted'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE outbox_status_enum AS ENUM ('pending', 'published'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$"
    )

    # Use existing enum types (don't create again)
    currency_enum = postgresql.ENUM("RUB", "USD", "EUR", name="currency_enum", create_type=False)
    payment_status_enum = postgresql.ENUM("pending", "succeeded", "failed", name="payment_status_enum", create_type=False)
    notification_status_enum = postgresql.ENUM(
        "pending", "delivered", "exhausted", name="notification_status_enum", create_type=False
    )
    outbox_status_enum = postgresql.ENUM("pending", "published", name="outbox_status_enum", create_type=False)

    # Create payments table
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", currency_enum, nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("status", payment_status_enum, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("webhook_url", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_status", notification_status_enum, nullable=True),
        sa.Column("notification_attempts", sa.Integer(), nullable=False),
        sa.Column("notification_last_error", sa.Text(), nullable=True),
        sa.Column("notification_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )

    # Create outbox_events table
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", outbox_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("payments")

    # Drop enum types
    sa.Enum(name="outbox_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="currency_enum").drop(op.get_bind(), checkfirst=True)