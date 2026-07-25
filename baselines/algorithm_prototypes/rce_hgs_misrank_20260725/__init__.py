"""Zero-search proxy-misranking audit for the protected China81 HGS."""

from .audit_core import (
    ACTION_QUOTA,
    AuditTask,
    CandidateDescriptor,
    generate_candidates,
    run_audit_task,
)

__all__ = [
    "ACTION_QUOTA",
    "AuditTask",
    "CandidateDescriptor",
    "generate_candidates",
    "run_audit_task",
]

