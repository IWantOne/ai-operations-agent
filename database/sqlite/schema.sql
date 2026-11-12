CREATE TABLE IF NOT EXISTS platform_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    employee_key TEXT NOT NULL DEFAULT '',
    input_data TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    timeout_seconds REAL NOT NULL DEFAULT 3600,
    resume_enabled INTEGER NOT NULL DEFAULT 0,
    manifest_ref TEXT,
    handler TEXT NOT NULL,
    sync_data TEXT,
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS retry_budget (
    id INTEGER PRIMARY KEY AUTOINCREMENT, retry_limit INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS work_request (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
    task_id INTEGER REFERENCES task_info(id), execution_id INTEGER,
    root_id INTEGER, previous_request_id INTEGER, parent_attempt_id INTEGER, budget_id INTEGER NOT NULL REFERENCES retry_budget(id),
    source TEXT NOT NULL DEFAULT 'manual', operation_key TEXT UNIQUE,
    input_hash TEXT NOT NULL, run_input TEXT NOT NULL DEFAULT '{}', policy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED', wait_reason TEXT, ready_at REAL,
    created_at REAL NOT NULL, dispatched_at REAL, last_execution_id INTEGER, last_attempt_id INTEGER,
    version INTEGER NOT NULL DEFAULT 0, control INTEGER NOT NULL DEFAULT 0,
    result_data TEXT, error_data TEXT
);
CREATE TABLE IF NOT EXISTS work_attempt (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL REFERENCES work_request(id),
    executor TEXT NOT NULL, status TEXT NOT NULL, execution_id INTEGER,
    started_at REAL NOT NULL, finished_at REAL, stop_confirmed_at REAL,
    result_data TEXT, error_data TEXT
);
CREATE TABLE IF NOT EXISTS control_command (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target_id INTEGER, status TEXT NOT NULL,
    created_at REAL NOT NULL, finished_at REAL, error_data TEXT
);

CREATE TABLE IF NOT EXISTS execution_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES task_info(id),
    request_id INTEGER NOT NULL REFERENCES work_request(id),
    status TEXT NOT NULL DEFAULT 'STARTING',
    wait_reason TEXT,
    waiting_since REAL,
    run_input TEXT NOT NULL DEFAULT '{}',
    runtime_data TEXT NOT NULL DEFAULT '{}',
    result_data TEXT,
    resume_data TEXT,
    skill_content TEXT,
    timer_started_at REAL,
    timer_stopped_at REAL,
    started_at REAL,
    finished_at REAL,
    pause_reason TEXT,
    stop_requested_at REAL,
    stop_confirmed_at REAL,
    error_message TEXT,
    timeout_seconds REAL NOT NULL DEFAULT 3600,
    resume_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resource_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'CLOSED',
    window_ref TEXT,
    blocked INTEGER NOT NULL DEFAULT 0,
    last_checked_at REAL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS resource_lease (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER NOT NULL REFERENCES execution_info(id),
    resource_id INTEGER REFERENCES resource_info(id),
    shop_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPENING',
    requested_at REAL NOT NULL DEFAULT 0,
    acquired_at REAL,
    expires_at REAL,
    released_at REAL,
    error_message TEXT,
    window_ref TEXT
);

CREATE TABLE IF NOT EXISTS execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_id INTEGER,
    borrow_id INTEGER,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_id INTEGER,
    borrow_id INTEGER,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_id INTEGER,
    borrow_id INTEGER,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS system_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_id INTEGER,
    borrow_id INTEGER,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    execution_id INTEGER,
    borrow_id INTEGER,
    call_id TEXT,
    level TEXT NOT NULL DEFAULT 'INFO',
    action TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    occurred_at REAL NOT NULL
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    execution_id INTEGER,
    case_ref TEXT NOT NULL DEFAULT '',
    reported_at REAL,
    report_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    checked_at REAL,
    UNIQUE(sid, marketplace_id, order_id)
);

CREATE INDEX IF NOT EXISTS feedback_case_status ON feedback_case(status, updated_at);

CREATE TABLE IF NOT EXISTS store_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    account TEXT NOT NULL DEFAULT '',
    expired INTEGER NOT NULL DEFAULT 0,
    oauth TEXT NOT NULL DEFAULT '',
    seen_at REAL NOT NULL
);
