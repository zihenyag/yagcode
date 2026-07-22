"""Pure, fail-closed lifecycle state transitions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn, TypeVar, cast

from yagcode.domain.errors import TransitionError
from yagcode.domain.states import (
    IntegrationEvent,
    IntegrationState,
    RecoveryClass,
    ReviewEvent,
    ReviewState,
    RunEvent,
    RunState,
    TaskEvent,
    TaskState,
)


RUN_INVALID = "RUN_TRANSITION_INVALID"
TASK_INVALID = "TASK_TRANSITION_INVALID"
REVIEW_INVALID = "REVIEW_TRANSITION_INVALID"
INTEGRATION_INVALID = "INTEGRATION_TRANSITION_INVALID"
EnumT = TypeVar("EnumT", bound=StrEnum)


def _invalid(reason_code: str) -> NoReturn:
    raise TransitionError(reason_code)


def _bools_are_exact(values: tuple[bool, ...]) -> bool:
    return all(type(value) is bool for value in values)


@dataclass(frozen=True)
class RunGuards:
    project_lock_acquired: bool = False
    start_checkpoint_persisted: bool = False
    plan_approved: bool = False
    process_tree_dead: bool = False
    stop_checkpoint_persisted: bool = False
    unknown_side_effects_reconciled: bool = False
    resume_guards_resolved: bool = False
    pending_side_effects: bool = True

    def __post_init__(self) -> None:
        if not _bools_are_exact(
            (
                self.project_lock_acquired,
                self.start_checkpoint_persisted,
                self.plan_approved,
                self.process_tree_dead,
                self.stop_checkpoint_persisted,
                self.unknown_side_effects_reconciled,
                self.resume_guards_resolved,
                self.pending_side_effects,
            )
        ):
            _invalid(RUN_INVALID)


@dataclass(frozen=True)
class TaskGuards:
    project_lock_acquired: bool = False
    has_locking_run: bool = True
    has_pending_approval: bool = True
    review_state: ReviewState | None = None

    def __post_init__(self) -> None:
        if not _bools_are_exact(
            (self.project_lock_acquired, self.has_locking_run, self.has_pending_approval)
        ):
            _invalid(TASK_INVALID)
        if self.review_state is not None and type(self.review_state) is not ReviewState:
            _invalid(TASK_INVALID)


@dataclass(frozen=True)
class ReviewGuards:
    validations_evaluated: bool = False
    required_validations_passed: bool = False
    incomplete_confirmation: bool = False
    integration_outcome: IntegrationState | None = None
    prior_review_state: ReviewState | None = None
    conflict_cleared: bool = False
    preimage_verified: bool = False
    no_live_process: bool = False
    no_unknown_side_effect: bool = False
    no_hard_block: bool = False
    trusted_confirmation: bool = False

    def __post_init__(self) -> None:
        if not _bools_are_exact(
            (
                self.validations_evaluated,
                self.required_validations_passed,
                self.incomplete_confirmation,
                self.conflict_cleared,
                self.preimage_verified,
                self.no_live_process,
                self.no_unknown_side_effect,
                self.no_hard_block,
                self.trusted_confirmation,
            )
        ):
            _invalid(REVIEW_INVALID)
        if (
            self.integration_outcome is not None
            and type(self.integration_outcome) is not IntegrationState
        ):
            _invalid(REVIEW_INVALID)
        if self.prior_review_state is not None and type(self.prior_review_state) is not ReviewState:
            _invalid(REVIEW_INVALID)


@dataclass(frozen=True)
class IntegrationGuards:
    manifest_persisted: bool = False
    locks_held: bool = False
    no_real_write: bool = False
    all_entries_applied: bool = False
    failure_recorded: bool = False
    all_entries_verified: bool = False
    required_validations_passed: bool = False
    all_preimages_verified: bool = False
    recovery_evidence_recorded: bool = False
    recovery_classification: RecoveryClass | None = None
    trusted_confirmation: bool = False

    def __post_init__(self) -> None:
        if not _bools_are_exact(
            (
                self.manifest_persisted,
                self.locks_held,
                self.no_real_write,
                self.all_entries_applied,
                self.failure_recorded,
                self.all_entries_verified,
                self.required_validations_passed,
                self.all_preimages_verified,
                self.recovery_evidence_recorded,
                self.trusted_confirmation,
            )
        ):
            _invalid(INTEGRATION_INVALID)
        if (
            self.recovery_classification is not None
            and type(self.recovery_classification) is not RecoveryClass
        ):
            _invalid(INTEGRATION_INVALID)


def _parse_event(value: object, event_type: type[EnumT], invalid_code: str) -> EnumT:
    if type(value) is event_type:
        return value
    if type(value) is str:
        try:
            return event_type(value)
        except ValueError:
            _invalid(invalid_code)
    _invalid(invalid_code)


def _guard_field_values(
    guards: object, guard_type: type[object], names: tuple[str, ...], invalid_code: str
) -> tuple[object, ...]:
    if type(guards) is not guard_type:
        _invalid(invalid_code)
    try:
        attributes = vars(guards)
    except TypeError:
        _invalid(invalid_code)
    if set(attributes) != set(names):
        _invalid(invalid_code)
    try:
        return tuple(getattr(guards, name) for name in names)
    except AttributeError:
        _invalid(invalid_code)


def _valid_run_guards(guards: object) -> RunGuards:
    values = _guard_field_values(
        guards,
        RunGuards,
        (
            "project_lock_acquired",
            "start_checkpoint_persisted",
            "plan_approved",
            "process_tree_dead",
            "stop_checkpoint_persisted",
            "unknown_side_effects_reconciled",
            "resume_guards_resolved",
            "pending_side_effects",
        ),
        RUN_INVALID,
    )
    if not all(type(value) is bool for value in values):
        _invalid(RUN_INVALID)
    return cast(RunGuards, guards)


def _valid_task_guards(guards: object) -> TaskGuards:
    project_lock_acquired, has_locking_run, has_pending_approval, review_state = _guard_field_values(
        guards,
        TaskGuards,
        ("project_lock_acquired", "has_locking_run", "has_pending_approval", "review_state"),
        TASK_INVALID,
    )
    if not all(type(value) is bool for value in (project_lock_acquired, has_locking_run, has_pending_approval)):
        _invalid(TASK_INVALID)
    if review_state is not None and type(review_state) is not ReviewState:
        _invalid(TASK_INVALID)
    return cast(TaskGuards, guards)


def _valid_review_guards(guards: object) -> ReviewGuards:
    values = _guard_field_values(
        guards,
        ReviewGuards,
        (
            "validations_evaluated",
            "required_validations_passed",
            "incomplete_confirmation",
            "integration_outcome",
            "prior_review_state",
            "conflict_cleared",
            "preimage_verified",
            "no_live_process",
            "no_unknown_side_effect",
            "no_hard_block",
            "trusted_confirmation",
        ),
        REVIEW_INVALID,
    )
    bool_indices = (0, 1, 2, 5, 6, 7, 8, 9, 10)
    if not all(type(values[index]) is bool for index in bool_indices):
        _invalid(REVIEW_INVALID)
    if values[3] is not None and type(values[3]) is not IntegrationState:
        _invalid(REVIEW_INVALID)
    if values[4] is not None and type(values[4]) is not ReviewState:
        _invalid(REVIEW_INVALID)
    return cast(ReviewGuards, guards)


def _valid_integration_guards(guards: object) -> IntegrationGuards:
    values = _guard_field_values(
        guards,
        IntegrationGuards,
        (
            "manifest_persisted",
            "locks_held",
            "no_real_write",
            "all_entries_applied",
            "failure_recorded",
            "all_entries_verified",
            "required_validations_passed",
            "all_preimages_verified",
            "recovery_evidence_recorded",
            "recovery_classification",
            "trusted_confirmation",
        ),
        INTEGRATION_INVALID,
    )
    bool_indices = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10)
    if not all(type(values[index]) is bool for index in bool_indices):
        _invalid(INTEGRATION_INVALID)
    if values[9] is not None and type(values[9]) is not RecoveryClass:
        _invalid(INTEGRATION_INVALID)
    return cast(IntegrationGuards, guards)


def transition_run(
    state: RunState, event: RunEvent | str, guards: RunGuards = RunGuards()
) -> RunState:
    parsed = _parse_event(event, RunEvent, RUN_INVALID)
    if type(state) is not RunState:
        _invalid(RUN_INVALID)
    checked = _valid_run_guards(guards)
    if parsed is RunEvent.START_PLAN:
        if state is not RunState.CREATED:
            _invalid(RUN_INVALID)
        if not checked.project_lock_acquired:
            _invalid("RUN_START_REQUIRES_PROJECT_LOCK")
        return RunState.PLANNING
    if parsed is RunEvent.START_WITHOUT_PLAN:
        if state is not RunState.CREATED:
            _invalid(RUN_INVALID)
        if not checked.project_lock_acquired:
            _invalid("RUN_START_REQUIRES_PROJECT_LOCK")
        if not checked.start_checkpoint_persisted:
            _invalid("RUN_START_CHECKPOINT_REQUIRED")
        return RunState.RUNNING
    if parsed is RunEvent.PLAN_READY:
        if state is not RunState.PLANNING:
            _invalid(RUN_INVALID)
        return RunState.WAITING_PLAN_APPROVAL
    if parsed is RunEvent.APPROVE_PLAN:
        if state is not RunState.WAITING_PLAN_APPROVAL:
            _invalid(RUN_INVALID)
        if not checked.plan_approved:
            _invalid("PLAN_APPROVAL_REQUIRED")
        return RunState.RUNNING
    if parsed in (
        RunEvent.WAIT_PERMISSION,
        RunEvent.WAIT_PRIVACY,
        RunEvent.START_COMPACTION,
        RunEvent.PAUSE_BUDGET,
        RunEvent.PAUSE_FAILURE,
        RunEvent.FINISH_CANDIDATE,
    ):
        if state is not RunState.RUNNING:
            _invalid(RUN_INVALID)
        if parsed is RunEvent.WAIT_PERMISSION:
            return RunState.WAITING_PERMISSION
        if parsed is RunEvent.WAIT_PRIVACY:
            return RunState.WAITING_PRIVACY
        if parsed is RunEvent.START_COMPACTION:
            return RunState.COMPACTING
        if parsed is RunEvent.PAUSE_BUDGET:
            return RunState.PAUSED_BUDGET
        if parsed is RunEvent.PAUSE_FAILURE:
            return RunState.PAUSED_FAILURE
        if checked.pending_side_effects:
            _invalid("RUN_PENDING_SIDE_EFFECTS")
        return RunState.FINISHED
    if parsed is RunEvent.DECISION_RESOLVED:
        if state not in (RunState.WAITING_PERMISSION, RunState.WAITING_PRIVACY):
            _invalid("RUN_DECISION_NOT_PENDING")
        return RunState.RUNNING
    if parsed in (RunEvent.COMPACTION_SUCCEEDED, RunEvent.COMPACTION_FAILED):
        if state is not RunState.COMPACTING:
            _invalid(RUN_INVALID)
        return (
            RunState.RUNNING if parsed is RunEvent.COMPACTION_SUCCEEDED else RunState.PAUSED_FAILURE
        )
    if parsed is RunEvent.REQUEST_STOP:
        if state is RunState.INTERRUPTED:
            _invalid("RUN_RECONCILIATION_REQUIRED")
        if state in (
            RunState.CREATED,
            RunState.PAUSED_BY_USER,
            RunState.PAUSED_BUDGET,
            RunState.PAUSED_FAILURE,
            RunState.FINISHED,
        ):
            _invalid("RUN_NOT_ACTIVE")
        if state not in (
            RunState.PLANNING,
            RunState.WAITING_PLAN_APPROVAL,
            RunState.RUNNING,
            RunState.WAITING_PERMISSION,
            RunState.WAITING_PRIVACY,
            RunState.COMPACTING,
            RunState.STOPPING,
        ):
            _invalid(RUN_INVALID)
        return RunState.STOPPING
    if parsed is RunEvent.STOP_CONFIRMED:
        if state not in (RunState.STOPPING, RunState.INTERRUPTED):
            _invalid("RUN_STOP_NOT_PENDING")
        if not checked.process_tree_dead:
            _invalid("RUN_STOP_PROCESS_STILL_ALIVE")
        if not checked.stop_checkpoint_persisted:
            _invalid("RUN_STOP_CHECKPOINT_REQUIRED")
        if state is RunState.INTERRUPTED and not checked.unknown_side_effects_reconciled:
            _invalid("RUN_RECONCILIATION_REQUIRED")
        return RunState.PAUSED_BY_USER
    if parsed is RunEvent.STOP_UNCONFIRMED:
        if state is not RunState.STOPPING:
            _invalid("RUN_STOP_NOT_PENDING")
        return RunState.INTERRUPTED
    if parsed is RunEvent.RESUME:
        if (
            state not in (RunState.PAUSED_BY_USER, RunState.PAUSED_BUDGET, RunState.PAUSED_FAILURE)
            or not checked.resume_guards_resolved
        ):
            _invalid("RUN_RESUME_GUARD_UNMET")
        return RunState.RUNNING
    if parsed is RunEvent.SWITCH_MODEL:
        if state is not RunState.PAUSED_BY_USER:
            _invalid("MODEL_SWITCH_REQUIRES_PAUSED_BY_USER")
        return RunState.PAUSED_BY_USER
    _invalid(RUN_INVALID)


def _task_close_checks(guards: TaskGuards) -> None:
    if guards.has_locking_run:
        _invalid("TASK_CLOSE_BLOCKED_BY_RUN")
    if guards.has_pending_approval:
        _invalid("TASK_CLOSE_BLOCKED_BY_APPROVAL")
    if guards.review_state is None:
        _invalid("TASK_REVIEW_STATE_REQUIRED")
    if guards.review_state is ReviewState.ACCEPTING:
        _invalid("TASK_CLOSE_BLOCKED_BY_ACCEPTING")
    if guards.review_state is ReviewState.RECOVERY_REQUIRED:
        _invalid("TASK_CLOSE_BLOCKED_BY_RECOVERY")


def transition_task(
    state: TaskState, event: TaskEvent | str, guards: TaskGuards = TaskGuards()
) -> TaskState:
    parsed = _parse_event(event, TaskEvent, TASK_INVALID)
    if type(state) is not TaskState:
        _invalid(TASK_INVALID)
    checked = _valid_task_guards(guards)
    if parsed is TaskEvent.ACTIVATE:
        if state is not TaskState.DRAFT:
            _invalid(TASK_INVALID)
        if not checked.project_lock_acquired:
            _invalid("TASK_ACTIVATION_REQUIRES_PROJECT_LOCK")
        return TaskState.ACTIVE
    if parsed is TaskEvent.CLOSE:
        if state is not TaskState.ACTIVE:
            _invalid(TASK_INVALID)
        _task_close_checks(checked)
        return TaskState.CLOSED
    if parsed is TaskEvent.REOPEN:
        if state is not TaskState.CLOSED:
            _invalid(TASK_INVALID)
        return TaskState.ACTIVE
    if parsed is TaskEvent.ARCHIVE:
        if state is not TaskState.CLOSED:
            _invalid(TASK_INVALID)
        _task_close_checks(checked)
        return TaskState.ARCHIVED
    if parsed is TaskEvent.RESTORE_ARCHIVE:
        if state is not TaskState.ARCHIVED:
            _invalid(TASK_INVALID)
        return TaskState.CLOSED
    _invalid(TASK_INVALID)


def transition_review(
    state: ReviewState, event: ReviewEvent | str, guards: ReviewGuards = ReviewGuards()
) -> ReviewState:
    parsed = _parse_event(event, ReviewEvent, REVIEW_INVALID)
    if type(state) is not ReviewState:
        _invalid(REVIEW_INVALID)
    checked = _valid_review_guards(guards)
    if parsed is ReviewEvent.CANDIDATE_INCOMPLETE:
        if state not in (ReviewState.NOT_READY, ReviewState.READY):
            _invalid(REVIEW_INVALID)
        if not checked.validations_evaluated:
            _invalid("REVIEW_VALIDATIONS_NOT_EVALUATED")
        if checked.required_validations_passed:
            _invalid("REVIEW_VALIDATION_PROJECTION_MISMATCH")
        return ReviewState.INCOMPLETE
    if parsed is ReviewEvent.CANDIDATE_READY:
        if state not in (ReviewState.NOT_READY, ReviewState.INCOMPLETE):
            _invalid(REVIEW_INVALID)
        if not checked.validations_evaluated:
            _invalid("REVIEW_VALIDATIONS_NOT_EVALUATED")
        if not checked.required_validations_passed:
            _invalid("REVIEW_REQUIRED_VALIDATIONS_NOT_PASSED")
        return ReviewState.READY
    if parsed is ReviewEvent.CONTINUE_WORK:
        if state not in (ReviewState.READY, ReviewState.INCOMPLETE):
            _invalid(REVIEW_INVALID)
        return ReviewState.NOT_READY
    if parsed is ReviewEvent.BEGIN_ACCEPT:
        if state not in (ReviewState.READY, ReviewState.INCOMPLETE):
            _invalid(REVIEW_INVALID)
        if not checked.no_hard_block:
            _invalid("REVIEW_HARD_BLOCK_UNRESOLVED")
        if not checked.no_unknown_side_effect:
            _invalid("REVIEW_UNKNOWN_SIDE_EFFECTS")
        if not checked.no_live_process:
            _invalid("REVIEW_PROCESS_STILL_RUNNING")
        if state is ReviewState.INCOMPLETE and not checked.incomplete_confirmation:
            _invalid("REVIEW_INCOMPLETE_CONFIRMATION_REQUIRED")
        return ReviewState.ACCEPTING
    if parsed is ReviewEvent.ACCEPT_SUCCEEDED:
        if state not in (ReviewState.ACCEPTING, ReviewState.RECOVERY_REQUIRED):
            _invalid(REVIEW_INVALID)
        if checked.integration_outcome is not IntegrationState.ACCEPTED:
            _invalid("REVIEW_INTEGRATION_OUTCOME_MISMATCH")
        if state is ReviewState.RECOVERY_REQUIRED and not checked.trusted_confirmation:
            _invalid("REVIEW_TRUSTED_CONFIRMATION_REQUIRED")
        return ReviewState.ACCEPTED
    if parsed is ReviewEvent.ACCEPT_CONFLICT:
        if state is not ReviewState.ACCEPTING:
            _invalid(REVIEW_INVALID)
        if checked.integration_outcome is not IntegrationState.CONFLICT_BEFORE_WRITE:
            _invalid("REVIEW_INTEGRATION_OUTCOME_MISMATCH")
        return ReviewState.CONFLICT
    if parsed is ReviewEvent.ACCEPT_RECOVERY_REQUIRED:
        if state is not ReviewState.ACCEPTING:
            _invalid(REVIEW_INVALID)
        if checked.integration_outcome is not IntegrationState.ACCEPT_RECOVERY_REQUIRED:
            _invalid("REVIEW_INTEGRATION_OUTCOME_MISMATCH")
        return ReviewState.RECOVERY_REQUIRED
    if parsed is ReviewEvent.ACCEPT_ROLLED_BACK:
        if state not in (ReviewState.ACCEPTING, ReviewState.RECOVERY_REQUIRED):
            _invalid(REVIEW_INVALID)
        if checked.integration_outcome is not IntegrationState.ACCEPT_FAILED_ROLLED_BACK:
            _invalid("REVIEW_INTEGRATION_OUTCOME_MISMATCH")
        if not checked.preimage_verified:
            _invalid("REVIEW_ROLLBACK_NOT_VERIFIED")
        if checked.prior_review_state not in (ReviewState.READY, ReviewState.INCOMPLETE):
            _invalid("REVIEW_PRIOR_STATE_REQUIRED")
        assert checked.prior_review_state is not None
        return checked.prior_review_state
    if parsed in (ReviewEvent.RESOLVE_CONFLICT_READY, ReviewEvent.RESOLVE_CONFLICT_INCOMPLETE):
        if state is not ReviewState.CONFLICT:
            _invalid(REVIEW_INVALID)
        if not checked.conflict_cleared:
            _invalid("REVIEW_CONFLICT_NOT_RESOLVED")
        if not checked.validations_evaluated:
            _invalid("REVIEW_VALIDATIONS_NOT_EVALUATED")
        required = parsed is ReviewEvent.RESOLVE_CONFLICT_READY
        if checked.required_validations_passed is not required:
            _invalid("REVIEW_VALIDATION_PROJECTION_MISMATCH")
        return ReviewState.READY if required else ReviewState.INCOMPLETE
    if parsed is ReviewEvent.REJECT:
        if state not in (
            ReviewState.NOT_READY,
            ReviewState.INCOMPLETE,
            ReviewState.READY,
            ReviewState.CONFLICT,
        ):
            _invalid(REVIEW_INVALID)
        if not checked.no_hard_block:
            _invalid("REVIEW_HARD_BLOCK_UNRESOLVED")
        if not checked.no_unknown_side_effect:
            _invalid("REVIEW_UNKNOWN_SIDE_EFFECTS")
        if not checked.no_live_process:
            _invalid("REVIEW_PROCESS_STILL_RUNNING")
        return ReviewState.REJECTED
    if parsed is ReviewEvent.RECOVERY_STILL_REQUIRED:
        if state is not ReviewState.RECOVERY_REQUIRED:
            _invalid(REVIEW_INVALID)
        if checked.integration_outcome is not IntegrationState.ACCEPT_RECOVERY_REQUIRED:
            _invalid("REVIEW_INTEGRATION_OUTCOME_MISMATCH")
        return ReviewState.RECOVERY_REQUIRED
    _invalid(REVIEW_INVALID)


def transition_integration(
    state: IntegrationState,
    event: IntegrationEvent | str,
    guards: IntegrationGuards = IntegrationGuards(),
) -> IntegrationState:
    parsed = _parse_event(event, IntegrationEvent, INTEGRATION_INVALID)
    if type(state) is not IntegrationState:
        _invalid(INTEGRATION_INVALID)
    checked = _valid_integration_guards(guards)
    if parsed is IntegrationEvent.PREPARE_SUCCEEDED:
        if state is not IntegrationState.PREPARING:
            _invalid(INTEGRATION_INVALID)
        if not (checked.manifest_persisted and checked.locks_held):
            _invalid("INTEGRATION_PREPARE_GUARD_UNMET")
        return IntegrationState.PREPARED
    if parsed is IntegrationEvent.CONFLICT_BEFORE_WRITE:
        if state not in (IntegrationState.PREPARING, IntegrationState.PREPARED):
            _invalid(INTEGRATION_INVALID)
        if not checked.no_real_write:
            _invalid("INTEGRATION_CONFLICT_AFTER_WRITE")
        return IntegrationState.CONFLICT_BEFORE_WRITE
    if parsed is IntegrationEvent.BEGIN_APPLY:
        if state is not IntegrationState.PREPARED:
            _invalid(INTEGRATION_INVALID)
        if not (checked.manifest_persisted and checked.locks_held):
            _invalid("INTEGRATION_PREPARE_GUARD_UNMET")
        return IntegrationState.APPLYING
    if parsed is IntegrationEvent.APPLY_SUCCEEDED:
        if state is not IntegrationState.APPLYING:
            _invalid(INTEGRATION_INVALID)
        if not checked.all_entries_applied:
            _invalid("INTEGRATION_APPLY_INCOMPLETE")
        return IntegrationState.VERIFYING
    if parsed is IntegrationEvent.APPLY_FAILED:
        if state is not IntegrationState.APPLYING:
            _invalid(INTEGRATION_INVALID)
        if not checked.failure_recorded:
            _invalid("INTEGRATION_FAILURE_NOT_RECORDED")
        return IntegrationState.COMPENSATING
    if parsed is IntegrationEvent.VERIFICATION_SUCCEEDED:
        if state is not IntegrationState.VERIFYING:
            _invalid(INTEGRATION_INVALID)
        if not (checked.all_entries_verified and checked.required_validations_passed):
            _invalid("INTEGRATION_VERIFICATION_INCOMPLETE")
        return IntegrationState.ACCEPTED
    if parsed is IntegrationEvent.VERIFICATION_FAILED:
        if state is not IntegrationState.VERIFYING:
            _invalid(INTEGRATION_INVALID)
        if not checked.failure_recorded:
            _invalid("INTEGRATION_FAILURE_NOT_RECORDED")
        return IntegrationState.COMPENSATING
    if parsed is IntegrationEvent.COMPENSATION_SUCCEEDED:
        if state is not IntegrationState.COMPENSATING:
            _invalid(INTEGRATION_INVALID)
        if not checked.all_preimages_verified:
            _invalid("INTEGRATION_PREIMAGE_NOT_VERIFIED")
        return IntegrationState.ACCEPT_FAILED_ROLLED_BACK
    if parsed is IntegrationEvent.COMPENSATION_FAILED:
        if state is not IntegrationState.COMPENSATING:
            _invalid(INTEGRATION_INVALID)
        if not checked.recovery_evidence_recorded:
            _invalid("INTEGRATION_RECOVERY_EVIDENCE_REQUIRED")
        return IntegrationState.ACCEPT_RECOVERY_REQUIRED
    if parsed is IntegrationEvent.RECOVER:
        if state not in (
            IntegrationState.PREPARED,
            IntegrationState.APPLYING,
            IntegrationState.VERIFYING,
            IntegrationState.COMPENSATING,
        ):
            _invalid(INTEGRATION_INVALID)
        if not checked.recovery_evidence_recorded:
            _invalid("INTEGRATION_RECOVERY_EVIDENCE_REQUIRED")
        if checked.recovery_classification is None:
            _invalid("INTEGRATION_RECOVERY_CLASSIFICATION_REQUIRED")
        if checked.recovery_classification is RecoveryClass.ALL_PREIMAGE:
            if not checked.all_preimages_verified:
                _invalid("INTEGRATION_PREIMAGE_NOT_VERIFIED")
            return IntegrationState.ACCEPT_FAILED_ROLLED_BACK
        if checked.recovery_classification is RecoveryClass.OWNED_POSTIMAGE_COMPENSATABLE:
            return IntegrationState.COMPENSATING
        return IntegrationState.ACCEPT_RECOVERY_REQUIRED
    if parsed is IntegrationEvent.RESOLVE_RECOVERY_ROLLED_BACK:
        if state is not IntegrationState.ACCEPT_RECOVERY_REQUIRED:
            _invalid(INTEGRATION_INVALID)
        if checked.recovery_classification is not RecoveryClass.ALL_PREIMAGE:
            _invalid("INTEGRATION_RECOVERY_CLASSIFICATION_MISMATCH")
        if not checked.all_preimages_verified:
            _invalid("INTEGRATION_PREIMAGE_NOT_VERIFIED")
        return IntegrationState.ACCEPT_FAILED_ROLLED_BACK
    if parsed is IntegrationEvent.CONFIRM_RECOVERED_ACCEPTANCE:
        if state is not IntegrationState.ACCEPT_RECOVERY_REQUIRED:
            _invalid(INTEGRATION_INVALID)
        if checked.recovery_classification is not RecoveryClass.ALL_POSTIMAGE:
            _invalid("INTEGRATION_RECOVERY_CLASSIFICATION_MISMATCH")
        if not (checked.all_entries_verified and checked.required_validations_passed):
            _invalid("INTEGRATION_VERIFICATION_INCOMPLETE")
        if not checked.trusted_confirmation:
            _invalid("INTEGRATION_TRUSTED_CONFIRMATION_REQUIRED")
        return IntegrationState.ACCEPTED
    _invalid(INTEGRATION_INVALID)
