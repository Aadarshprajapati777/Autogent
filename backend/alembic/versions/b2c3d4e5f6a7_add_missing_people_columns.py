"""add missing memory_people columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-01

Adds 11 columns to memory_people that were in the model but missing
from the initial migration: email, avatar_url, slack_id, slack_handle,
github_id, github_login, jira_account_id, jira_display_name, linear_id,
onboarding_step, onboarding_completed.
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_people", sa.Column("email", sa.String(300), nullable=True))
    op.add_column("memory_people", sa.Column("avatar_url", sa.String(500), nullable=True))
    op.add_column("memory_people", sa.Column("slack_id", sa.String(50), nullable=True))
    op.add_column("memory_people", sa.Column("slack_handle", sa.String(100), nullable=True))
    op.add_column("memory_people", sa.Column("github_id", sa.String(50), nullable=True))
    op.add_column("memory_people", sa.Column("github_login", sa.String(100), nullable=True))
    op.add_column("memory_people", sa.Column("jira_account_id", sa.String(100), nullable=True))
    op.add_column("memory_people", sa.Column("jira_display_name", sa.String(200), nullable=True))
    op.add_column("memory_people", sa.Column("linear_id", sa.String(50), nullable=True))
    op.add_column("memory_people", sa.Column("onboarding_step", sa.String(40), nullable=True))
    op.add_column("memory_people", sa.Column("onboarding_completed", sa.Boolean, nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    for col in (
        "onboarding_completed",
        "onboarding_step",
        "linear_id",
        "jira_display_name",
        "jira_account_id",
        "github_login",
        "github_id",
        "slack_handle",
        "slack_id",
        "avatar_url",
        "email",
    ):
        op.drop_column("memory_people", col)
