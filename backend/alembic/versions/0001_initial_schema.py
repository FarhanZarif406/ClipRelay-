"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-05 22:03:52.156261
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('activity_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('level', sa.String(length=16), nullable=False),
    sa.Column('service', sa.String(length=40), nullable=False),
    sa.Column('event', sa.String(length=60), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('request_id', sa.String(length=40), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=True),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('activity_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_logs_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_logs_level'), ['level'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_logs_service'), ['service'], unique=False)

    op.create_table('prompt_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('niche', sa.String(length=80), nullable=False),
    sa.Column('title_prompt', sa.Text(), nullable=False),
    sa.Column('caption_prompt', sa.Text(), nullable=False),
    sa.Column('hashtags_prompt', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('tiktok_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('open_id', sa.String(length=128), nullable=False),
    sa.Column('username', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('avatar_url', sa.Text(), nullable=True),
    sa.Column('color', sa.String(length=16), nullable=False),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('refresh_token_enc', sa.Text(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refresh_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scopes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('daily_cap', sa.Integer(), nullable=False),
    sa.Column('default_privacy', sa.String(length=40), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('open_id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('workspace_name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('instagram_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ig_user_id', sa.String(length=64), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('profile_picture_url', sa.Text(), nullable=True),
    sa.Column('color', sa.String(length=16), nullable=False),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('refresh_interval_minutes', sa.Integer(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_status', sa.String(length=32), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('approval_mode', sa.String(length=16), nullable=False),
    sa.Column('prompt_template_id', sa.Integer(), nullable=True),
    sa.Column('videos_found', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['prompt_template_id'], ['prompt_templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ig_user_id')
    )
    with op.batch_alter_table('instagram_sources', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_instagram_sources_is_active'), ['is_active'], unique=False)
        batch_op.create_index(batch_op.f('ix_instagram_sources_next_run_at'), ['next_run_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_instagram_sources_username'), ['username'], unique=True)

    op.create_table('prompt_template_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['prompt_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('prompt_template_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prompt_template_versions_template_id'), ['template_id'], unique=False)

    op.create_table('source_tiktok_links',
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('tiktok_account_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['instagram_sources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tiktok_account_id'], ['tiktok_accounts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('source_id', 'tiktok_account_id')
    )
    op.create_table('videos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('ig_media_id', sa.String(length=64), nullable=False),
    sa.Column('permalink', sa.Text(), nullable=True),
    sa.Column('media_url', sa.Text(), nullable=True),
    sa.Column('thumbnail_url', sa.Text(), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('original_title', sa.Text(), nullable=False),
    sa.Column('original_caption', sa.Text(), nullable=False),
    sa.Column('original_tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('duration_sec', sa.Float(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('storage_key', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('transcript', sa.Text(), nullable=True),
    sa.Column('detected_language', sa.String(length=32), nullable=True),
    sa.Column('language_confidence', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['instagram_sources.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'ig_media_id', name='uq_video_source_media')
    )
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_videos_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_videos_source_id'), ['source_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_videos_status'), ['status'], unique=False)

    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('video_id', sa.Integer(), nullable=False),
    sa.Column('tiktok_account_id', sa.Integer(), nullable=True),
    sa.Column('prompt_template_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('approval_required', sa.Boolean(), nullable=False),
    sa.Column('rewritten_title', sa.Text(), nullable=True),
    sa.Column('rewritten_caption', sa.Text(), nullable=True),
    sa.Column('rewritten_tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('privacy_level', sa.String(length=40), nullable=True),
    sa.Column('tiktok_publish_id', sa.String(length=128), nullable=True),
    sa.Column('tiktok_post_id', sa.String(length=128), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('monitor_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('check_count', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('violation_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['prompt_template_id'], ['prompt_templates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tiktok_account_id'], ['tiktok_accounts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('video_id', 'tiktok_account_id', name='uq_job_video_account')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_posted_at'), ['posted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_status'), ['status'], unique=False)
        batch_op.create_index('ix_jobs_status_next_check', ['status', 'next_check_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_tiktok_account_id'), ['tiktok_account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_video_id'), ['video_id'], unique=False)

    op.create_table('job_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_events_job_id'), ['job_id'], unique=False)

    op.create_table('violations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('tiktok_account_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('raw', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('removal_status', sa.String(length=32), nullable=False),
    sa.Column('acknowledged', sa.Boolean(), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tiktok_account_id'], ['tiktok_accounts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('violations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_violations_acknowledged'), ['acknowledged'], unique=False)
        batch_op.create_index(batch_op.f('ix_violations_detected_at'), ['detected_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_violations_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_violations_tiktok_account_id'), ['tiktok_account_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('violations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_violations_tiktok_account_id'))
        batch_op.drop_index(batch_op.f('ix_violations_job_id'))
        batch_op.drop_index(batch_op.f('ix_violations_detected_at'))
        batch_op.drop_index(batch_op.f('ix_violations_acknowledged'))

    op.drop_table('violations')
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_events_job_id'))

    op.drop_table('job_events')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_video_id'))
        batch_op.drop_index(batch_op.f('ix_jobs_tiktok_account_id'))
        batch_op.drop_index('ix_jobs_status_next_check')
        batch_op.drop_index(batch_op.f('ix_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_jobs_posted_at'))

    op.drop_table('jobs')
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_videos_status'))
        batch_op.drop_index(batch_op.f('ix_videos_source_id'))
        batch_op.drop_index(batch_op.f('ix_videos_created_at'))

    op.drop_table('videos')
    op.drop_table('source_tiktok_links')
    with op.batch_alter_table('prompt_template_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prompt_template_versions_template_id'))

    op.drop_table('prompt_template_versions')
    with op.batch_alter_table('instagram_sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_instagram_sources_username'))
        batch_op.drop_index(batch_op.f('ix_instagram_sources_next_run_at'))
        batch_op.drop_index(batch_op.f('ix_instagram_sources_is_active'))

    op.drop_table('instagram_sources')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('tiktok_accounts')
    op.drop_table('settings')
    op.drop_table('prompt_templates')
    with op.batch_alter_table('activity_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_activity_logs_service'))
        batch_op.drop_index(batch_op.f('ix_activity_logs_level'))
        batch_op.drop_index(batch_op.f('ix_activity_logs_job_id'))
        batch_op.drop_index(batch_op.f('ix_activity_logs_created_at'))

    op.drop_table('activity_logs')
