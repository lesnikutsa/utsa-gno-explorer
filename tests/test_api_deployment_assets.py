import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "deploy/systemd/api.env.example"
UNIT_PATH = ROOT / "deploy/systemd/utsa-gno-api.service"
DOC_PATH = ROOT / "docs/production-deployment.md"
CREDENTIAL_URL = re.compile(
    rb"postgres(?:ql)?://[A-Za-z0-9_.~-]+:([^@\s]+)@[^\s/]+"
)
PLACEHOLDER_PASSWORDS = {
    b"password",
    b"secret",
    b"super-secret-password",
    b"change-me",
    b"REPLACE_WITH_PASSWORD",
    b"REPLACE_WITH_URL_SAFE_PASSWORD",
    b"{cls.password}",
    b"{self.password}",
}


class ApiDeploymentAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = ENV_PATH.read_text()
        cls.unit = UNIT_PATH.read_text()
        cls.documentation = DOC_PATH.read_text()

    def test_environment_example_exists_and_has_safe_defaults(self):
        self.assertTrue(ENV_PATH.is_file())
        self.assertIn("REPLACE_WITH_URL_SAFE_PASSWORD", self.environment)
        self.assertIn("API_BIND_HOST=127.0.0.1", self.environment)
        self.assertIn("API_BIND_PORT=18180", self.environment)
        self.assertNotIn("GNO_RPC_URLS", self.environment)

    def test_unit_uses_external_bind_configuration_and_one_worker(self):
        expected_exec_start = (
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/uvicorn api.app:app "
            "--host ${API_BIND_HOST} --port ${API_BIND_PORT} --workers 1 "
            "--log-level ${API_LOG_LEVEL} --no-access-log"
        )
        self.assertIn(expected_exec_start, self.unit.splitlines())
        self.assertNotIn("python -m uvicorn", self.unit)
        self.assertNotIn("8000", self.unit)
        self.assertNotIn("0.0.0.0", self.unit)
        self.assertIn("--host ${API_BIND_HOST}", self.unit)
        self.assertIn("--port ${API_BIND_PORT}", self.unit)
        self.assertIn("--workers 1", self.unit)
        self.assertNotIn("--reload", self.unit)
        self.assertIn("${API_LOG_LEVEL}", self.unit)

    def test_unit_uses_unprivileged_identity_and_external_environment(self):
        self.assertIn("User=utsa-gno", self.unit)
        self.assertIn("Group=utsa-gno", self.unit)
        self.assertNotIn("User=root", self.unit)
        self.assertIn("EnvironmentFile=/etc/utsa-gno-explorer/api.env", self.unit)

    def test_unit_has_readiness_restart_and_hardening(self):
        expected = [
            "ExecStartPre=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/wait_for_postgres.py --timeout 120 --retry-interval 2",
            "Restart=on-failure", "NoNewPrivileges=true", "PrivateTmp=true",
            "ProtectHome=true", "ProtectSystem=strict", "PrivateDevices=true",
            "ProtectKernelTunables=true", "ProtectKernelModules=true",
            "ProtectControlGroups=true", "RestrictSUIDSGID=true",
            "LockPersonality=true", "UMask=0077", "CapabilityBoundingSet=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ]
        for directive in expected:
            self.assertIn(directive, self.unit)

    def test_unit_performs_no_shell_deployment_or_database_management(self):
        lowered = self.unit.lower()
        for forbidden in ["/bin/sh", "bash", "eval", "git pull", "init_database", "migrate", "gunicorn"]:
            self.assertNotIn(forbidden, lowered)

    def test_documentation_defines_restricted_separate_role(self):
        self.assertIn("CREATE ROLE utsa_gno_api LOGIN", self.documentation)
        self.assertIn("default_transaction_read_only", self.documentation)
        self.assertRegex(self.documentation, r"GRANT SELECT\s+ON ALL TABLES")
        self.assertIn("the `UPDATE` check to be `false`", self.documentation)
        self.assertNotRegex(self.documentation, r"(?i)ufw\s+allow\s+18180")

    def test_documentation_uses_correct_container_psql_quoting(self):
        command = "sh -c 'psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\"'"
        self.assertIn(command, self.documentation)
        self.assertNotIn(r'\"$POSTGRES_USER\"', self.documentation)
        self.assertNotIn(r'\"$POSTGRES_DB\"', self.documentation)

    def test_documentation_defines_read_only_runtime_permissions(self):
        for path in [".venv", "api", "scripts"]:
            self.assertIn(f"/opt/utsa-gno-explorer/{path}", self.documentation)
        self.assertIn("sudo chown -R root:utsa-gno", self.documentation)
        self.assertIn("sudo chmod -R u=rwX,g=rX,o=", self.documentation)
        self.assertNotIn("g=rwX", self.documentation)
        self.assertIn("-type f -perm /g=w", self.documentation)
        self.assertIn("-type d -perm /g=w", self.documentation)

    def test_documentation_uses_root_owned_api_update(self):
        expected_commands = [
            "sudo git -C /opt/utsa-gno-explorer fetch origin",
            "sudo git -C /opt/utsa-gno-explorer switch main",
            "sudo git -C /opt/utsa-gno-explorer merge --ff-only origin/main",
            "sudo /opt/utsa-gno-explorer/.venv/bin/python \\",
            "-r /opt/utsa-gno-explorer/requirements.txt",
        ]
        for command in expected_commands:
            self.assertIn(command, self.documentation)

    def api_070_upgrade_section(self):
        start = self.documentation.index("#### API 0.7.0 Valopers identity upgrade")
        end = self.documentation.index("For rollback,", start)
        return self.documentation[start:end]

    def test_api_070_upgrade_grants_only_required_profile_select(self):
        section = self.api_070_upgrade_section()
        grant = "GRANT SELECT ON TABLE public.valoper_profiles TO utsa_gno_api;"
        self.assertIn(grant, section)
        self.assertNotIn("GRANT SELECT ON TABLE public.valopers_snapshot_state", section)
        self.assertNotRegex(section, r"(?i)GRANT\s+ALL\s+(?:ON|;)")
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.assertNotIn(f"GRANT {privilege}", section)
        self.assertIn("role remains read-only", section)

    def test_api_070_upgrade_verifies_privileges_before_restart(self):
        section = self.api_070_upgrade_section()
        grant_at = section.index(
            "GRANT SELECT ON TABLE public.valoper_profiles TO utsa_gno_api;"
        )
        verification_at = section.index("DO $$")
        version_at = section.index("API_VERSION=0.7.0")
        restart_at = section.index("sudo systemctl restart utsa-gno-api.service")
        self.assertLess(grant_at, verification_at)
        self.assertLess(verification_at, version_at)
        self.assertLess(version_at, restart_at)
        normalized = " ".join(section.split())
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.assertIn(
                f"'public.valoper_profiles', '{privilege}'",
                normalized,
            )
        self.assertIn("Stop the deployment before restart", normalized)

    def test_api_070_upgrade_loads_schema_environment_and_fails_closed(self):
        section = self.api_070_upgrade_section()
        source_at = section.index(". /etc/utsa-gno-explorer/indexer.env")
        init_at = section.index("exec .venv/bin/python scripts/init_database.py")
        grant_at = section.index(
            "GRANT SELECT ON TABLE public.valoper_profiles TO utsa_gno_api;"
        )
        self.assertLess(source_at, init_at)
        self.assertLess(init_at, grant_at)
        validation = section[source_at:grant_at]
        self.assertNotIn("api.env", validation)
        self.assertNotRegex(validation, r"DATABASE_URL\s*=")

        verification_at = section.index("DO $$")
        version_at = section.index("API_VERSION=0.7.0")
        restart_at = section.index("sudo systemctl restart utsa-gno-api.service")
        self.assertIn("ON_ERROR_STOP=1", section[:verification_at])
        self.assertIn("RAISE EXCEPTION", section[verification_at:version_at])
        self.assertLess(grant_at, verification_at)
        self.assertLess(verification_at, version_at)
        self.assertLess(version_at, restart_at)
        self.assertIn(
            "has_table_privilege(\n       'utsa_gno_api', 'public.valopers_snapshot_state', 'SELECT'",
            section[verification_at:version_at],
        )

    def test_api_070_unmatched_smoke_check_is_conditional_and_non_mutating(self):
        section = self.api_070_upgrade_section()
        smoke = section[section.index("9. When at least one matched profile exists"):]
        self.assertIn("If one currently exists", smoke)
        self.assertIn("If every active validator currently has a profile", smoke)
        self.assertIn("Never create or modify production rows", smoke)
        self.assertNotRegex(smoke, r"(?i)\b(?:INSERT|UPDATE|DELETE|TRUNCATE)\b")

    def assert_urls_have_placeholder_passwords(self, data):
        for match in CREDENTIAL_URL.finditer(data):
            self.assertIn(match.group(1), PLACEHOLDER_PASSWORDS)

    def test_credential_url_scanning_handles_common_uri_password_characters(self):
        for password in [b"real+" + b"password", b"real!" + b"password"]:
            with self.subTest(password=password):
                with self.assertRaises(AssertionError):
                    self.assert_urls_have_placeholder_passwords(
                        b"postgresql://user:" + password + b"@db.internal:5432/database"
                    )

    def test_credential_url_scanning_allows_known_placeholders(self):
        for password in PLACEHOLDER_PASSWORDS:
            with self.subTest(password=password):
                self.assert_urls_have_placeholder_passwords(
                    b"postgresql://user:" + password + b"@localhost:5432/database"
                )

    def test_tracked_files_contain_no_embedded_real_url_password(self):
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
        )
        for relative in result.stdout.split(b"\0"):
            if not relative:
                continue
            data = (ROOT / relative.decode()).read_bytes()
            try:
                self.assert_urls_have_placeholder_passwords(data)
            except AssertionError as error:
                raise AssertionError(
                    f"possible real credential in {relative.decode()}"
                ) from error


if __name__ == "__main__":
    unittest.main()
