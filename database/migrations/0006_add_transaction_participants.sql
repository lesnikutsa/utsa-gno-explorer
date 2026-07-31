BEGIN;

CREATE TABLE IF NOT EXISTS transaction_participants (
    block_height BIGINT NOT NULL,
    tx_index INTEGER NOT NULL CONSTRAINT transaction_participants_tx_index_check CHECK (tx_index >= 0),
    message_index INTEGER NOT NULL CONSTRAINT transaction_participants_message_index_check CHECK (message_index BETWEEN 0 AND 19),
    role TEXT NOT NULL CONSTRAINT transaction_participants_role_check CHECK (role IN ('sender', 'recipient')),
    address TEXT NOT NULL CONSTRAINT transaction_participants_address_check CHECK (
        char_length(address) = 40 AND address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'
    ),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (block_height, tx_index, message_index, role, address),
    FOREIGN KEY (block_height, tx_index)
        REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS transaction_participants_address_position_idx
    ON transaction_participants (address, block_height DESC, tx_index DESC);

WITH bounded_messages AS (
    SELECT transaction.block_height, transaction.tx_index,
           message.value AS message, (message.ordinality - 1)::integer AS message_index
    FROM transactions transaction
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(transaction.payload_summary) = 'object'
             AND transaction.payload_summary->>'parse_status' = 'parsed'
             AND jsonb_typeof(transaction.payload_summary->'messages') = 'array'
            THEN jsonb_path_query_array(transaction.payload_summary, '$.messages[0 to 19]')
            ELSE '[]'::jsonb
        END
    ) WITH ORDINALITY AS message(value, ordinality)
), participants AS (
    SELECT block_height, tx_index, message_index, role, address
    FROM bounded_messages
    CROSS JOIN LATERAL (VALUES
        ('sender'::text, message->>'sender'),
        ('recipient'::text, message->>'recipient')
    ) AS participant(role, address)
    WHERE jsonb_typeof(message) = 'object'
      AND address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'
)
INSERT INTO transaction_participants(block_height, tx_index, message_index, role, address)
SELECT block_height, tx_index, message_index, role, address FROM participants
ON CONFLICT DO NOTHING;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
        EXECUTE 'GRANT SELECT ON TABLE transaction_participants TO utsa_gno_api';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_indexer') THEN
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON TABLE transaction_participants TO utsa_gno_indexer';
    END IF;
END $$;

COMMIT;
