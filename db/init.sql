-- Run as the database owner. No default passwords: configure LOGIN credentials separately.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mis_admin') THEN
        CREATE ROLE mis_admin LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mis_app') THEN
        CREATE ROLE mis_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mis_runtime') THEN
        CREATE ROLE mis_runtime LOGIN;
    END IF;
    EXECUTE 'GRANT mis_admin, mis_app, mis_runtime TO ' || quote_ident(current_user);
END $$;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS mis AUTHORIZATION mis_admin;
CREATE SCHEMA IF NOT EXISTS runtime AUTHORIZATION mis_admin;
CREATE SCHEMA IF NOT EXISTS trace AUTHORIZATION mis_admin;
CREATE SCHEMA IF NOT EXISTS knowledge AUTHORIZATION mis_admin;
CREATE SCHEMA IF NOT EXISTS cache AUTHORIZATION mis_admin;
GRANT USAGE ON SCHEMA mis, knowledge, cache, trace TO mis_app;
GRANT USAGE ON SCHEMA mis, runtime, trace TO mis_runtime;
GRANT CREATE ON SCHEMA runtime TO mis_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA mis FROM mis_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA mis TO mis_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mis, knowledge, cache TO mis_app;
GRANT SELECT ON ALL TABLES IN SCHEMA trace TO mis_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA runtime, trace TO mis_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE mis_admin IN SCHEMA mis
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mis_admin IN SCHEMA mis GRANT SELECT ON TABLES TO mis_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE mis_admin IN SCHEMA knowledge, cache
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mis_admin IN SCHEMA trace GRANT SELECT ON TABLES TO mis_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mis_admin IN SCHEMA trace, runtime
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mis_runtime;
