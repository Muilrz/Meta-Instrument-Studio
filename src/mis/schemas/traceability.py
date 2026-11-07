from mis.ids import ArtifactId
from mis.schemas.artifacts import Claim
from mis.schemas.base import Model
from mis.schemas.evidence import Evidence


class ClaimTrace(Model):
    """Business provenance; independent of execution Trace infrastructure."""

    artifact_id: ArtifactId
    claim: Claim
    evidence: tuple[Evidence, ...]
