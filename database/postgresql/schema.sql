CREATE TABLE IF NOT EXISTS platform_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_info (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    employee_key TEXT NOT NULL DEFAULT '',
    input_data TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 3600,
    resume_enabled INTEGER NOT NULL DEFAULT 0,
    manifest_ref TEXT,
    handler TEXT NOT NULL,
    sync_data TEXT,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS retry_budget (
    id BIGSERIAL PRIMARY KEY, retry_limit INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS work_request (
    id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL,
    task_id BIGINT REFERENCES task_info(id), execution_id BIGINT,
    root_id BIGINT, previous_request_id BIGINT, parent_attempt_id BIGINT, budget_id BIGINT NOT NULL REFERENCES retry_budget(id),
    source TEXT NOT NULL DEFAULT 'manual', operation_key TEXT UNIQUE,
    input_hash TEXT NOT NULL, run_input TEXT NOT NULL DEFAULT '{}', policy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED', wait_reason TEXT, ready_at DOUBLE PRECISION,
    created_at DOUBLE PRECISION NOT NULL, dispatched_at DOUBLE PRECISION, last_execution_id BIGINT, last_attempt_id BIGINT,
    version INTEGER NOT NULL DEFAULT 0, control INTEGER NOT NULL DEFAULT 0,
    result_data TEXT, error_data TEXT
);
CREATE TABLE IF NOT EXISTS work_attempt (
    id BIGSERIAL PRIMARY KEY, request_id BIGINT NOT NULL REFERENCES work_request(id),
    executor TEXT NOT NULL, status TEXT NOT NULL, execution_id BIGINT,
    started_at DOUBLE PRECISION NOT NULL, finished_at DOUBLE PRECISION, stop_confirmed_at DOUBLE PRECISION,
    result_data TEXT, error_data TEXT
);
CREATE TABLE IF NOT EXISTS control_command (
    id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, target_id BIGINT, status TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL, finished_at DOUBLE PRECISION, error_data TEXT
);

CREATE TABLE IF NOT EXISTS execution_info (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES task_info(id),
    request_id BIGINT NOT NULL REFERENCES work_request(id),
    status TEXT NOT NULL DEFAULT 'STARTING',
    wait_reason TEXT,
    waiting_since DOUBLE PRECISION,
    run_input TEXT NOT NULL DEFAULT '{}',
    runtime_data TEXT NOT NULL DEFAULT '{}',
    result_data TEXT,
    resume_data TEXT,
    skill_content TEXT,
    timer_started_at DOUBLE PRECISION,
    timer_stopped_at DOUBLE PRECISION,
    started_at DOUBLE PRECISION,
    finished_at DOUBLE PRECISION,
    pause_reason TEXT,
    stop_requested_at DOUBLE PRECISION,
    stop_confirmed_at DOUBLE PRECISION,
    error_message TEXT,
    timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 3600,
    resume_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resource_info (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'CLOSED',
    window_ref TEXT,
    blocked INTEGER NOT NULL DEFAULT 0,
    last_checked_at DOUBLE PRECISION,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS resource_lease (
    id BIGSERIAL PRIMARY KEY,
    execution_id BIGINT NOT NULL REFERENCES execution_info(id),
    resource_id BIGINT REFERENCES resource_info(id),
    shop_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPENING',
    requested_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    acquired_at DOUBLE PRECISION,
    expires_at DOUBLE PRECISION,
    released_at DOUBLE PRECISION,
    error_message TEXT,
    window_ref TEXT
);

CREATE TABLE IF NOT EXISTS execution_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    execution_id BIGINT,
    borrow_id BIGINT,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    execution_id BIGINT,
    borrow_id BIGINT,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    execution_id BIGINT,
    borrow_id BIGINT,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS system_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    execution_id BIGINT,
    borrow_id BIGINT,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_call_log (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT,
    execution_id BIGINT,
    borrow_id BIGINT,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS request_queue ON work_request(status, ready_at, created_at, id);

CREATE INDEX IF NOT EXISTS execution_task ON execution_info(task_id, status);

CREATE INDEX IF NOT EXISTS lease_queue ON resource_lease(status, requested_at, id);

CREATE UNIQUE INDEX IF NOT EXISTS lease_shop_owner ON resource_lease(shop_id) WHERE status IN ('OPENING','ACTIVE','CLOSING','UNKNOWN');

CREATE UNIQUE INDEX IF NOT EXISTS lease_execution_owner ON resource_lease(execution_id) WHERE status IN ('OPENING','ACTIVE','CLOSING','UNKNOWN');

CREATE INDEX IF NOT EXISTS execution_log_execution_time ON execution_log(execution_id, occurred_at, id);

CREATE INDEX IF NOT EXISTS resource_log_execution_time ON resource_log(execution_id, occurred_at, id);

CREATE INDEX IF NOT EXISTS runtime_log_execution_time ON runtime_log(execution_id, occurred_at, id);

CREATE INDEX IF NOT EXISTS system_log_execution_time ON system_log(execution_id, occurred_at, id);

CREATE INDEX IF NOT EXISTS tool_call_log_execution_time ON tool_call_log(execution_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS feedback_case (
    id BIGSERIAL PRIMARY KEY,
    sid TEXT NOT NULL,
    store_name TEXT NOT NULL DEFAULT '',
    marketplace_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    feedback_date TEXT NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'NEW',
    reason TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    case_ref TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    checked_at DOUBLE PRECISION,
    UNIQUE(sid, marketplace_id, order_id)
);

CREATE INDEX IF NOT EXISTS feedback_case_status ON feedback_case(status, updated_at);

CREATE TABLE IF NOT EXISTS store_info (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    account TEXT NOT NULL DEFAULT '',
    expired INTEGER NOT NULL DEFAULT 0,
    seen_at DOUBLE PRECISION NOT NULL
);
