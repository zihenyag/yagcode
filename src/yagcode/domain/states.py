"""Closed domain enums for the lifecycle transition contract."""

from enum import StrEnum


class RunState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    WAITING_PLAN_APPROVAL = "WAITING_PLAN_APPROVAL"
    RUNNING = "RUNNING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    WAITING_PRIVACY = "WAITING_PRIVACY"
    COMPACTING = "COMPACTING"
    STOPPING = "STOPPING"
    PAUSED_BY_USER = "PAUSED_BY_USER"
    PAUSED_BUDGET = "PAUSED_BUDGET"
    PAUSED_FAILURE = "PAUSED_FAILURE"
    INTERRUPTED = "INTERRUPTED"
    FINISHED = "FINISHED"


class TaskState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ReviewState(StrEnum):
    NOT_READY = "NOT_READY"
    INCOMPLETE = "INCOMPLETE"
    READY = "READY"
    ACCEPTING = "ACCEPTING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class IntegrationState(StrEnum):
    PREPARING = "PREPARING"
    PREPARED = "PREPARED"
    APPLYING = "APPLYING"
    VERIFYING = "VERIFYING"
    ACCEPTED = "ACCEPTED"
    CONFLICT_BEFORE_WRITE = "CONFLICT_BEFORE_WRITE"
    COMPENSATING = "COMPENSATING"
    ACCEPT_FAILED_ROLLED_BACK = "ACCEPT_FAILED_ROLLED_BACK"
    ACCEPT_RECOVERY_REQUIRED = "ACCEPT_RECOVERY_REQUIRED"


class RecoveryClass(StrEnum):
    ALL_PREIMAGE = "ALL_PREIMAGE"
    OWNED_POSTIMAGE_COMPENSATABLE = "OWNED_POSTIMAGE_COMPENSATABLE"
    ALL_POSTIMAGE = "ALL_POSTIMAGE"
    MIXED_OR_UNKNOWN = "MIXED_OR_UNKNOWN"


class RunEvent(StrEnum):
    START_PLAN = "start_plan"
    START_WITHOUT_PLAN = "start_without_plan"
    PLAN_READY = "plan_ready"
    APPROVE_PLAN = "approve_plan"
    WAIT_PERMISSION = "wait_permission"
    WAIT_PRIVACY = "wait_privacy"
    DECISION_RESOLVED = "decision_resolved"
    START_COMPACTION = "start_compaction"
    COMPACTION_SUCCEEDED = "compaction_succeeded"
    COMPACTION_FAILED = "compaction_failed"
    REQUEST_STOP = "request_stop"
    STOP_CONFIRMED = "stop_confirmed"
    STOP_UNCONFIRMED = "stop_unconfirmed"
    PAUSE_BUDGET = "pause_budget"
    PAUSE_FAILURE = "pause_failure"
    RESUME = "resume"
    SWITCH_MODEL = "switch_model"
    FINISH_CANDIDATE = "finish_candidate"


class TaskEvent(StrEnum):
    ACTIVATE = "activate"
    CLOSE = "close"
    REOPEN = "reopen"
    ARCHIVE = "archive"
    RESTORE_ARCHIVE = "restore_archive"


class ReviewEvent(StrEnum):
    CANDIDATE_INCOMPLETE = "candidate_incomplete"
    CANDIDATE_READY = "candidate_ready"
    CONTINUE_WORK = "continue_work"
    BEGIN_ACCEPT = "begin_accept"
    ACCEPT_SUCCEEDED = "accept_succeeded"
    ACCEPT_CONFLICT = "accept_conflict"
    ACCEPT_RECOVERY_REQUIRED = "accept_recovery_required"
    ACCEPT_ROLLED_BACK = "accept_rolled_back"
    RESOLVE_CONFLICT_READY = "resolve_conflict_ready"
    RESOLVE_CONFLICT_INCOMPLETE = "resolve_conflict_incomplete"
    REJECT = "reject"
    RECOVERY_STILL_REQUIRED = "recovery_still_required"


class IntegrationEvent(StrEnum):
    PREPARE_SUCCEEDED = "prepare_succeeded"
    CONFLICT_BEFORE_WRITE = "conflict_before_write"
    BEGIN_APPLY = "begin_apply"
    APPLY_SUCCEEDED = "apply_succeeded"
    APPLY_FAILED = "apply_failed"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    COMPENSATION_SUCCEEDED = "compensation_succeeded"
    COMPENSATION_FAILED = "compensation_failed"
    RECOVER = "recover"
    RESOLVE_RECOVERY_ROLLED_BACK = "resolve_recovery_rolled_back"
    CONFIRM_RECOVERED_ACCEPTANCE = "confirm_recovered_acceptance"
