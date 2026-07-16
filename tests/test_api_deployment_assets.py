import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "deploy/systemd/api.env.example"
UNIT_PATH = ROOT / "deploy/systemd/utsa-gno-api.service"
DOC_PATH = ROOT / "docs/production-deployment.md"


POSTGRES_URL = re.compile(rb"postgres(?:ql)?://[^\s\"<>]+")
PLACEHOLDER_PASSWORDS = {b"password", b"secret", b"super-secret-password", b"change-me"}


def credential_passwords(data):
    """Return passwords from bounded, single-token PostgreSQL URLs."""
    passwords = []
    for match in POSTGRES_URL.finditer(data):
        authority = match.group().split(b"://", 1)[1].split(b"/", 1)[0]
        userinfo, separator, _host = authority.rpartition(b"@")
        if separator and b":" in userinfo:
            passwords.append(userinfo.split(b":", 1)[1])
    return passwords


def is_placeholder_password(password):
    lowered = password.lower()
    return (
        lowered in PLACEHOLDER_PASSWORDS
        or b"replace" in lowered
        or b"placeholder" in lowered
        or (lowered.startswith(b"{") and lowered.endswith(b"}"))
    )


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
        self.assertNotIn("8000", self.unit)
        self.assertNotIn("0.0.0.0", self.unit)
        exec_start = next(
            line for line in self.unit.splitlines() if line.startswith("ExecStart=")
        )
        expected = (
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/uvicorn api.app:app "
            "--host ${API_BIND_HOST} --port ${API_BIND_PORT} --workers 1 "
            "--log-level ${API_LOG_LEVEL} --no-access-log"
        )
        self.assertEqual(exec_start, expected)
        self.assertNotIn("python -m uvicorn", exec_start)
        self.assertIn("--host ${API_BIND_HOST}", exec_start)
        self.assertIn("--port ${API_BIND_PORT}", exec_start)
        self.assertIn("--workers 1", exec_start)
        self.assertIn("--log-level ${API_LOG_LEVEL}", exec_start)
        self.assertNotIn("--reload", exec_start)

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

    def test_documentation_normalizes_and_verifies_service_permissions(self):
        self.assertIn("chown -R root:utsa-gno", self.documentation)
        self.assertIn("chmod -R u=rwX,g=rX,o=", self.documentation)
        for path in [".venv", "api", "scripts"]:
            self.assertIn(f"/opt/utsa-gno-explorer/{path}", self.documentation)
        self.assertIn("scripts/wait_for_postgres.py", self.documentation)
        self.assertIn("sudo -u utsa-gno test -r", self.documentation)
        self.assertIn("/opt/utsa-gno-explorer/.venv/bin/uvicorn", self.documentation)
        self.assertIn(r"\( -type f -o -type d \) -perm -g+w -print", self.documentation)
        self.assertNotIn("find -L", self.documentation)
        self.assertNotRegex(self.documentation, r"chmod[^\n]*(?:g\+w|g=rw)")

    def test_documented_updates_run_as_root(self):
        for command in [
            "sudo git -C /opt/utsa-gno-explorer fetch origin",
            "sudo git -C /opt/utsa-gno-explorer switch main",
            "sudo git -C /opt/utsa-gno-explorer merge --ff-only origin/main",
            "sudo /opt/utsa-gno-explorer/.venv/bin/python",
        ]:
            self.assertIn(command, self.documentation)
        self.assertIn("-r /opt/utsa-gno-explorer/requirements.txt", self.documentation)

    def test_credential_parser_rejects_common_uri_password_characters(self):
        prefix = b"postgresql://api_user:"
        suffix = b"@127.0.0.1:5432/explorer"
        for password in [b"real+password", b"real!password"]:
            parsed = credential_passwords(prefix + password + suffix)
            self.assertEqual(parsed, [password])
            self.assertFalse(is_placeholder_password(parsed[0]))

    def test_tracked_files_contain_no_embedded_real_url_password(self):
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
        )
        for relative in result.stdout.split(b"\0"):
            if not relative:
                continue
            data = (ROOT / relative.decode()).read_bytes()
            for password in credential_passwords(data):
                self.assertTrue(
                    is_placeholder_password(password),
                    f"possible real credential in {relative.decode()}",
                )


if __name__ == "__main__":
    unittest.main()
