import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import backup_database, init_database, wait_for_postgres

ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def text(self, relative):
        return (ROOT / relative).read_text()

    def test_shared_rpc_environment_and_unit_precedence(self):
        rpc_env = self.text("deploy/systemd/rpc.env.example")
        definitions = [line.split("=", 1)[0] for line in rpc_env.splitlines()
                       if line and not line.startswith("#") and "=" in line]
        self.assertEqual(definitions, ["GNO_CHAIN_ID", "GNO_RPC_URLS", "RPC_MAX_HEIGHT_LAG"])
        self.assertNotRegex(rpc_env.lower(), r"database_url|password|token|https?://[^\s]+@")
        for example in ("api.env.example", "indexer.env.example"):
            text = self.text(f"deploy/systemd/{example}")
            for name in definitions:
                self.assertNotRegex(text, rf"(?m)^{name}=")
        expected = {
            "utsa-gno-api.service": ["api.env", "rpc.env"],
            "utsa-gno-indexer.service": ["indexer.env", "rpc.env"],
            "utsa-gno-governance-updater.service": ["indexer.env", "rpc.env"],
            "utsa-gno-valopers-refresh.service": ["indexer.env", "rpc.env"],
            "utsa-gno-network-distribution.service": [
                "indexer.env", "-network-distribution.env", "rpc.env",
            ],
        }
        for filename, suffixes in expected.items():
            unit = self.text(f"deploy/systemd/{filename}")
            files = [line.split("=", 1)[1].replace("/etc/utsa-gno-explorer/", "")
                     for line in unit.splitlines() if line.startswith("EnvironmentFile=")]
            self.assertEqual(files, suffixes)
            self.assertNotIn("EnvironmentFile=-/etc/utsa-gno-explorer/rpc.env", unit)
            self.assertNotRegex(unit, r"https?://")

        stale = {"GNO_RPC_URLS": "https://stale.example.invalid"}
        shared = {"GNO_RPC_URLS": "https://intended.example.invalid"}
        effective = {**stale, **shared}
        self.assertEqual(effective["GNO_RPC_URLS"], shared["GNO_RPC_URLS"])

    def test_shared_rpc_migration_documentation_contract(self):
        docs = self.text("docs/production-deployment.md")
        create_at = docs.index("deploy/systemd/rpc.env.example /etc/utsa-gno-explorer/rpc.env")
        reload_at = docs.index("sudo systemctl daemon-reload")
        self.assertLess(create_at, reload_at)
        self.assertIn("`root:utsa-gno` with mode `0640`", docs)
        self.assertIn("single operator-controlled static source", docs)
        self.assertIn("without printing", docs)

    def test_account_rpc_documentation_uses_shared_ownership(self):
        docs = self.text("docs/production-deployment.md")
        section = docs.split("#### Account API RPC configuration", 1)[1].split(
            "#### Network distribution API access prerequisite", 1,
        )[0]
        self.assertIn("/etc/utsa-gno-explorer/rpc.env", section)
        self.assertIn("single static source", section)
        self.assertIn("API_ACCOUNT_RPC_TIMEOUT_SECONDS=10", section)
        self.assertIn("/etc/utsa-gno-explorer/api.env", section)
        self.assertNotIn("receives its RPC configuration only", docs)
        self.assertNotIn("Add these public settings", section)
        self.assertNotIn("restart only the API", section)
        for service in (
            "utsa-gno-indexer.service",
            "utsa-gno-api.service",
            "utsa-gno-governance-updater.service",
        ):
            self.assertIn(f"sudo systemctl restart {service}", section)
        self.assertIn("oneshot/timer consumers", section)

    def test_read_only_api_documentation_includes_live_account_rpc_reads(self):
        docs = self.text("docs/production-deployment.md")
        section = docs.split("## Read-only API deployment", 1)[1].split(
            "### Create and verify the API database role", 1,
        )[0]
        self.assertNotIn("It reads PostgreSQL only; it does not call Gno RPC", docs)
        self.assertIn("PostgreSQL role is strictly read-only", section)
        self.assertIn("exposes no mutation endpoint", section)
        self.assertIn("bounded live read-only Gno RPC queries", section)
        self.assertIn("reads the canonical selected endpoint from", section)
        self.assertIn("never writes indexer or canonical RPC selection state", section)

    def test_manual_indexer_check_loads_shared_rpc_environment_last(self):
        docs = self.text("docs/production-deployment.md")
        command = next(
            line for line in docs.splitlines()
            if "scripts/run_indexer.py --once" in line
        )
        indexer_at = command.index(". /etc/utsa-gno-explorer/indexer.env")
        rpc_at = command.index(". /etc/utsa-gno-explorer/rpc.env")
        runner_at = command.index("scripts/run_indexer.py --once")
        self.assertLess(indexer_at, rpc_at)
        self.assertLess(rpc_at, runner_at)
        for forbidden in ("cat ", "grep ", "sed ", "printenv", "set -x"):
            self.assertNotIn(forbidden, command)

    def test_indexer_lifecycle_documents_both_required_environment_files(self):
        docs = self.text("docs/production-deployment.md")
        section = docs.split("## systemd lifecycle", 1)[1].split(
            "### Automatic Valopers profile refresh", 1,
        )[0]
        indexer_at = section.index("EnvironmentFile=/etc/utsa-gno-explorer/indexer.env")
        rpc_at = section.index("EnvironmentFile=/etc/utsa-gno-explorer/rpc.env")
        self.assertLess(indexer_at, rpc_at)
        self.assertIn("first", section[indexer_at - 100:rpc_at])
        self.assertIn("last", section[rpc_at:rpc_at + 100])

    def test_account_architecture_documentation_matches_canonical_preference(self):
        docs = self.text("docs/account-api.md")
        normalized = " ".join(docs.split())
        for value in (
            "bounded concurrent discovery",
            "15 seconds",
            "prefers the canonical endpoint",
            "latency advantage of a few milliseconds",
            "immediately uses the next request-local suitable fallback",
            "source.rpc_url",
            "read-only with respect to canonical RPC selection",
            "/etc/utsa-gno-explorer/rpc.env",
            "API_ACCOUNT_RPC_TIMEOUT_SECONDS",
            "never mixed between endpoints",
        ):
            self.assertIn(value, normalized)
        self.assertNotIn("should provide an ordered comma-separated `GNO_RPC_URLS`", docs)
        self.assertNotIn("`GNO_RPC_URLS` in `/etc/utsa-gno-explorer/api.env`", docs)

    def test_changed_documentation_has_no_credential_bearing_rpc_url(self):
        docs = self.text("docs/production-deployment.md") + self.text("docs/account-api.md")
        self.assertNotRegex(docs, r"https?://[^\s/]+:[^\s/@]+@")

    def test_compose_postgres_runtime_is_pinned_local_and_persistent(self):
        compose = self.text("deploy/postgres/compose.yml")
        self.assertIn("image: postgres:16.14-bookworm", compose)
        self.assertNotIn(":latest", compose)
        self.assertIn('"127.0.0.1:${POSTGRES_PORT:-5432}:5432"', compose)
        self.assertIn("source: ${POSTGRES_DATA_DIR:-/var/lib/utsa-gno-explorer/postgres}", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("pg_isready", compose)
        self.assertNotIn("git pull", compose)

    def test_compose_uses_external_password_file_and_no_real_secret(self):
        compose = self.text("deploy/postgres/compose.yml")
        example = self.text("deploy/postgres/postgres.env.example")
        self.assertIn("POSTGRES_PASSWORD_FILE", compose)
        self.assertIn("/etc/utsa-gno-explorer/postgres-password", compose)
        self.assertNotIn("POSTGRES_PASSWORD:", compose)
        self.assertIn("POSTGRES_DATA_DIR=/var/lib/utsa-gno-explorer/postgres", example)
        self.assertNotIn("postgres:16.4", compose)
        self.assertNotRegex(example, r"password|secret|token", msg="postgres example should not contain secret values")

    def test_systemd_unit_contains_expected_runtime_directives(self):
        unit = self.text("deploy/systemd/utsa-gno-indexer.service")
        expected = [
            "User=utsa-gno",
            "Group=utsa-gno",
            "WorkingDirectory=/opt/utsa-gno-explorer",
            "EnvironmentFile=/etc/utsa-gno-explorer/indexer.env",
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/python scripts/run_indexer.py",
            "Restart=on-failure",
            "KillSignal=SIGTERM",
            "TimeoutStopSec=180",
            "Wants=network-online.target docker.service",
            "After=network-online.target docker.service",
            "ExecStartPre=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/wait_for_postgres.py",
            "NoNewPrivileges=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ]
        for value in expected:
            self.assertIn(value, unit)
        self.assertNotIn("git pull", unit)
        self.assertNotIn("--start-height", unit)

    def test_governance_updater_service_and_single_scheduler_contract(self):
        unit_path = ROOT / "deploy/systemd/utsa-gno-governance-updater.service"
        self.assertTrue(unit_path.is_file())
        unit = unit_path.read_text()
        expected = ["Type=simple", "User=utsa-gno", "Group=utsa-gno",
            "WorkingDirectory=/opt/utsa-gno-explorer",
            "EnvironmentFile=/etc/utsa-gno-explorer/indexer.env",
            "ExecStartPre=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/wait_for_postgres.py --timeout 120 --retry-interval 2",
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/python scripts/run_governance_updater.py",
            "Restart=on-failure", "KillSignal=SIGTERM", "TimeoutStopSec=900",
            "NoNewPrivileges=true", "PrivateTmp=true", "ProtectHome=true",
            "ProtectSystem=strict", "PrivateDevices=true", "ProtectKernelTunables=true",
            "ProtectKernelModules=true", "ProtectControlGroups=true", "RestrictSUIDSGID=true",
            "LockPersonality=true", "UMask=0077", "CapabilityBoundingSet=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "WantedBy=multi-user.target"]
        for value in expected: self.assertIn(value, unit)
        self.assertFalse(list((ROOT / "deploy/systemd").glob("*governance*.timer")))

    def test_governance_updater_env_docs_and_no_automatic_activation(self):
        env = self.text("deploy/systemd/indexer.env.example")
        for value in ["GOVERNANCE_REFRESH_INTERVAL_SECONDS=30",
                      "GOVERNANCE_FULL_RECONCILE_INTERVAL_SECONDS=21600",
                      "GOVERNANCE_ERROR_BACKOFF_SECONDS=5", "GOVERNANCE_MAX_BACKOFF_SECONDS=60"]:
            self.assertIn(value, env)
        docs = self.text("docs/production-deployment.md") + self.text("docs/operator-runbook.md")
        self.assertIn("`utsa-gno-governance-updater.service`", docs)
        self.assertFalse(list((ROOT / "deploy/systemd").glob("*governance*.timer")))
        code = "\n".join(path.read_text() for path in (ROOT / "scripts").glob("*.py"))
        self.assertNotIn("systemctl enable --now utsa-gno-governance-updater", code)
        self.assertNotIn("crontab", docs.lower())

    def test_valopers_refresh_service_contract(self):
        unit = self.text("deploy/systemd/utsa-gno-valopers-refresh.service")
        expected = [
            "Type=oneshot",
            "User=utsa-gno",
            "Group=utsa-gno",
            "WorkingDirectory=/opt/utsa-gno-explorer",
            "EnvironmentFile=/etc/utsa-gno-explorer/indexer.env",
            "ExecStartPre=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/wait_for_postgres.py --timeout 120 --retry-interval 2",
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/persist_valopers_snapshot.py",
            "TimeoutStartSec=30m",
            "StandardOutput=journal",
            "StandardError=journal",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectHome=true",
            "ProtectSystem=strict",
            "PrivateDevices=true",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictSUIDSGID=true",
            "LockPersonality=true",
            "UMask=0077",
            "CapabilityBoundingSet=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ]
        for value in expected:
            self.assertIn(value, unit)
        self.assertNotIn("User=root", unit)
        self.assertNotIn("Group=root", unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("Restart=on-failure", unit)
        self.assertNotIn("probe_valopers_snapshot.py", unit)
        self.assertNotIn("run_indexer.py", unit)
        self.assertLess(unit.index("ExecStartPre="), unit.index("ExecStart="))

    def test_valopers_refresh_timer_contract(self):
        timer = self.text("deploy/systemd/utsa-gno-valopers-refresh.timer")
        expected = [
            "OnCalendar=hourly",
            "Persistent=true",
            "RandomizedDelaySec=5m",
            "AccuracySec=1m",
            "Unit=utsa-gno-valopers-refresh.service",
            "WantedBy=timers.target",
        ]
        for value in expected:
            self.assertIn(value, timer)
        self.assertEqual(timer.count("OnCalendar="), 1)
        self.assertNotIn("OnBootSec", timer)


    def test_compose_has_stable_project_name_with_override(self):
        compose = self.text("deploy/postgres/compose.yml")
        self.assertIn("name: ${COMPOSE_PROJECT_NAME:-utsa-gno-explorer}", compose)
        self.assertIn("COMPOSE_PROJECT_NAME", compose)
        self.assertLess(compose.index("name:"), compose.index("services:"))

    def test_backup_systemd_service_uses_absolute_production_paths(self):
        unit = self.text("deploy/systemd/utsa-gno-explorer-backup.service")
        self.assertIn("Type=oneshot", unit)
        self.assertIn("WorkingDirectory=/opt/utsa-gno-explorer", unit)
        self.assertIn("/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/backup_database.py", unit)
        self.assertIn("--backup-dir /var/backups/utsa-gno-explorer", unit)
        self.assertIn("--retention 3", unit)
        self.assertNotIn("--retention 14", unit)
        self.assertIn("--compose-file /opt/utsa-gno-explorer/deploy/postgres/compose.yml", unit)
        self.assertIn("--env-file /etc/utsa-gno-explorer/postgres.env", unit)
        self.assertIn("StandardOutput=journal", unit)
        self.assertIn("StandardError=journal", unit)
        self.assertNotIn("systemctl stop utsa-gno-indexer", unit)

    def test_backup_systemd_service_runs_as_root_with_restrictive_umask(self):
        unit = self.text("deploy/systemd/utsa-gno-explorer-backup.service")
        for value in ["User=root", "Group=root", "UMask=0077", "NoNewPrivileges=true", "ProtectSystem=strict", "ReadWritePaths=/var/backups/utsa-gno-explorer /run/utsa-gno-explorer-backup"]:
            self.assertIn(value, unit)
        self.assertNotIn("User=utsa-gno", unit)
        self.assertNotIn("SupplementaryGroups=docker", unit)


    def test_backup_systemd_service_uses_runtime_directory_for_docker_config(self):
        unit = self.text("deploy/systemd/utsa-gno-explorer-backup.service")
        lines = unit.splitlines()
        runtime = self._single_value(lines, "RuntimeDirectory")
        docker_config = self._single_value(lines, "Environment=DOCKER_CONFIG")

        self.assertEqual(runtime, "utsa-gno-explorer-backup")
        self.assertEqual(docker_config, "/run/utsa-gno-explorer-backup")
        self.assertEqual(docker_config, f"/run/{runtime}")
        self.assertIn("ProtectHome=true", lines)
        self.assertNotIn("/usr/libexec/docker/cli-plugins/docker-compose", unit)

    @staticmethod
    def _single_value(lines, key):
        prefix = f"{key}="
        matches = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
        if len(matches) != 1:
            raise AssertionError(f"Expected exactly one {key} entry, found {len(matches)}")
        return matches[0]

    def test_backup_installation_docs_create_root_only_backup_directory(self):
        install = self.text("docs/install.md")
        self.assertIn(
            "install -d -o root -g root -m 0700 /var/backups/utsa-gno-explorer",
            install,
        )
        self.assertLess(
            install.index("/var/backups/utsa-gno-explorer"),
            install.index("utsa-gno-explorer-backup.timer"),
        )

    def test_backup_systemd_timer_schedule_and_target(self):
        timer = self.text("deploy/systemd/utsa-gno-explorer-backup.timer")
        for value in ["OnCalendar=*-*-* 03:15:00 UTC", "Persistent=true", "RandomizedDelaySec=15m", "AccuracySec=1m", "Unit=utsa-gno-explorer-backup.service", "WantedBy=timers.target"]:
            self.assertIn(value, timer)

    def test_backup_systemd_command_does_not_contain_credentials(self):
        unit = self.text("deploy/systemd/utsa-gno-explorer-backup.service")
        exec_lines = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
        self.assertEqual(len(exec_lines), 1)
        self.assertNotRegex(exec_lines[0], r"(DATABASE_URL|PASSWORD|PGPASSWORD|postgresql://|://[^\s:]+:[^\s@]+@)")

    def test_example_indexer_env_uses_placeholders(self):
        env = self.text("deploy/systemd/indexer.env.example")
        self.assertIn("REPLACE_WITH_PASSWORD", env)
        self.assertIn("INDEXER_START_HEIGHT=1", env)
        self.assertNotIn("change-me", env)

    def test_gitignore_protects_secret_like_files_without_examples(self):
        ignore = self.text(".gitignore")
        self.assertIn("deploy/**/.env", ignore)
        self.assertIn("deploy/**/*password*", ignore)
        self.assertIn("*.local.env", ignore)
        self.assertNotRegex(ignore, r"^\*\.example$", msg="do not ignore committed example files")

    def test_documentation_uses_safe_compose_exec_commands(self):
        doc = self.text("docs/production-deployment.md")
        self.assertNotIn('psql "$DATABASE_URL"', doc)
        self.assertIn("exec postgres sh -c 'pg_isready -U", doc)
        self.assertIn("systemd-analyze verify", doc)
        self.assertIn("systemd-analyze security", doc)

    def test_restore_validation_documentation_fails_closed(self):
        doc = self.text("docs/production-deployment.md")
        self.assertIn("set -euo pipefail", doc)
        self.assertIn("trap cleanup_restore_validation EXIT", doc)
        self.assertIn("for attempt in $(seq 1 60)", doc)
        self.assertIn("--exit-on-error", doc)
        self.assertIn("--single-transaction", doc)
        self.assertIn("--no-owner", doc)
        self.assertIn("--no-privileges", doc)
        self.assertIn("POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password", doc)
        self.assertIn(":/run/secrets/postgres_password:ro", doc)
        self.assertIn("docker exec \"$VALIDATION_CONTAINER\" sh -c 'pg_isready", doc)
        self.assertIn("docker exec -i \"$VALIDATION_CONTAINER\" sh -c 'pg_restore", doc)
        self.assertIn("docker exec -i \"$VALIDATION_CONTAINER\" sh -c 'psql", doc)
        self.assertNotIn("PGPASSWORD=", doc)
        self.assertNotIn("POSTGRES_PASSWORD=validation", doc)
        self.assertNotIn("-e POSTGRES_PASSWORD=", doc)
        self.assertIn("RAISE EXCEPTION 'validation failed: expected exact legacy", doc)
        self.assertIn("RAISE EXCEPTION 'validation failed: checkpoint", doc)
        self.assertIn("secrets.token_urlsafe", doc)

    def test_restore_validation_accepts_only_exact_supported_catalogs(self):
        doc = self.text("docs/production-deployment.md")
        section = doc.split("## Validation restore", 1)[1].split("\n## ", 1)[0]
        legacy = "legacy_expected_tables text[] := ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators'];"
        current = "current_expected_tables text[] := ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators','valoper_profiles','valopers_snapshot_state'];"
        self.assertIn(legacy, section)
        self.assertIn(current, section)
        self.assertIn("actual_tables IS DISTINCT FROM legacy_expected_tables", section)
        self.assertIn("actual_tables IS DISTINCT FROM current_expected_tables", section)
        self.assertIn("AND actual_tables IS DISTINCT FROM current_expected_tables", section)
        self.assertNotIn("<@", section)
        self.assertNotIn("@>", section)
        self.assertNotIn("array_length", section)
        self.assertIn("either possible nine-table state", section)
        self.assertIn("partial catalog", section)

    def test_main_upgrade_runs_migration_before_validation_and_restart(self):
        doc = self.text("docs/production-deployment.md")
        section = doc.split("## Upgrade procedure", 1)[1].split("\n## ", 1)[0]
        migration = "python scripts/migrate_valopers_schema.py"
        validation = "python scripts/init_database.py"
        restart = "sudo systemctl start utsa-gno-indexer.service"
        self.assertIn(migration, section)
        self.assertIn(validation, section)
        self.assertIn(restart, section)
        self.assertLess(section.index(migration), section.index(validation))
        self.assertLess(section.index(validation), section.index(restart))

    def test_init_database_help_runs(self):
        result = subprocess.run([sys.executable, "scripts/init_database.py", "--help"], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--schema", result.stdout)

    def test_documentation_links_exist(self):
        for relative in ["README.md", "database/README.md", "docs/operator-runbook.md"]:
            self.assertIn("production-deployment.md", self.text(relative))
        self.assertTrue((ROOT / "docs/production-deployment.md").is_file())


class SchemaValidationTests(unittest.TestCase):
    def snapshot(self):
        return {
            "tables": set(init_database.EXPECTED_TABLES),
            "columns": {table: dict(columns) for table, columns in init_database.EXPECTED_COLUMNS.items()},
            "primary_keys": dict(init_database.EXPECTED_PRIMARY_KEYS),
            "unique_constraints": set(init_database.EXPECTED_UNIQUES),
            "foreign_keys": set(init_database.EXPECTED_FOREIGN_KEYS),
            "check_constraints": dict(init_database.EXPECTED_CHECKS),
            "indexes": dict(init_database.EXPECTED_INDEXES),
        }

    def test_compatible_schema_snapshot_passes(self):
        init_database.validate_schema_snapshot(self.snapshot())

    def test_empty_database_initialization_runs_schema_transactionally(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.snapshot = self_outer.snapshot()
            def execute(self, sql, params=None):
                self.calls.append(str(sql))
            def fetchone(self):
                return (False,)
            def fetchall(self):
                if "information_schema.tables" in self.calls[-1]:
                    return [] if len(self.calls) == 1 else [(t,) for t in self.snapshot["tables"]]
                if "information_schema.columns" in self.calls[-1]:
                    return [(t, c, v[0], v[1]) for t, cols in self.snapshot["columns"].items() for c, v in cols.items()]
                if "table_constraints" in self.calls[-1]:
                    rows = []
                    for t, cols in self.snapshot["primary_keys"].items():
                        rows += [(t, "PRIMARY KEY", f"{t}_pkey", c, None) for c in cols]
                    for t, cols in init_database.EXPECTED_UNIQUES:
                        rows += [(t, "UNIQUE", f"{t}_{c}_unique", c, None) for c in cols]
                    for t, cols, ref in init_database.EXPECTED_FOREIGN_KEYS:
                        rows += [(t, "FOREIGN KEY", f"{t}_fk", c, ref) for c in cols]
                    rows += [("blocks", "CHECK", c, None, None) for c in init_database.EXPECTED_CHECKS]
                    return rows
                if "pg_indexes" in self.calls[-1]:
                    return list(self.snapshot["indexes"].items())
                return []
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def __init__(self): self.cursor_obj = Cursor(); self.commits = 0
            def cursor(self): return self.cursor_obj
            def commit(self): self.commits += 1
            def __enter__(self): return self
            def __exit__(self, *a): return False
        self_outer = self
        conn = Conn()
        with tempfile.NamedTemporaryFile("w") as schema:
            schema.write("CREATE TABLE blocks(height bigint primary key);")
            schema.flush()
            with patch("scripts.init_database.fetch_schema_snapshot", return_value=self.snapshot()):
                init_database.initialize_or_validate("postgresql://user:secret@host/db", Path(schema.name), connect=lambda url: conn)
        self.assertEqual(conn.commits, 1)
        self.assertIn("CREATE TABLE blocks", "\n".join(conn.cursor_obj.calls))

    def test_missing_table_fails(self):
        snapshot = self.snapshot(); snapshot["tables"].remove("blocks")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_partial_schema_fails(self):
        snapshot = self.snapshot(); snapshot["tables"] = {"blocks", "transactions"}
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_column_type_fails(self):
        snapshot = self.snapshot(); snapshot["columns"]["blocks"]["height"] = ("integer", "NO", "", None)
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)



    def test_postgresql_formatted_check_definitions_are_normalized(self):
        snapshot = self.snapshot()
        snapshot["check_constraints"]["transactions_decode_status_check"] = "CHECK ((decode_status = ANY (ARRAY['decoded'::text, 'invalid_base64'::text, 'not_attempted'::text])))"
        snapshot["check_constraints"]["indexer_state_default_key"] = "CHECK ((state_key = 'default'::text))"
        snapshot["check_constraints"]["validator_set_members_voting_power_check"] = "CHECK ((voting_power >= (0)::numeric))"
        init_database.validate_schema_snapshot(snapshot)


    def test_postgresql_16_check_expression_fixtures_are_normalized(self):
        snapshot = self.snapshot()
        snapshot["check_constraints"]["transactions_decoded_byte_length_check"] = "((decoded_byte_length IS NULL) OR (decoded_byte_length >= 0))"
        snapshot["check_constraints"]["transactions_decode_status_check"] = "(decode_status = ANY (ARRAY['decoded'::text, 'invalid_base64'::text, 'not_attempted'::text]))"
        snapshot["check_constraints"]["transactions_decode_status_consistent"] = "(((decode_status = 'decoded'::text) AND (decoded_bytes IS NOT NULL) AND (decoded_byte_length = octet_length(decoded_bytes))) OR ((decode_status = ANY (ARRAY['invalid_base64'::text, 'not_attempted'::text])) AND (decoded_bytes IS NULL) AND (decoded_byte_length IS NULL)))"
        snapshot["check_constraints"]["validator_signatures_nil_vote_consistent"] = "((vote_status <> 'nil'::text) OR ((NOT signed) AND vote_block_id_is_zero AND (NOT block_id_matches_commit)))"
        snapshot["check_constraints"]["rpc_endpoints_no_secret_url"] = "(url !~* '(password|token|apikey|api_key|secret)='::text)"
        snapshot["check_constraints"]["validators_last_seen_height_check"] = "(last_seen_height >= first_seen_height)"
        init_database.validate_schema_snapshot(snapshot)

    def test_incompatible_check_diagnostic_includes_expected_and_actual(self):
        snapshot = self.snapshot()
        snapshot["check_constraints"]["transactions_decoded_byte_length_check"] = "CHECK (true)"
        with self.assertRaisesRegex(
            init_database.SchemaCompatibilityError,
            r"transactions_decoded_byte_length_check: expected=.*actual=",
        ):
            init_database.validate_schema_snapshot(snapshot)

    def test_check_constraint_true_with_correct_name_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"]["blocks_tx_count_check"] = "CHECK (true)"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_changed_transactions_decode_status_consistent_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"]["transactions_decode_status_consistent"] = "CHECK (decode_status IN ('decoded', 'invalid_base64', 'not_attempted'))"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_changed_validator_signatures_commit_consistency_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"]["validator_signatures_commit_vote_consistent"] = "CHECK (vote_status <> 'commit' OR block_id_matches_commit)"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_changed_rpc_endpoint_no_secret_check_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"]["rpc_endpoints_no_secret_url"] = "CHECK (url !~* '(password)=')"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_missing_constraint_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"].pop("indexer_state_default_key")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_index_definition_fails(self):
        snapshot = self.snapshot(); snapshot["indexes"]["rpc_endpoints_one_selected_per_chain_idx"] = ("rpc_endpoints", False, (("chain_id", "ASC"),), None)
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)


    def test_pg_catalog_introspection_preserves_composite_constraints(self):
        snapshot = self.snapshot()
        class CatalogCursor:
            def __init__(self):
                self.calls = 0
            def execute(self, sql):
                self.calls += 1
            def fetchall(self):
                if self.calls == 1:
                    return [(table,) for table in sorted(snapshot["tables"])]
                if self.calls == 2:
                    return [
                        (table, column, values[0], values[1], values[2], values[3])
                        for table, cols in snapshot["columns"].items()
                        for column, values in cols.items()
                    ]
                if self.calls == 3:
                    rows = []
                    oid = 1
                    for table, cols in snapshot["primary_keys"].items():
                        rows.append((oid, table, "p", f"{table}_pkey", list(cols), None, [], " ", "PRIMARY KEY (" + ", ".join(cols) + ")")); oid += 1
                    for table, cols in snapshot["unique_constraints"]:
                        rows.append((oid, table, "u", f"{table}_{'_'.join(cols)}_key", list(cols), None, [], " ", "UNIQUE (" + ", ".join(cols) + ")")); oid += 1
                    for table, cols, ref_table, ref_cols, action in snapshot["foreign_keys"]:
                        rows.append((oid, table, "f", f"{table}_{'_'.join(cols)}_fkey", list(cols), ref_table, list(ref_cols), action, "FOREIGN KEY")); oid += 1
                    for name, definition in snapshot["check_constraints"].items():
                        rows.append((oid, "blocks", "c", name, [], None, [], " ", definition)); oid += 1
                    return rows
                if self.calls == 4:
                    return [
                        (name, table, unique, [column for column, _ in columns], [direction for _, direction in columns], predicate)
                        for name, (table, unique, columns, predicate) in snapshot["indexes"].items()
                    ]
                return []
        fetched = init_database.fetch_schema_snapshot(CatalogCursor())
        self.assertEqual(fetched["primary_keys"]["validator_set_members"], ("height", "signing_address"))
        self.assertEqual(fetched["primary_keys"]["validator_signatures"], ("height", "signing_address"))
        self.assertIn(("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "c"), fetched["foreign_keys"])
        self.assertIn(("transactions", ("block_height", "tx_index")), fetched["unique_constraints"])
        self.assertIn(("validators", ("public_key_type", "public_key_value")), fetched["unique_constraints"])
        init_database.validate_schema_snapshot(fetched)

    def test_unexpected_extra_table_fails(self):
        snapshot = self.snapshot(); snapshot["tables"].add("surprise")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_check_definition_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"]["indexer_state_default_key"] = "CHECK ((state_key <> 'default'::text))"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_foreign_key_action_fails(self):
        snapshot = self.snapshot(); snapshot["foreign_keys"].remove(("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "c")); snapshot["foreign_keys"].add(("validator_signatures", ("height", "signing_address"), "validator_set_members", ("height", "signing_address"), "r"))
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_partial_index_predicate_fails(self):
        snapshot = self.snapshot(); snapshot["indexes"]["rpc_endpoints_one_selected_per_chain_idx"] = ("rpc_endpoints", True, (("chain_id", "ASC"),), "healthy")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_init_database_does_not_use_subprocess_argv_for_database_url(self):
        self.assertNotIn("subprocess", Path("scripts/init_database.py").read_text())


    def test_compatible_existing_schema_executes_no_create(self):
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, sql, params=None): self.calls.append(str(sql))
            def fetchall(self): return [("blocks",)] if len(self.calls) == 1 else []
            def fetchone(self): return (False,)
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def __init__(self): self.cursor_obj = Cursor(); self.commits = 0
            def cursor(self): return self.cursor_obj
            def commit(self): self.commits += 1
            def __enter__(self): return self
            def __exit__(self, *a): return False
        conn = Conn()
        with patch("scripts.init_database.fetch_schema_snapshot", return_value=self.snapshot()):
            init_database.initialize_or_validate("postgresql://safe", connect=lambda url: conn)
        self.assertEqual(conn.commits, 1)
        self.assertFalse(any("CREATE TABLE" in call for call in conn.cursor_obj.calls))

    def test_schema_sql_failure_rolls_back_by_not_committing(self):
        class Cursor:
            def execute(self, sql):
                if "CREATE TABLE" in sql:
                    raise RuntimeError("sql failed")
            def fetchall(self): return []
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def __init__(self): self.committed = False
            def cursor(self): return Cursor()
            def commit(self): self.committed = True
            def __enter__(self): return self
            def __exit__(self, *a): return False
        conn = Conn()
        with tempfile.NamedTemporaryFile("w") as schema:
            schema.write("CREATE TABLE broken();")
            schema.flush()
            with self.assertRaises(RuntimeError):
                init_database.initialize_or_validate("postgresql://safe", Path(schema.name), connect=lambda url: conn)
        self.assertFalse(conn.committed)

    def test_post_create_validation_failure_rolls_back_by_not_committing(self):
        class Cursor:
            def execute(self, sql): pass
            def fetchall(self): return []
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def __init__(self): self.committed = False
            def cursor(self): return Cursor()
            def commit(self): self.committed = True
            def __enter__(self): return self
            def __exit__(self, *a): return False
        conn = Conn()
        with tempfile.NamedTemporaryFile("w") as schema:
            schema.write("CREATE TABLE blocks(height bigint primary key);")
            schema.flush()
            with patch("scripts.init_database.fetch_schema_snapshot", return_value={"tables": {"blocks"}}), self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.initialize_or_validate("postgresql://safe", Path(schema.name), connect=lambda url: conn)
        self.assertFalse(conn.committed)

    def test_init_database_main_sanitizes_error_output(self):
        err = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:secret@host/db"}, clear=True), patch("scripts.init_database.initialize_or_validate", side_effect=RuntimeError("failed postgresql://user:secret@host/db")), contextlib.redirect_stderr(err):
            code = init_database.main([])
        self.assertEqual(code, 1)
        self.assertNotIn("secret", err.getvalue())

    def test_missing_database_url_is_concise(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL is required"):
            init_database.initialize_or_validate("")


class BackupScriptTests(unittest.TestCase):
    def test_parser_defaults_to_three_backups(self):
        self.assertEqual(backup_database.build_parser().parse_args([]).retention, 3)

    def test_backup_filename_uses_utc_timestamp(self):
        name = backup_database.backup_filename(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(name, "utsa-gno-explorer-20260715T010203Z.dump")
        self.assertRegex(name, backup_database.BACKUP_RE)

    def test_backup_command_construction_uses_expected_flags(self):
        dump = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "sh", "-c", "pg_dump -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Fc --no-owner --no-privileges")
        restore = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "pg_restore", "--list")
        self.assertIn("--no-owner", dump[-1])
        self.assertIn("--no-privileges", dump[-1])
        self.assertEqual(restore[-2:], ["pg_restore", "--list"])
        self.assertNotIn("-", restore)

    def test_negative_retention_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            with self.assertRaises(ValueError):
                backup_database.create_backup(directory, compose_file, env_file, retention=-1)

    def test_successful_backup_renames_part_and_applies_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            old.write_bytes(b"old")
            unrelated = directory / "notes.txt"
            unrelated.write_text("keep")

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                if "pg_dump" in " ".join(command):
                    stdout.write(b"archive")
                return type("Result", (), {"returncode": 0})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                final = backup_database.create_backup(directory, compose_file, env_file, retention=1)

            self.assertTrue(final.exists())
            self.assertFalse(final.with_suffix(final.suffix + ".part").exists())
            self.assertFalse(old.exists())
            self.assertTrue(unrelated.exists())

    def test_failed_dump_removes_part_without_final_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            old.write_bytes(b"old")

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                return type("Result", (), {"returncode": 1})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    backup_database.create_backup(directory, compose_file, env_file, retention=1)
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump").exists())
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump.part").exists())
            self.assertTrue(old.exists())


    def test_failed_archive_validation_removes_part_without_final_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            old.write_bytes(b"old")
            calls = []
            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                calls.append(command)
                if "pg_dump" in " ".join(command):
                    stdout.write(b"archive")
                    return type("Result", (), {"returncode": 0})()
                return type("Result", (), {"returncode": 1})()
            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    backup_database.create_backup(directory, compose_file, env_file, retention=1)
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump").exists())
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump.part").exists())
            self.assertTrue(old.exists())

    def test_retention_keeps_three_newest_and_ignores_recovery_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            second = directory / "utsa-gno-explorer-20260201T000000Z.dump"
            third = directory / "utsa-gno-explorer-20260301T000000Z.dump"
            newest = directory / "utsa-gno-explorer-20260715T010203Z.dump"
            symlink = directory / "utsa-gno-explorer-20260401T000000Z.dump"
            unrelated = directory / "utsa-gno-explorer-not-a-date.dump"
            manual = directory / "utsa-gno-explorer-test13-recovery.dump"
            part = directory / "utsa-gno-explorer-20260501T000000Z.dump.part"
            checksum = directory / "utsa-gno-explorer-20260101T000000Z.dump.sha256"
            subdirectory = directory / "utsa-gno-explorer-20200101T000000Z.dump"
            subdirectory.mkdir()
            for path in (old, second, third, newest, unrelated, manual, part, checksum):
                path.write_text("keep")
            newest.write_text("new")
            symlink.symlink_to(old)
            backup_database.apply_retention(directory, keep=3, newest=newest)
            self.assertFalse(old.exists())
            self.assertTrue(second.exists())
            self.assertTrue(third.exists())
            self.assertTrue(newest.exists())
            for path in (unrelated, manual, part, checksum, subdirectory):
                self.assertTrue(path.exists())
            self.assertTrue(symlink.is_symlink(), "symlinks must not count as successful backups")

    def test_zero_retention_disables_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            backups = [directory / f"utsa-gno-explorer-20260{month}01T000000Z.dump" for month in range(1, 5)]
            for backup in backups:
                backup.write_text("keep")
            backup_database.apply_retention(directory, keep=0, newest=backups[-1])
            self.assertTrue(all(backup.exists() for backup in backups))


class WaitForPostgresTests(unittest.TestCase):
    def setUp(self):
        wait_for_postgres._STOP = False

    def test_success_does_not_print_database_url(self):
        calls = []

        class Conn:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def connect(url, connect_timeout):
            calls.append((url, connect_timeout))
            return Conn()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = wait_for_postgres.wait_for_postgres("postgresql://user:secret@localhost/db", 1, 1, connect=connect)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", out.getvalue())

    def test_retry_then_success_without_real_sleep(self):
        attempts = []
        times = iter([0, 0, 0.1])

        def connect(url, connect_timeout):
            attempts.append(url)
            if len(attempts) == 1:
                raise RuntimeError("not yet")
            return contextlib.nullcontext()

        ok = wait_for_postgres.wait_for_postgres("postgresql://safe", 5, 1, connect=connect, sleep=lambda _: None, monotonic=lambda: next(times, 0.2))
        self.assertTrue(ok)
        self.assertEqual(len(attempts), 2)

    def test_permanent_configuration_error_does_not_retry(self):
        attempts = []
        err = io.StringIO()
        class ProgrammingError(Exception): pass
        def connect(*args, **kwargs):
            attempts.append(1)
            raise ProgrammingError("invalid dsn contains secret")
        with contextlib.redirect_stderr(err):
            ok = wait_for_postgres.wait_for_postgres("postgresql://user:secret@localhost/db", 60, 1, connect=connect, sleep=lambda _: None)
        self.assertFalse(ok)
        self.assertEqual(len(attempts), 1)
        self.assertNotIn("secret", err.getvalue())

    def test_timeout_sanitizes_output(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ok = wait_for_postgres.wait_for_postgres(
                "postgresql://user:secret@localhost/db",
                0,
                1,
                connect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                sleep=lambda _: None,
                monotonic=lambda: 0,
            )
        self.assertFalse(ok)
        self.assertNotIn("secret", err.getvalue())
        self.assertIn("timed out", err.getvalue())

    def test_interrupted_wait_returns_false(self):
        wait_for_postgres._STOP = True
        self.assertFalse(wait_for_postgres.wait_for_postgres("postgresql://safe", 1, 1, connect=lambda *a, **k: contextlib.nullcontext(), sleep=lambda _: None))


if __name__ == "__main__":
    unittest.main()

class NetworkDistributionDeploymentAssetTests(unittest.TestCase):
    def test_network_distribution_service_and_timer_contract(self):
        service = (ROOT / "deploy/systemd/utsa-gno-network-distribution.service").read_text()
        timer = (ROOT / "deploy/systemd/utsa-gno-network-distribution.timer").read_text()
        for value in ["Type=oneshot", "User=utsa-gno", "Group=utsa-gno", "EnvironmentFile=/etc/utsa-gno-explorer/indexer.env", "EnvironmentFile=-/etc/utsa-gno-explorer/network-distribution.env", "wait_for_postgres.py", "NoNewPrivileges=true", "ProtectSystem=strict", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"]:
            self.assertIn(value, service)
        for value in ["OnCalendar=*:0/15", "Persistent=true", "RandomizedDelaySec=1m", "AccuracySec=1m"]:
            self.assertIn(value, timer)
        self.assertNotIn("systemctl enable", service + timer)
