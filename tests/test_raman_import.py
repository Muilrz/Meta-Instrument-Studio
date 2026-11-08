from mis.importers.raman_baseline import import_raman_baseline
from mis.project_service.repository import ProjectService
from mis.schemas.project import InstrumentProject


def test_import_baseline_v1_and_project_kind(db_session):
    service = ProjectService(db_session)
    result = import_raman_baseline(service)
    assert result.project.kind == "benchmark"
    assert result.baseline.version == 1
    assert len(result.baseline.items) == 11
    assert result.baseline.budget.value == 60000
    assert result.fx_evidence.fx_rate.rate == 7.1
    assert result.project.current_baseline_version == 1
    normal = import_raman_baseline(service, kind="normal")
    assert service.get(InstrumentProject, normal.project.id).kind == "normal"
