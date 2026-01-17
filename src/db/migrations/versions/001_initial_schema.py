"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create capture_windows table
    op.create_table(
        'capture_windows',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('digest_generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('digest_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('alert_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
    )

    # Create indexes for capture_windows
    op.create_index('idx_capture_windows_start', 'capture_windows', ['window_start'])
    op.create_index('idx_capture_windows_end', 'capture_windows', ['window_end'])
    op.create_index('idx_capture_windows_status', 'capture_windows', ['status'])

    # Create alerts table
    op.create_table(
        'alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('alertname', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('severity', sa.String(50), nullable=True),
        sa.Column('namespace', sa.String(255), nullable=True),
        sa.Column('labels', JSONB, nullable=False),
        sa.Column('annotations', JSONB, nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('capture_window_id', UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['capture_window_id'], ['capture_windows.id'], ondelete='SET NULL'),
    )

    # Create indexes for alerts
    op.create_index('idx_alerts_fingerprint', 'alerts', ['fingerprint'])
    op.create_index('idx_alerts_alertname', 'alerts', ['alertname'])
    op.create_index('idx_alerts_severity', 'alerts', ['severity'])
    op.create_index('idx_alerts_window', 'alerts', ['capture_window_id'])
    op.create_index('idx_alerts_received', 'alerts', ['received_at'])
    op.create_index('idx_alerts_labels', 'alerts', ['labels'], postgresql_using='gin')

    # Create digests table
    op.create_table(
        'digests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('capture_window_id', UUID(as_uuid=True), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('llm_model', sa.String(100), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('raw_prompt', sa.Text(), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('formatted_output', sa.Text(), nullable=True),
        sa.Column('teams_message_id', sa.String(255), nullable=True),
        sa.Column('delivery_status', sa.String(20), nullable=False, server_default='pending'),
        sa.ForeignKeyConstraint(['capture_window_id'], ['capture_windows.id'], ondelete='CASCADE'),
    )

    # Create indexes for digests
    op.create_index('idx_digests_window', 'digests', ['capture_window_id'])


def downgrade() -> None:
    op.drop_table('digests')
    op.drop_table('alerts')
    op.drop_table('capture_windows')
