\set ON_ERROR_STOP on
\getenv observer_password POSTGRES_PASSWORD
SELECT format('CREATE ROLE parceldesk_monitor LOGIN PASSWORD %L', :'observer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='parceldesk_monitor')
\gexec
SELECT format('ALTER ROLE parceldesk_monitor PASSWORD %L', :'observer_password')
\gexec
GRANT pg_monitor TO parceldesk_monitor;
GRANT CONNECT ON DATABASE parceldesk TO parceldesk_monitor;
ALTER ROLE parceldesk_monitor SET default_transaction_read_only=on;
