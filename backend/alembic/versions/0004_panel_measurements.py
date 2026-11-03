"""panel measurements

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate emits sqlmodel column types)


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('panel_measurements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('line', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('lot', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('panel_serial', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('subgroup', sa.Integer(), nullable=False),
    sa.Column('metric', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_panel_measurements_line_metric', 'panel_measurements', ['line', 'metric', 'subgroup'], unique=False)
    op.create_index(op.f('ix_panel_measurements_panel_serial'), 'panel_measurements', ['panel_serial'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_panel_measurements_panel_serial'), table_name='panel_measurements')
    op.drop_index('ix_panel_measurements_line_metric', table_name='panel_measurements')
    op.drop_table('panel_measurements')
