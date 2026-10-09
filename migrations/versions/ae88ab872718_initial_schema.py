"""initial schema

Revision ID: ae88ab872718
Revises: 
Create Date: 2026-10-09 09:45:11.589335

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae88ab872718'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'data_changes' not in existing_tables:
        op.create_table('data_changes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=64), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('detected_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('data_changes', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_data_changes_entity_id'), ['entity_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_data_changes_entity_type'), ['entity_type'], unique=False)
            batch_op.create_index(batch_op.f('ix_data_changes_run_id'), ['run_id'], unique=False)

    if 'exchanges' not in existing_tables:
        op.create_table('exchanges',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('country', sa.String(length=64), nullable=True),
        sa.Column('currency', sa.String(length=16), nullable=True),
        sa.Column('timezone', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('exchanges', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_exchanges_code'), ['code'], unique=True)

    if 'sync_jobs' not in existing_tables:
        op.create_table('sync_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(length=64), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('ticker', sa.String(length=32), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('locked_by', sa.String(length=64), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('sync_jobs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_sync_jobs_job_type'), ['job_type'], unique=False)
            batch_op.create_index(batch_op.f('ix_sync_jobs_next_run_at'), ['next_run_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_sync_jobs_priority'), ['priority'], unique=False)
            batch_op.create_index(batch_op.f('ix_sync_jobs_status'), ['status'], unique=False)
            batch_op.create_index(batch_op.f('ix_sync_jobs_ticker'), ['ticker'], unique=False)

    if 'sync_runs' not in existing_tables:
        op.create_table('sync_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('items_processed', sa.Integer(), nullable=False),
        sa.Column('items_failed', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('sync_runs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_sync_runs_run_type'), ['run_type'], unique=False)
            batch_op.create_index(batch_op.f('ix_sync_runs_status'), ['status'], unique=False)

    if 'sync_state' not in existing_tables:
        op.create_table('sync_state',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value_json', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('sync_state', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_sync_state_key'), ['key'], unique=True)

    if 'worker_status' not in existing_tables:
        op.create_table('worker_status',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('worker_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('current_job_id', sa.Integer(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=False),
        sa.Column('meta_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('worker_status', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_worker_status_worker_id'), ['worker_id'], unique=True)

    if 'companies' not in existing_tables:
        op.create_table('companies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticker', sa.String(length=32), nullable=False),
        sa.Column('exchange_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('sector', sa.String(length=128), nullable=True),
        sa.Column('industry', sa.String(length=128), nullable=True),
        sa.Column('country', sa.String(length=64), nullable=True),
        sa.Column('currency', sa.String(length=16), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['exchange_id'], ['exchanges.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exchange_id', 'ticker', name='uq_exchange_ticker')
        )
        with op.batch_alter_table('companies', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_companies_exchange_id'), ['exchange_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_companies_industry'), ['industry'], unique=False)
            batch_op.create_index(batch_op.f('ix_companies_sector'), ['sector'], unique=False)
            batch_op.create_index(batch_op.f('ix_companies_ticker'), ['ticker'], unique=False)

    if 'company_relationships' not in existing_tables:
        op.create_table('company_relationships',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('related_company_id', sa.Integer(), nullable=False),
        sa.Column('relationship_type', sa.String(length=32), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['related_company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'related_company_id', 'relationship_type', name='uq_company_relationship')
        )
        with op.batch_alter_table('company_relationships', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_company_relationships_company_id'), ['company_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_company_relationships_related_company_id'), ['related_company_id'], unique=False)

    if 'dividend_events' not in existing_tables:
        op.create_table('dividend_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('declaration_date', sa.Date(), nullable=True),
        sa.Column('ex_date', sa.Date(), nullable=True),
        sa.Column('record_date', sa.Date(), nullable=True),
        sa.Column('pay_date', sa.Date(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(length=16), nullable=True),
        sa.Column('frequency', sa.String(length=32), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'ex_date', 'pay_date', 'amount', name='uq_company_dividend_event')
        )
        with op.batch_alter_table('dividend_events', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_dividend_events_company_id'), ['company_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_dividend_events_ex_date'), ['ex_date'], unique=False)
            batch_op.create_index(batch_op.f('ix_dividend_events_pay_date'), ['pay_date'], unique=False)

    if 'dividend_metrics' not in existing_tables:
        op.create_table('dividend_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('current_yield', sa.Float(), nullable=True),
        sa.Column('trailing_yield', sa.Float(), nullable=True),
        sa.Column('forward_yield', sa.Float(), nullable=True),
        sa.Column('annual_dividend', sa.Float(), nullable=True),
        sa.Column('payout_ratio', sa.Float(), nullable=True),
        sa.Column('fcf_coverage', sa.Float(), nullable=True),
        sa.Column('growth_1y', sa.Float(), nullable=True),
        sa.Column('growth_3y', sa.Float(), nullable=True),
        sa.Column('growth_5y', sa.Float(), nullable=True),
        sa.Column('growth_10y', sa.Float(), nullable=True),
        sa.Column('years_paying', sa.Integer(), nullable=True),
        sa.Column('years_growing', sa.Integer(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('calculated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('dividend_metrics', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_dividend_metrics_company_id'), ['company_id'], unique=True)

    if 'financial_metrics' not in existing_tables:
        op.create_table('financial_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('market_cap', sa.Float(), nullable=True),
        sa.Column('pe_ratio', sa.Float(), nullable=True),
        sa.Column('forward_pe', sa.Float(), nullable=True),
        sa.Column('pb_ratio', sa.Float(), nullable=True),
        sa.Column('debt_to_equity', sa.Float(), nullable=True),
        sa.Column('roe', sa.Float(), nullable=True),
        sa.Column('roa', sa.Float(), nullable=True),
        sa.Column('earnings_growth', sa.Float(), nullable=True),
        sa.Column('revenue_growth', sa.Float(), nullable=True),
        sa.Column('free_cash_flow', sa.Float(), nullable=True),
        sa.Column('operating_cash_flow', sa.Float(), nullable=True),
        sa.Column('calculated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('financial_metrics', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_financial_metrics_company_id'), ['company_id'], unique=True)

    if 'price_history' not in existing_tables:
        op.create_table('price_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('adj_close', sa.Float(), nullable=True),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'date', name='uq_company_price_date')
        )
        with op.batch_alter_table('price_history', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_price_history_company_id'), ['company_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_price_history_date'), ['date'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'price_history' in existing_tables:
        with op.batch_alter_table('price_history', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_price_history_date'))
            batch_op.drop_index(batch_op.f('ix_price_history_company_id'))
        op.drop_table('price_history')

    if 'financial_metrics' in existing_tables:
        with op.batch_alter_table('financial_metrics', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_financial_metrics_company_id'))
        op.drop_table('financial_metrics')

    if 'dividend_metrics' in existing_tables:
        with op.batch_alter_table('dividend_metrics', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_dividend_metrics_company_id'))
        op.drop_table('dividend_metrics')

    if 'dividend_events' in existing_tables:
        with op.batch_alter_table('dividend_events', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_dividend_events_pay_date'))
            batch_op.drop_index(batch_op.f('ix_dividend_events_ex_date'))
            batch_op.drop_index(batch_op.f('ix_dividend_events_company_id'))
        op.drop_table('dividend_events')

    if 'company_relationships' in existing_tables:
        with op.batch_alter_table('company_relationships', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_company_relationships_related_company_id'))
            batch_op.drop_index(batch_op.f('ix_company_relationships_company_id'))
        op.drop_table('company_relationships')

    if 'companies' in existing_tables:
        with op.batch_alter_table('companies', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_companies_ticker'))
            batch_op.drop_index(batch_op.f('ix_companies_sector'))
            batch_op.drop_index(batch_op.f('ix_companies_industry'))
            batch_op.drop_index(batch_op.f('ix_companies_exchange_id'))
        op.drop_table('companies')

    if 'worker_status' in existing_tables:
        with op.batch_alter_table('worker_status', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_worker_status_worker_id'))
        op.drop_table('worker_status')

    if 'sync_state' in existing_tables:
        with op.batch_alter_table('sync_state', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_sync_state_key'))
        op.drop_table('sync_state')

    if 'sync_runs' in existing_tables:
        with op.batch_alter_table('sync_runs', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_sync_runs_status'))
            batch_op.drop_index(batch_op.f('ix_sync_runs_run_type'))
        op.drop_table('sync_runs')

    if 'sync_jobs' in existing_tables:
        with op.batch_alter_table('sync_jobs', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_sync_jobs_ticker'))
            batch_op.drop_index(batch_op.f('ix_sync_jobs_status'))
            batch_op.drop_index(batch_op.f('ix_sync_jobs_priority'))
            batch_op.drop_index(batch_op.f('ix_sync_jobs_next_run_at'))
            batch_op.drop_index(batch_op.f('ix_sync_jobs_job_type'))
        op.drop_table('sync_jobs')

    if 'exchanges' in existing_tables:
        with op.batch_alter_table('exchanges', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_exchanges_code'))
        op.drop_table('exchanges')

    if 'data_changes' in existing_tables:
        with op.batch_alter_table('data_changes', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_data_changes_run_id'))
            batch_op.drop_index(batch_op.f('ix_data_changes_entity_type'))
            batch_op.drop_index(batch_op.f('ix_data_changes_entity_id'))
        op.drop_table('data_changes')
    # ### end Alembic commands ###
