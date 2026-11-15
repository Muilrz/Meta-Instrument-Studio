from dataclasses import replace

import pytest

from mis.adapters.a4_resume import PauseBinding, reconcile_a4_status, resume_request
from mis.adapters.deerflow import RunBinding, ThreadBinding
from mis.schemas.base import now
from mis.schemas.provenance import RunRef
from mis.schemas.questions import UserQuestion


@pytest.fixture
def answer_records(records):
    project, _, _, evidence, *_ = records
    run = RunBinding(ThreadBinding(project.id, "task", "mt", "dt"), "mis-run", "df-run")
    question = UserQuestion(
        project_id=project.id,
        run_id=run.run_id,
        question="Choose fixture",
        options=("fixture-a", "fixture-b"),
        context="P2 fixture",
    )
    evidence = evidence.model_copy(
        update={
            "source_type": "user_decision",
            "locator": question.id,
            "page_or_anchor": "answer",
            "excerpt": "fixture-a",
            "retrieved_by": RunRef(run_id=run.run_id, actor="user"),
        }
    )
    question = UserQuestion.model_validate(
        {
            **question.model_dump(),
            "status": "answered",
            "answer": "fixture-a",
            "answer_evidence_id": evidence.id,
            "answered_at": now(),
        }
    )
    pause = PauseBinding(run, question.id, "cp-1", "interrupt-1", "a4.before_agent")
    kwargs = dict(
        answer="fixture-a",
        resume_key="resume-1",
        resume_run_id="mis-resume-run",
        current_checkpoint_id="cp-1",
        observed_interrupt_id="interrupt-1",
        current_pending_nodes=("a4.before_agent",),
    )
    return pause, question, evidence, kwargs


def test_resume_command_binds_native_interrupt_checkpoint_and_durable_evidence(answer_records):
    pause, question, evidence, kwargs = answer_records
    first = resume_request(pause, question, evidence, **kwargs)
    assert first == resume_request(pause, question, evidence, **kwargs)
    assert first["checkpoint_id"] == "cp-1"
    answer = first["command"]["resume"]
    assert answer["question_id"] == question.id
    assert answer["answer_evidence_id"] == evidence.id
    assert answer["resume_key"] == "resume-1"
    assert answer["observed_interrupt_id"] == "interrupt-1"
    assert first["metadata"]["mis_run_id"] == "mis-resume-run"
    assert first["metadata"]["mis_parent_run_id"] == pause.run.run_id


def test_restart_can_omit_unavailable_audit_id_but_still_requires_current_single_pause(
    answer_records,
):
    pause, question, evidence, kwargs = answer_records
    pause = replace(pause, interrupt_id=None)
    kwargs = {**kwargs, "observed_interrupt_id": None}
    body = resume_request(pause, question, evidence, **kwargs)
    assert "observed_interrupt_id" not in body["command"]["resume"]
    for changed in ({"current_checkpoint_id": "old"}, {"current_pending_nodes": ()}):
        with pytest.raises(ValueError):
            resume_request(pause, question, evidence, **{**kwargs, **changed})


@pytest.mark.parametrize(
    "changed",
    [
        {"answer": "not-an-option"},
        {"answer": "fixture-b"},
        {"current_checkpoint_id": "old"},
        {"observed_interrupt_id": "another"},
        {"current_pending_nodes": ()},
        {"current_pending_nodes": ("a4.before_agent", "other")},
        {"resume_key": ""},
        {"resume_key": "bad\nkey"},
        {"resume_key": "x" * 256},
        {"resume_run_id": ""},
        {"resume_run_id": "mis-run"},
    ],
)
def test_rejects_invalid_answer_or_current_binding_before_io(answer_records, changed):
    pause, question, evidence, kwargs = answer_records
    with pytest.raises(ValueError, match="binding rejected"):
        resume_request(pause, question, evidence, **{**kwargs, **changed})


@pytest.mark.parametrize(
    "changed",
    [
        {"source_type": "document"},
        {"excerpt": "other answer"},
        {"locator": "other-question"},
        {"page_or_anchor": "other-anchor"},
        {"retrieved_by": RunRef(run_id="other-run", actor="user")},
        {"retrieved_by": RunRef(run_id="mis-run", actor="research")},
    ],
)
def test_rejects_evidence_provenance_mismatch(answer_records, changed):
    pause, question, evidence, kwargs = answer_records
    with pytest.raises(ValueError, match="binding rejected"):
        resume_request(pause, question, evidence.model_copy(update=changed), **kwargs)


def test_rejects_question_and_pause_scope_mismatch(answer_records):
    pause, question, evidence, kwargs = answer_records
    for changed in (
        {"status": "open"},
        {"run_id": "other-run"},
        {"answer_evidence_id": "other-evidence"},
    ):
        with pytest.raises(ValueError, match="binding rejected"):
            resume_request(pause, question.model_copy(update=changed), evidence, **kwargs)
    with pytest.raises(ValueError, match="binding rejected"):
        resume_request(replace(pause, question_id="other-question"), question, evidence, **kwargs)


@pytest.mark.parametrize("run_status", ["success", "interrupted", "error"])
def test_durable_question_interrupt_outweighs_command_status(run_status):
    assert (
        reconcile_a4_status(
            run_status,
            {"checkpoint_id": "cp", "next": ["a4.before_agent"]},
            pending_interrupt_id="i",
        )
        == "waiting_user"
    )


@pytest.mark.parametrize("state", [None, {}, {"checkpoint_id": "cp"}])
def test_command_success_without_checkpoint_proof_is_unknown(state):
    assert reconcile_a4_status("success", state, pending_interrupt_id=None) == "unknown"


def test_checkpoint_end_reconciles_success_but_mismatched_interrupt_does_not():
    state = {"checkpoint_id": "cp", "next": []}
    assert reconcile_a4_status("success", state, pending_interrupt_id=None) == "completed"
    assert reconcile_a4_status("success", state, pending_interrupt_id="i") == "unknown"
    assert reconcile_a4_status("error", state, pending_interrupt_id=None) == "failed"


def test_durable_question_binding_can_identify_pause_when_native_audit_id_is_unavailable():
    assert (
        reconcile_a4_status(
            "success",
            {"checkpoint_id": "cp", "next": ["a4.before_agent"]},
            pending_question_id="stored-question",
        )
        == "waiting_user"
    )
    assert (
        reconcile_a4_status(
            "success",
            {"checkpoint_id": "cp", "next": []},
            pending_question_id="stored-question",
        )
        == "unknown"
    )
