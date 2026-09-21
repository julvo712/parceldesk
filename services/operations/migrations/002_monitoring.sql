CREATE INDEX IF NOT EXISTS action_attempts_run_created ON action_attempts(run_id,created_at);
CREATE INDEX IF NOT EXISTS conversations_customer ON conversations(run_id,customer_id);
CREATE INDEX IF NOT EXISTS sessions_expiration ON sessions(expires_at);
-- The exporter account is provisioned separately with pg_monitor, without business write access.
