ALTER TABLE rpc_endpoints ADD COLUMN IF NOT EXISTS latency_ms INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rpc_endpoints'
          AND column_name = 'latency_ms' AND data_type = 'integer' AND is_nullable = 'YES'
    ) THEN
        RAISE EXCEPTION 'rpc_endpoints.latency_ms has an incompatible definition';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rpc_endpoints'::regclass
          AND conname = 'rpc_endpoints_latency_ms_check'
          AND pg_get_constraintdef(oid) <> 'CHECK (((latency_ms IS NULL) OR ((latency_ms >= 0) AND (latency_ms <= 30000))))'
    ) THEN
        RAISE EXCEPTION 'rpc_endpoints latency constraint is incompatible';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rpc_endpoints'::regclass AND conname = 'rpc_endpoints_latency_ms_check'
    ) THEN
        ALTER TABLE rpc_endpoints ADD CONSTRAINT rpc_endpoints_latency_ms_check
            CHECK (latency_ms IS NULL OR latency_ms BETWEEN 0 AND 30000);
    END IF;
END $$;
