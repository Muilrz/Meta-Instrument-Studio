"""Protect question identity, terminal states and answer evidence."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE FUNCTION mis.guard_question() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'question cannot be deleted';
    END IF;
    IF OLD.status IS DISTINCT FROM 'open' OR
       OLD.body->>'status' IS DISTINCT FROM 'open' OR
       NEW.status IS NULL OR NEW.status NOT IN ('answered', 'cancelled') OR
       NEW.status IS DISTINCT FROM NEW.body->>'status' OR
       (to_jsonb(NEW) - 'body' - 'status') IS DISTINCT FROM
       (to_jsonb(OLD) - 'body' - 'status') OR
       (NEW.body - 'status' - 'answer' - 'answered_at' - 'answer_evidence_id') IS DISTINCT FROM
       (OLD.body - 'status' - 'answer' - 'answered_at' - 'answer_evidence_id') THEN
        RAISE EXCEPTION 'question allows only open to answered or cancelled; identity is immutable';
    END IF;
    IF NEW.status = 'answered' THEN
        IF jsonb_typeof(NEW.body->'answer') IS DISTINCT FROM 'string' OR
           btrim(NEW.body->>'answer') = '' OR
           jsonb_typeof(NEW.body->'answered_at') IS DISTINCT FROM 'string' OR
           (NEW.body->>'answered_at')::timestamptz IS NULL OR
           NOT EXISTS (
               SELECT 1 FROM mis.evidence e
               WHERE e.id = NEW.body->>'answer_evidence_id'
                 AND e.project_id = NEW.project_id
                 AND e.body->>'source_type' = 'user_decision'
           ) THEN
            RAISE EXCEPTION 'answer requires text, time and project user_decision evidence';
        END IF;
    ELSE
        IF NEW.body->>'answer' IS NOT NULL OR NEW.body->>'answered_at' IS NOT NULL OR
           NEW.body->>'answer_evidence_id' IS NOT NULL THEN
            RAISE EXCEPTION 'cancelled question cannot contain answer fields';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_question BEFORE UPDATE OR DELETE ON mis.questions
    FOR EACH ROW EXECUTE FUNCTION mis.guard_question();
CREATE TRIGGER guard_question_truncate BEFORE TRUNCATE ON mis.questions
    FOR EACH STATEMENT EXECUTE FUNCTION mis.guard_question();
""")


def downgrade():
    op.execute("DROP TRIGGER guard_question_truncate ON mis.questions")
    op.execute("DROP TRIGGER guard_question ON mis.questions")
    op.execute("DROP FUNCTION mis.guard_question()")
