from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_portable_package import validate_members


class PortablePackageTest(unittest.TestCase):
    def test_accepts_required_public_files(self) -> None:
        prefix = "bio-literature-digest-https-portable-20260714"
        members = [f"{prefix}/{name}" for name in sorted({
            "install_server.sh",
            "docs/https_api_deployment.md",
            "ops/caddy/Caddyfile.example",
            "ops/systemd/bio-literature-digest-api.service.example",
            "scripts/audit_secrets.py",
            "scripts/serve_api.py",
        })]
        validate_members(members)

    def test_rejects_private_runtime_content(self) -> None:
        prefix = "bio-literature-digest-https-portable-20260714"
        members = [
            f"{prefix}/install_server.sh",
            f"{prefix}/docs/https_api_deployment.md",
            f"{prefix}/ops/caddy/Caddyfile.example",
            f"{prefix}/ops/systemd/bio-literature-digest-api.service.example",
            f"{prefix}/scripts/audit_secrets.py",
            f"{prefix}/scripts/serve_api.py",
            f"{prefix}/local/.env.local",
        ]
        with self.assertRaisesRegex(ValueError, "禁止内容"):
            validate_members(members)


if __name__ == "__main__":
    unittest.main()
