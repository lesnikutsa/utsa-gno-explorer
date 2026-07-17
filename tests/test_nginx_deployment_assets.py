import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "deploy/nginx/exp.gno.utsa.tech.bootstrap.conf"
FINAL_PATH = ROOT / "deploy/nginx/exp.gno.utsa.tech.conf"
DOCS_PATH = ROOT / "docs/production-deployment.md"


class NginxDeploymentAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.final = FINAL_PATH.read_text(encoding="utf-8")
        cls.docs = DOCS_PATH.read_text(encoding="utf-8")

    def test_assets_exist(self):
        self.assertTrue(BOOTSTRAP_PATH.is_file())
        self.assertTrue(FINAL_PATH.is_file())

    def test_server_names_are_isolated(self):
        for content in (self.bootstrap, self.final):
            names = re.findall(r"^\s*server_name\s+([^;]+);", content, re.MULTILINE)
            self.assertTrue(names)
            self.assertEqual(set(names), {"exp.gno.utsa.tech"})
            self.assertNotRegex(content, r"server_name\s+exp\.utsa\.tech(?:\s|;)")

    def test_bootstrap_is_http_acme_only(self):
        self.assertRegex(self.bootstrap, r"(?m)^\s*listen 80;")
        self.assertRegex(self.bootstrap, r"(?m)^\s*listen \[::\]:80;")
        self.assertIn("/.well-known/acme-challenge/", self.bootstrap)
        self.assertIn("root /var/www/letsencrypt;", self.bootstrap)
        self.assertRegex(self.bootstrap, r"location /\s*\{\s*return 404;", re.DOTALL)
        self.assertNotIn("ssl_certificate", self.bootstrap)
        self.assertNotIn("proxy_pass", self.bootstrap)

    def test_final_http_and_https_listeners_and_certificate_paths(self):
        for directive in (
            "listen 80;",
            "listen [::]:80;",
            "listen 443 ssl http2;",
            "listen [::]:443 ssl http2;",
            "ssl_certificate /etc/letsencrypt/live/exp.gno.utsa.tech/fullchain.pem;",
            "ssl_certificate_key /etc/letsencrypt/live/exp.gno.utsa.tech/privkey.pem;",
            "ssl_trusted_certificate /etc/letsencrypt/live/exp.gno.utsa.tech/chain.pem;",
            "ssl_protocols TLSv1.2 TLSv1.3;",
            "ssl_session_timeout 1d;",
            "ssl_session_cache shared:UTSA_GNO_EXPLORER_SSL:10m;",
            "ssl_session_tickets off;",
        ):
            self.assertIn(directive, self.final)
        self.assertNotIn("include snippets/ssl-params.conf;", self.final)
        self.assertNotIn("add_header Strict-Transport-Security", self.final)
        self.assertNotIn("ssl_ciphers", self.final)
        self.assertIn("return 301 https://exp.gno.utsa.tech$request_uri;", self.final)

    def test_api_proxy_preserves_request_uri_and_is_not_public(self):
        proxy_targets = re.findall(r"^\s*proxy_pass\s+([^;]+);", self.final, re.MULTILINE)
        self.assertEqual(proxy_targets, ["http://127.0.0.1:18180"])
        self.assertNotIn("http://127.0.0.1:18180/", self.final)
        self.assertNotIn("0.0.0.0:18180", self.final)
        self.assertRegex(self.final, r"location /api/\s*\{")

    def test_https_fallback_returns_404(self):
        https_server = self.final.split("listen 443 ssl http2;", 1)[1]
        self.assertRegex(https_server, r"location /\s*\{\s*return 404;", re.DOTALL)

    def test_proxy_headers_and_timeouts_are_complete(self):
        directives = (
            "proxy_http_version 1.1;",
            "proxy_set_header Host $host;",
            "proxy_set_header X-Real-IP $remote_addr;",
            "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "proxy_set_header X-Forwarded-Proto $scheme;",
            "proxy_set_header X-Forwarded-Host $host;",
            "proxy_set_header X-Forwarded-Port $server_port;",
            "proxy_connect_timeout 5s;",
            "proxy_send_timeout 15s;",
            "proxy_read_timeout 15s;",
        )
        for directive in directives:
            self.assertIn(directive, self.final)

    def test_proxy_is_read_only_without_policy_expansion(self):
        self.assertRegex(self.final, r"limit_except\s+GET\s+OPTIONS\s*\{")
        self.assertNotIn("proxy_buffering off", self.final)
        self.assertNotIn("proxy_request_buffering off", self.final)
        self.assertNotIn("add_header Access-Control-", self.final)
        self.assertNotRegex(self.final, r"(?m)^\s*auth_(?:basic|request|jwt)\b")

    def test_documentation_validates_before_each_reload(self):
        commands = re.findall(r"^\s*(sudo (?:nginx -t|systemctl (?:reload|restart) nginx))\s*$", self.docs, re.MULTILINE)
        reload_indexes = [index for index, command in enumerate(commands) if command == "sudo systemctl reload nginx"]
        self.assertEqual(len(reload_indexes), 2)
        for index in reload_indexes:
            self.assertGreater(index, 0)
            self.assertEqual(commands[index - 1], "sudo nginx -t")
        self.assertNotIn("systemctl restart nginx", self.docs)

    def test_certbot_deploy_hook_validates_before_reload(self):
        expected_command = (
            "sudo certbot certonly --webroot \\\n"
            "     -w /var/www/letsencrypt \\\n"
            "     -d exp.gno.utsa.tech \\\n"
            "     --deploy-hook 'nginx -t && systemctl reload nginx'"
        )
        self.assertIn(expected_command, self.docs)
        hooks = re.findall(r"--deploy-hook\s+'([^']+)'", self.docs)
        self.assertEqual(hooks, ["nginx -t && systemctl reload nginx"])
        self.assertNotIn("--deploy-hook 'systemctl reload nginx'", self.docs)

    def test_documentation_does_not_open_internal_port_or_expose_secrets(self):
        self.assertNotRegex(self.docs, r"(?i)ufw\s+allow\s+18180")
        self.assertNotIn("BEGIN PRIVATE KEY", self.docs)
        self.assertNotRegex(self.docs, r"postgres(?:ql)?://[^\s/:]+:[^\s/@]+@")

    def test_tracked_assets_have_no_credential_bearing_urls(self):
        for path in (BOOTSTRAP_PATH, FINAL_PATH, DOCS_PATH):
            content = path.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"https?://[^\s/:]+:[^\s/@]+@")


if __name__ == "__main__":
    unittest.main()
