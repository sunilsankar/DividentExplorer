"""add parent_job_id to sync_jobs

Revision ID: 3289b71418a5
Revises: ae88ab872718
Create Date: 2026-10-09 13:51:13.057990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3289b71418a5'
down_revision: Union[str, Sequence[str], None] = 'ae88ab872718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("sync_jobs")]
    if "parent_job_id" not in columns:
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "parent_job_id",
                    sa.Integer(),
                    sa.ForeignKey("sync_jobs.id", name="fk_sync_jobs_parent_job_id", ondelete="SET NULL"),
                    nullable=True,
                )
            )
            batch_op.create_index("ix_sync_jobs_parent_job_id", ["parent_job_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns("sync_jobs")]
    if "parent_job_id" in columns:
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.drop_index("ix_sync_jobs_parent_job_id")
            batch_op.drop_column("parent_job_id")
