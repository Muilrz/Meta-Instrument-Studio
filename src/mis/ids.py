from typing import Annotated

from pydantic import StringConstraints
from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


ProjectId = Annotated[str, StringConstraints(pattern=r"^prj_[0-9A-HJKMNP-TV-Z]{26}$")]
BaselineId = Annotated[str, StringConstraints(pattern=r"^req_[0-9A-HJKMNP-TV-Z]{26}$")]
BriefId = Annotated[str, StringConstraints(pattern=r"^brf_[0-9A-HJKMNP-TV-Z]{26}$")]
ArtifactId = Annotated[str, StringConstraints(pattern=r"^art_[0-9A-HJKMNP-TV-Z]{26}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^evd_[0-9A-HJKMNP-TV-Z]{26}$")]
PlanId = Annotated[str, StringConstraints(pattern=r"^pln_[0-9A-HJKMNP-TV-Z]{26}$")]
