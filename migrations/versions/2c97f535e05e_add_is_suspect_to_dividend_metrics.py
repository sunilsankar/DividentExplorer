"""add is_suspect to dividend_metrics

Revision ID: 2c97f535e05e
Revises: 4d11a91bc123
Create Date: 2026-10-10 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c97f535e05e'
down_revision: Union[str, Sequence[str], None] = '4d11a91bc123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("dividend_metrics")]
    with op.batch_alter_table("dividend_metrics") as batch_op:
        if "is_suspect" not in columns:
            batch_op.add_column(
                sa.Column("is_suspect", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
            batch_op.create_index("ix_dividend_metrics_is_suspect", ["is_suspect"])
        if "suspect_reason" not in columns:
            batch_op.add_column(
                sa.Column("suspect_reason", sa.String(255), nullable=True)
            )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("dividend_metrics")]
    with op.batch_alter_table("dividend_metrics") as batch_op:
        if "is_suspect" in columns:
            batch_op.drop_index("ix_dividend_metrics_is_suspect")
            batch_op.drop_column("is_suspect")
        if "suspect_reason" in columns:
            batch_op.drop_column("suspect_reason")
