BEGIN;

CREATE TABLE realm_call_index (
    chain_id TEXT NOT NULL,
    block_height BIGINT NOT NULL,
    tx_index INTEGER NOT NULL,
    message_index INTEGER NOT NULL,
    path TEXT NOT NULL,
    caller_address TEXT,
    function_name TEXT,
    args_count INTEGER,
    send_amount TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, block_height, tx_index, message_index),
    FOREIGN KEY (block_height, tx_index)
        REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE,
    CONSTRAINT realm_call_index_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    CONSTRAINT realm_call_index_block_height_check CHECK (block_height > 0),
    CONSTRAINT realm_call_index_tx_index_check CHECK (tx_index >= 0),
    CONSTRAINT realm_call_index_message_index_check CHECK (message_index BETWEEN 0 AND 19),
    CONSTRAINT realm_call_index_path_check CHECK (char_length(path) BETWEEN 1 AND 256 AND path ~ '^gno\.land/r/[!-\.0-~]+(/[!-\.0-~]+)*$' AND path !~ '[?#]'),
    CONSTRAINT realm_call_index_caller_check CHECK (caller_address IS NULL OR caller_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    CONSTRAINT realm_call_index_function_check CHECK (function_name IS NULL OR char_length(function_name) BETWEEN 1 AND 160),
    CONSTRAINT realm_call_index_args_count_check CHECK (args_count IS NULL OR args_count BETWEEN 0 AND 100000),
    CONSTRAINT realm_call_index_send_check CHECK (send_amount IS NULL OR char_length(send_amount) BETWEEN 1 AND 160)
);
CREATE INDEX realm_call_index_path_position_idx ON realm_call_index
    (chain_id, path, block_height DESC, tx_index DESC, message_index DESC);

CREATE TABLE realm_call_index_state (
    chain_id TEXT PRIMARY KEY,
    from_height BIGINT NOT NULL,
    through_height BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT realm_call_index_state_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    CONSTRAINT realm_call_index_state_from_height_check CHECK (from_height > 0),
    CONSTRAINT realm_call_index_state_range_check CHECK (through_height >= from_height)
);

COMMENT ON TABLE realm_call_index IS 'Compact locator projection of bounded MsgCall summaries; heavy call payloads remain excluded.';
COMMENT ON TABLE realm_call_index_state IS 'Continuous block range whose bounded MsgCall observations were processed into realm_call_index.';

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_api') THEN
  GRANT SELECT ON realm_call_index, realm_call_index_state TO utsa_gno_api;
 END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_indexer') THEN
  GRANT SELECT,INSERT,UPDATE,DELETE ON realm_call_index, realm_call_index_state TO utsa_gno_indexer;
 END IF;
END $$;
COMMIT;
