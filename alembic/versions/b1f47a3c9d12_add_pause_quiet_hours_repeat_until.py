"""Add quiet hours, repeat_until, parent_reminder_id

Revision ID: b1f47a3c9d12
Revises: aee009efa436
Create Date: 2026-04-28 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1f47a3c9d12'
down_revision: Union[str, None] = 'aee009efa436'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reminders', sa.Column('repeat_until', sa.DateTime(), nullable=True))
    op.add_column('reminders', sa.Column('parent_reminder_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_reminders_parent_reminder_id',
        'reminders', 'reminders',
        ['parent_reminder_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_reminders_parent_reminder_id', 'reminders', ['parent_reminder_id'])

    op.add_column('users', sa.Column('quiet_start_hour', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('quiet_end_hour', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'quiet_end_hour')
    op.drop_column('users', 'quiet_start_hour')

    op.drop_index('ix_reminders_parent_reminder_id', table_name='reminders')
    op.drop_constraint('fk_reminders_parent_reminder_id', 'reminders', type_='foreignkey')
    op.drop_column('reminders', 'parent_reminder_id')
    op.drop_column('reminders', 'repeat_until')
