"""Widen reminders.repeat_interval to hold multi-day patterns with many weekdays

Revision ID: f2c9a4e17b63
Revises: d4e7b20c5a91
Create Date: 2026-07-23 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c9a4e17b63'
down_revision: Union[str, None] = 'd4e7b20c5a91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'reminders',
        'repeat_interval',
        type_=sa.String(length=100),
        existing_type=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'reminders',
        'repeat_interval',
        type_=sa.String(length=50),
        existing_type=sa.String(length=100),
        existing_nullable=True,
    )
