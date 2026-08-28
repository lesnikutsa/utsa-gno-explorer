# UTSA Gno.land Explorer

Independent explorer and infrastructure project for Gno.land Pearl.

## Live services

- Explorer: <https://exp.gno.utsa.tech>
- Validator monitoring bot: <https://t.me/UTSAGNOBot>

## Current release

The active public test network is Pearl, with chain ID `pearl-1`. Pearl is a
fresh chain rather than a Topaz hardfork, and complete Explorer history starts at block 1.
This independent community project does not claim official Gno.land ownership or endorsement.

## Main features

- Live network overview.
- Indexed blocks and block details.
- Transaction list and transaction details.
- Execution status, gas usage, and errors.
- Decoded Gno messages and bounded `MsgCall` argument values.
- Account pages and paginated transaction history.
- Validator list and validator detail pages.
- Official Valopers metadata.
- Signing history, missed blocks, and voting power.
- Governance proposals and votes.
- Observed peer and network distribution.
- Global search.
- Multi-RPC health and safe failover.
- Responsive frontend.
- Continuous PostgreSQL indexer and read-only API.

## Architecture

```text
Gno RPCs
  → continuous indexer
  → PostgreSQL
  → read-only API
  → React frontend
```

The indexer owns sequential ingestion. The API uses a separate read-only database role.
The static React/Vite build is served by Nginx; there is no frontend systemd service.
Governance, Valopers, network-distribution, and backup jobs use separate units.

## Requirements

Production is designed for a supported Ubuntu server with:

- Python 3 and a virtual environment;
- Go for the transaction decoder;
- Node.js 22 and npm for the frontend;
- Docker Engine with Compose and PostgreSQL 16;
- systemd, Nginx, rsync, and operator-managed TLS;
- access to the Pearl RPC endpoint.

Production configuration and secrets live outside Git under `/etc/utsa-gno-explorer`.
Never commit database passwords or credential-bearing RPC URLs.

## Documentation

- [Fresh installation](docs/install.md)
- [Production update](docs/update.md)
- [Backup and restore](docs/restore.md)
- [Operator runbook](docs/operator-runbook.md)
- [Detailed production reference](docs/production-deployment.md)
- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Transaction decoding](docs/transaction-decoding.md)
- [Changelog](CHANGELOG.md)
- [v1.0.0 release notes](docs/releases/v1.0.0.md)

Historical prototype material is retained under [`docs/archive/`](docs/archive/), clearly
separated from current operating instructions.

## Development

Install Python development dependencies in a virtual environment, then run:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Test the Go decoder independently:

```bash
cd tools/gno-tx-decoder
go test ./...
```

Use Node.js 22 for frontend development and verification:

```bash
cd frontend
npm install
node --test test/*.test.js
npm run build
```

Production installation, migrations, service restarts, and frontend publication are always
explicit operator actions. Use the dedicated guides rather than this landing page as a
production manual.
