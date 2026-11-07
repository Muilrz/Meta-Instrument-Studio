"""P1 business records and immutable content guards (no runtime tables)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NAMES = (
    "projects",
    "baselines",
    "briefs",
    "evidence",
    "artifacts",
    "plans",
    "questions",
    "corrections",
    "test_results",
)


def upgrade():
    for name in NAMES:
        columns = [sa.Column("id", sa.String, primary_key=True)]
        if name != "projects":
            columns.append(
                sa.Column("project_id", sa.String, sa.ForeignKey("mis.projects.id"), nullable=False)
            )
        columns.extend(
            [
                sa.Column("version", sa.Integer),
                sa.Column("status", sa.String),
                sa.Column("run_id", sa.String),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("body", JSONB, nullable=False),
                sa.CheckConstraint("body->>'id' = id", name=f"{name}_body_id"),
            ]
        )
        if name != "projects":
            columns.append(
                sa.CheckConstraint("body->>'project_id' = project_id", name=f"{name}_body_project")
            )
        if name in ("baselines", "plans"):
            columns.extend(
                [
                    sa.UniqueConstraint("project_id", "version", name=f"{name}_version"),
                    sa.CheckConstraint(
                        "version > 0 AND (body->>'version')::int = version",
                        name=f"{name}_body_version",
                    ),
                ]
            )
        op.create_table(name, *columns, schema="mis")
        op.create_index(f"ix_mis_{name}_run_id", name, ["run_id"], schema="mis")
        if name != "projects":
            op.create_index(f"ix_mis_{name}_project_id", name, ["project_id"], schema="mis")
    op.execute("""
CREATE FUNCTION mis.guard_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_history jsonb; new_history jsonb;
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'business record cannot be deleted';
    END IF;
    IF TG_ARGV[0] = 'immutable' THEN
        RAISE EXCEPTION 'business content is immutable';
    END IF;
    IF (to_jsonb(NEW) - 'body' - 'status') IS DISTINCT FROM
       (to_jsonb(OLD) - 'body' - 'status') OR
       (NEW.body - 'status' - 'status_history') IS DISTINCT FROM
       (OLD.body - 'status' - 'status_history') THEN
        RAISE EXCEPTION 'business content is immutable';
    END IF;
    old_history := COALESCE(OLD.body->'status_history', '[]'::jsonb);
    new_history := COALESCE(NEW.body->'status_history', '[]'::jsonb);
    IF OLD.status = 'stale' OR NEW.status = OLD.status OR
       NEW.status IS DISTINCT FROM NEW.body->>'status' OR
       jsonb_array_length(new_history) <> jsonb_array_length(old_history) + 1 OR
       (new_history - (jsonb_array_length(new_history) - 1)) <> old_history OR
       new_history->-1->>'status' IS DISTINCT FROM NEW.status OR
       COALESCE(new_history->-1->>'reason', '') = '' OR
       COALESCE(new_history->-1->>'trigger_id', '') = '' THEN
        RAISE EXCEPTION 'status requires appended history and cannot revive stale content';
    END IF;
    RETURN NEW;
END $$;
""")
    for name in (
        "baselines",
        "evidence",
        "corrections",
        "test_results",
        "briefs",
        "artifacts",
        "plans",
    ):
        mode = "status" if name in ("briefs", "artifacts", "plans") else "immutable"
        op.execute(
            f"CREATE TRIGGER guard_record BEFORE UPDATE OR DELETE ON mis.{name} "
            f"FOR EACH ROW EXECUTE FUNCTION mis.guard_record('{mode}')"
        )
        op.execute(
            f"CREATE TRIGGER guard_truncate BEFORE TRUNCATE ON mis.{name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION mis.guard_record('immutable')"
        )


def downgrade():
    for name in reversed(NAMES):
        op.drop_table(name, schema="mis")
    op.execute("DROP FUNCTION mis.guard_record()")
