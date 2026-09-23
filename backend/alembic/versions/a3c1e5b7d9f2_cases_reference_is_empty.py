"""cases.reference_is_empty

Revision ID: a3c1e5b7d9f2
Revises: e8ac296a80a0
Create Date: 2026-09-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c1e5b7d9f2'
down_revision: Union[str, Sequence[str], None] = 'e8ac296a80a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('reference_is_empty', sa.Boolean(), server_default='0', nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.drop_column('reference_is_empty')
