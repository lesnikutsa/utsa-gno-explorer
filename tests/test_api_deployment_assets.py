import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "deploy/systemd/api.env.example"
UNIT_PATH = ROOT / "deploy/systemd/utsa-gno-api.service"
DOC_PATH = ROOT / "docs/production-deployment.md"


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
        self.assertIn("--host ${API_BIND_HOST}", self.unit)
        self.assertIn("--port ${API_BIND_PORT}", self.unit)
        self.assertIn("--workers 1", self.unit)
        self.assertNotIn("--reload", self.unit)

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

    def test_tracked_files_contain_no_embedded_real_url_password(self):
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
        )
        credential_url = re.compile(rb"postgres(?:ql)?://[A-Za-z0-9_.~-]+:([A-Za-z0-9_.~%-]+)@[A-Za-z0-9.-]+(?=[:/])")
        for relative in result.stdout.split(b"\0"):
            if not relative:
                continue
            data = (ROOT / relative.decode()).read_bytes()
            for match in credential_url.finditer(data):
                password = match.group(1)
                self.assertTrue(
                    any(marker in password.lower() for marker in [b"replace", b"placeholder", b"password", b"secret", b"change-me"]),
                    f"possible real credential in {relative.decode()}",
                )


if __name__ == "__main__":
    unittest.main()
