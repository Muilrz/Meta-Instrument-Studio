import httpx
import pytest

from mis.adapters.deerflow import DeerFlowClient, DeerFlowError, RunBinding, ThreadBinding

THREAD = ThreadBinding("p", "task", "mt", "dt")
META = {"mis_project_id": "p", "mis_task_id": "task", "mis_thread_id": "mt"}


def row(identifier="dr", run_id="mr"):
    return {
        "thread_id": "dt",
        "run_id": identifier,
        "metadata": {**META, "mis_run_id": run_id},
        "status": "success",
    }


def client_for(pages, requests):
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/runs/page"):
            return httpx.Response(200, json=pages.pop(0))
        return httpx.Response(200, json={"thread_id": "dt", "metadata": META})

    return DeerFlowClient("https://gateway.invalid", transport=httpx.MockTransport(handler))


def test_reconcile_across_keyset_pages_checks_full_mapping_and_never_posts():
    requests = []
    with client_for(
        [
            {
                "data": [row("other", "other")],
                "has_more": True,
                "next_before_created_at": "2026-11-15T00:00:00Z",
                "next_before_run_id": "other",
            },
            {"data": [row()], "has_more": False},
        ],
        requests,
    ) as client:
        result = client.find_run(THREAD, "mr")
    assert result.binding == RunBinding(THREAD, "mr", "dr")
    assert result.status == "completed"
    assert requests[-1].url.params["before_run_id"] == "other"


def test_missing_run_does_not_resend():
    requests = []
    with client_for([{"data": [], "has_more": False}], requests) as client:
        assert client.find_run(THREAD, "mr") is None
    assert len(requests) == 2


@pytest.mark.parametrize(
    "page,kind",
    [
        ({"data": [row(), row("second")], "has_more": False}, "ambiguous_run_mapping"),
        (
            {
                "data": [row()],
                "has_more": True,
                "next_before_created_at": "time",
                "next_before_run_id": "dr",
            },
            "reconciliation_incomplete",
        ),
        (
            {
                "data": [
                    {**row(), "metadata": {**META, "mis_project_id": "other", "mis_run_id": "mr"}}
                ],
                "has_more": False,
            },
            "run_mapping_conflict",
        ),
        ({"data": [{**row(), "thread_id": "other"}], "has_more": False}, "invalid_run_page"),
        ({"data": [], "has_more": True}, "invalid_run_cursor"),
    ],
)
def test_ambiguous_incomplete_or_cross_scope_query_is_not_a_binding(page, kind):
    with client_for([page], []) as client:
        with pytest.raises(DeerFlowError, match=kind):
            client.find_run(THREAD, "mr", max_pages=1)
