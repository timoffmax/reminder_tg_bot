"""Add default_snooze_minutes and last_confirmation_request_at to reminders

Revision ID: d4e7b20c5a91
Revises: b1f47a3c9d12
Create Date: 2026-06-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e7b20c5a91'
down_revision: Union[str, None] = 'b1f47a3c9d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reminders', sa.Column('default_snooze_minutes', sa.Integer(), nullable=True))
    op.add_column('reminders', sa.Column('last_confirmation_request_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('reminders', 'last_confirmation_request_at')
    op.drop_column('reminders', 'default_snooze_minutes')
