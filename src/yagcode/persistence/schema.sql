PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retention_policy_id TEXT
);
CREATE TABLE IF NOT EXISTS agent_config_versions (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, version INTEGER NOT NULL,
    plan_default INTEGER NOT NULL, permission_mode TEXT NOT NULL, budget_defaults TEXT NOT NULL,
    provider_default TEXT, UNIQUE(profile_id, version)
);
CREATE TABLE IF NOT EXISTS provider_configs (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, provider TEXT NOT NULL,
    official_endpoint TEXT NOT NULL, credential_ref TEXT, models TEXT NOT NULL, status TEXT NOT NULL,
    UNIQUE(profile_id, provider)
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    canonical_root TEXT NOT NULL, git_common_dir TEXT, write_roots TEXT NOT NULL DEFAULT '[]', validation_config TEXT NOT NULL DEFAULT '{}',
    UNIQUE(profile_id, canonical_root)
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, title TEXT NOT NULL DEFAULT '',
    task_state TEXT NOT NULL DEFAULT 'DRAFT', provider TEXT, model TEXT, review_state TEXT NOT NULL DEFAULT 'NOT_READY'
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE, state TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0), budget_version INTEGER NOT NULL DEFAULT 0 CHECK(budget_version >= 0), started_at TEXT, runtime_ms INTEGER NOT NULL DEFAULT 0 CHECK(runtime_ms >= 0)
);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, sequence INTEGER NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0), kind TEXT NOT NULL, payload_hash TEXT NOT NULL, policy_decision TEXT NOT NULL,
    status TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0), CHECK(sequence >= 0), UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS tool_results (
    action_id TEXT PRIMARY KEY REFERENCES actions(id) ON DELETE CASCADE, status TEXT NOT NULL, category TEXT NOT NULL,
    reason_code TEXT NOT NULL, exit_code INTEGER, artifact_refs TEXT NOT NULL DEFAULT '[]', side_effect_state TEXT NOT NULL CHECK(side_effect_state IN ('NONE','APPLIED','PARTIAL','UNKNOWN')),
    retryable INTEGER NOT NULL CHECK(retryable IN (0,1)), CHECK(status IN ('SUCCEEDED','FAILED','DENIED','UNKNOWN'))
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, kind TEXT NOT NULL,
    base_head TEXT, index_hash TEXT, tree_hash TEXT, journal_position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, content_hash TEXT NOT NULL,
    kind TEXT NOT NULL, path TEXT NOT NULL, expires_at TEXT, UNIQUE(profile_id, content_hash, kind)
);
CREATE TABLE IF NOT EXISTS artifact_reconciliations (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, content_hash TEXT NOT NULL, kind TEXT NOT NULL,
    target_path TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome = 'SYNC_UNCONFIRMED'),
    state TEXT NOT NULL CHECK(state IN ('PENDING','VERIFIED')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(profile_id, content_hash, kind)
);
CREATE TABLE IF NOT EXISTS validation_results (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, validator_id TEXT NOT NULL,
    required INTEGER NOT NULL CHECK(required IN (0,1)), status TEXT NOT NULL CHECK(status IN ('PASS','FAIL','UNKNOWN','MISSING')), category TEXT NOT NULL, reason_code TEXT NOT NULL,
    command_template_id TEXT NOT NULL, exit_code INTEGER, summary TEXT NOT NULL, evidence_refs TEXT NOT NULL DEFAULT '[]',
    source_action_id TEXT REFERENCES actions(id) ON DELETE SET NULL, retryable INTEGER NOT NULL CHECK(retryable IN (0,1))
);
CREATE TABLE IF NOT EXISTS approval_rules (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE, action_kind TEXT NOT NULL, verb TEXT NOT NULL,
    side_effect_class TEXT NOT NULL, canonical_scope TEXT NOT NULL, resource_identity TEXT NOT NULL,
    constraints_hash TEXT NOT NULL, policy_version INTEGER NOT NULL, lifetime TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_grants (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    canonical_source_scope TEXT NOT NULL, privacy_category TEXT NOT NULL, purpose TEXT NOT NULL,
    recipient_set_version TEXT NOT NULL, granted_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS privacy_preview_artifacts (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    privacy_grant_id TEXT REFERENCES privacy_grants(id) ON DELETE SET NULL, receiver TEXT NOT NULL,
    source_ref TEXT NOT NULL, raw_ref TEXT NOT NULL, redacted_ref TEXT NOT NULL, category TEXT NOT NULL,
    purpose TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credential_refs (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, provider TEXT NOT NULL,
    keyring_service TEXT NOT NULL, keyring_account TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(profile_id, provider)
);
CREATE TABLE IF NOT EXISTS egress_requests (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    generation INTEGER NOT NULL, action_id TEXT REFERENCES actions(id) ON DELETE SET NULL, origin TEXT NOT NULL,
    method TEXT NOT NULL, purpose TEXT NOT NULL, payload_hash TEXT NOT NULL, source_refs TEXT NOT NULL,
    privacy_categories TEXT NOT NULL, credential_ref TEXT
);
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, thread_id TEXT REFERENCES threads(id) ON DELETE CASCADE,
    scope TEXT NOT NULL, status TEXT NOT NULL, content_ref TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
    source_ids TEXT NOT NULL DEFAULT '[]', pinned INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(memory_id UNINDEXED, profile_id UNINDEXED, project_id UNINDEXED, content);
CREATE TABLE IF NOT EXISTS promotion_candidates (
    id TEXT PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    proposed_scope TEXT NOT NULL, decision TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_attempts (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, state TEXT NOT NULL,
    prior_review_state TEXT NOT NULL, baseline_ref TEXT NOT NULL, candidate_ref TEXT NOT NULL,
    target_checkpoint TEXT NOT NULL, manifest_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_entries (
    id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES integration_attempts(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL, operation TEXT NOT NULL, target_identity TEXT NOT NULL, preimage_hash TEXT,
    planned_postimage_hash TEXT, actual_postimage_hash TEXT, backup_ref TEXT, state TEXT NOT NULL,
    UNIQUE(attempt_id, sequence)
);
CREATE TABLE IF NOT EXISTS active_project_locks (
    project_identity TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE, acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS action_journal (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    action_id TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase IN ('INTENT','EFFECT','RESULT')),
    side_effecting INTEGER NOT NULL CHECK(side_effecting IN (0,1)), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, action_id, phase)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, sequence INTEGER NOT NULL,
    run_id TEXT, action_id TEXT, event_type TEXT NOT NULL, decision_ref TEXT, result TEXT NOT NULL,
    content_digest TEXT, prev_digest TEXT NOT NULL, event_digest TEXT NOT NULL, schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(profile_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_memory_items_owner ON memory_items(profile_id, project_id, scope, status);
CREATE INDEX IF NOT EXISTS idx_audit_events_profile_sequence ON audit_events(profile_id, sequence);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS approval_rules_profile_owner BEFORE INSERT ON approval_rules WHEN NEW.project_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS approval_rules_profile_owner_update BEFORE UPDATE ON approval_rules WHEN NEW.project_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS egress_requests_profile_owner BEFORE INSERT ON egress_requests WHEN NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) OR (NEW.run_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM runs JOIN threads ON threads.id = runs.thread_id JOIN projects ON projects.id = threads.project_id
    WHERE runs.id = NEW.run_id AND projects.id = NEW.project_id AND projects.profile_id = NEW.profile_id
)) OR (NEW.action_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM actions JOIN runs ON runs.id = actions.run_id JOIN threads ON threads.id = runs.thread_id
    JOIN projects ON projects.id = threads.project_id
    WHERE actions.id = NEW.action_id AND projects.id = NEW.project_id AND projects.profile_id = NEW.profile_id
)) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS egress_requests_profile_owner_update BEFORE UPDATE ON egress_requests WHEN NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) OR (NEW.run_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM runs JOIN threads ON threads.id = runs.thread_id JOIN projects ON projects.id = threads.project_id
    WHERE runs.id = NEW.run_id AND projects.id = NEW.project_id AND projects.profile_id = NEW.profile_id
)) OR (NEW.action_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM actions JOIN runs ON runs.id = actions.run_id JOIN threads ON threads.id = runs.thread_id
    JOIN projects ON projects.id = threads.project_id
    WHERE actions.id = NEW.action_id AND projects.id = NEW.project_id AND projects.profile_id = NEW.profile_id
)) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS privacy_preview_profile_owner BEFORE INSERT ON privacy_preview_artifacts WHEN NEW.privacy_grant_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM privacy_grants WHERE id = NEW.privacy_grant_id AND profile_id = NEW.profile_id
) BEGIN SELECT RAISE(ABORT, 'PROFILE_GRANT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS privacy_preview_profile_owner_update BEFORE UPDATE ON privacy_preview_artifacts WHEN NEW.privacy_grant_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM privacy_grants WHERE id = NEW.privacy_grant_id AND profile_id = NEW.profile_id
) BEGIN SELECT RAISE(ABORT, 'PROFILE_GRANT_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS memory_profile_owner BEFORE INSERT ON memory_items WHEN NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) OR (NEW.thread_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM threads JOIN projects ON projects.id = threads.project_id WHERE threads.id = NEW.thread_id AND projects.id = NEW.project_id
)) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_THREAD_OWNERSHIP'); END;
CREATE TRIGGER IF NOT EXISTS memory_profile_owner_update BEFORE UPDATE ON memory_items WHEN NOT EXISTS (
    SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id
) OR (NEW.thread_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM threads JOIN projects ON projects.id = threads.project_id WHERE threads.id = NEW.thread_id AND projects.id = NEW.project_id
)) BEGIN SELECT RAISE(ABORT, 'PROFILE_PROJECT_THREAD_OWNERSHIP'); END;
