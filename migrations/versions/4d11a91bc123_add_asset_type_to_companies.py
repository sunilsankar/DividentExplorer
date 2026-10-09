"""add asset_type to companies

Revision ID: 4d11a91bc123
Revises: 3289b71418a5
Create Date: 2026-10-09 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d11a91bc123'
down_revision: Union[str, Sequence[str], None] = '3289b71418a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("companies")]
    if "asset_type" not in columns:
        with op.batch_alter_table("companies") as batch_op:
            batch_op.add_column(
                sa.Column("asset_type", sa.String(16), nullable=False, server_default="STOCK")
            )
            batch_op.create_index("ix_companies_asset_type", ["asset_type"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("companies")]
    if "asset_type" in columns:
        with op.batch_alter_table("companies") as batch_op:
            batch_op.drop_index("ix_companies_asset_type")
            batch_op.drop_column("asset_type")
