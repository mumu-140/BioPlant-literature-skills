from __future__ import annotations

import stat
import tempfile
import unittest
import sys
from pathlib import Path

from fastapi.testclient import TestClient

SKILL_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SKILL_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bio_literature_digest.api.app import create_app
from bio_literature_digest.api.configuration import ConfigManager
from bio_literature_digest.api.models import RunRequest
from bio_literature_digest.api.store import ActiveRunError, RunStore


class FakeManager:
    def __init__(self, store: RunStore, *, conflict: bool = False) -> None:
        self.store = store
        self.conflict = conflict

    def submit(self, request: RunRequest):  # type: ignore[no-untyped-def]
        if self.conflict:
            raise ActiveRunError("another digest run is active: existing")
        return self.store.create(request.model_dump(mode="json"))


class DigestApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="bio-digest-api-")
        self.run_root = Path(self.temp_dir.name) / "runs"
        self.store = RunStore(self.run_root)
        root = Path(self.temp_dir.name)
        watchlist = root / "journals.yaml"
        rules = root / "rules.yaml"
        recipients = root / "users.yaml"
        watchlist.write_text("journals: []\n", encoding="utf-8")
        rules.write_text("categories:\n  - id: other\n", encoding="utf-8")
        recipients.write_text("users: []\n", encoding="utf-8")
        configs = ConfigManager(watchlist, rules, recipients, root / "backups")
        app = create_app(
            api_key="test-api-key",
            run_root=self.run_root,
            manager=FakeManager(self.store),
            config_manager=configs,
        )
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-api-key"}

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_health_is_public(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_run_endpoints_require_api_key(self) -> None:
        response = self.client.get("/api/v1/runs")
        self.assertEqual(response.status_code, 401)

    def test_supports_x_api_key_header(self) -> None:
        response = self.client.get("/api/v1/me", headers={"X-API-Key": "test-api-key"})
        self.assertEqual(response.status_code, 200)

    def test_identity_and_run_state_files_are_private(self) -> None:
        auth_mode = stat.S_IMODE((self.run_root.parent / "auth.sqlite3").stat().st_mode)
        record = self.store.create({})
        status_mode = stat.S_IMODE((self.store.run_dir(str(record["id"])) / "status.json").stat().st_mode)
        self.assertEqual(auth_mode, 0o600)
        self.assertEqual(status_mode, 0o600)

    def test_create_and_get_run(self) -> None:
        response = self.client.post(
            "/api/v1/runs",
            headers=self.headers,
            json={"skip_email": True, "summary_provider": "placeholder"},
        )
        self.assertEqual(response.status_code, 202)
        run_id = response.json()["id"]

        status_response = self.client.get(f"/api/v1/runs/{run_id}", headers=self.headers)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "queued")

    def test_rejects_partial_window_and_unknown_fields(self) -> None:
        partial = self.client.post(
            "/api/v1/runs",
            headers=self.headers,
            json={"window_start": "2026-03-13T00:00:00Z"},
        )
        unknown = self.client.post(
            "/api/v1/runs",
            headers=self.headers,
            json={"input_file": "/etc/passwd"},
        )
        self.assertEqual(partial.status_code, 422)
        self.assertEqual(unknown.status_code, 422)

    def test_rejects_timezone_naive_window(self) -> None:
        response = self.client.post(
            "/api/v1/runs",
            headers=self.headers,
            json={"window_start": "2026-03-13T00:00:00", "window_end": "2026-03-14T00:00:00"},
        )
        self.assertEqual(response.status_code, 422)

    def test_reports_active_run_conflict(self) -> None:
        app = create_app(
            api_key="test-api-key",
            run_root=self.run_root,
            manager=FakeManager(self.store, conflict=True),
        )
        with TestClient(app) as client:
            response = client.post("/api/v1/runs", headers=self.headers, json={})
        self.assertEqual(response.status_code, 409)

    def test_admin_can_create_viewer_and_viewer_is_read_only(self) -> None:
        username = f"reader-{Path(self.temp_dir.name).name[-8:]}"
        created = self.client.post(
            "/api/v1/users",
            headers=self.headers,
            json={"username": username, "display_name": "Reader", "role": "viewer"},
        )
        self.assertEqual(created.status_code, 201)
        viewer_headers = {"Authorization": f"Bearer {created.json()['token']}"}
        self.assertEqual(self.client.get("/api/v1/runs", headers=viewer_headers).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/runs", headers=viewer_headers, json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/users", headers=viewer_headers).status_code, 403)

    def test_token_rotation_and_deactivation_invalidate_access(self) -> None:
        created = self.client.post(
            "/api/v1/users",
            headers=self.headers,
            json={"username": "rotate-user", "display_name": "Rotate User", "role": "viewer"},
        ).json()
        old_headers = {"Authorization": f"Bearer {created['token']}"}
        rotated = self.client.post(
            f"/api/v1/users/{created['id']}/rotate-token",
            headers=self.headers,
        ).json()
        new_headers = {"Authorization": f"Bearer {rotated['token']}"}
        self.assertEqual(self.client.get("/api/v1/me", headers=old_headers).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/me", headers=new_headers).status_code, 200)

        disabled = self.client.patch(
            f"/api/v1/users/{created['id']}",
            headers=self.headers,
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me", headers=new_headers).status_code, 401)

    def test_operator_cannot_write_any_configuration(self) -> None:
        created = self.client.post(
            "/api/v1/users",
            headers=self.headers,
            json={"username": "config-operator", "display_name": "Config Operator", "role": "operator"},
        ).json()
        headers = {"Authorization": f"Bearer {created['token']}"}
        responses = [
            self.client.post("/api/v1/config/journals", headers=headers, json={"id": "forbidden"}),
            self.client.put(
                "/api/v1/config/category-rules",
                headers=headers,
                json={"categories": [{"id": "other"}]},
            ),
            self.client.put("/api/v1/config/recipients", headers=headers, json={"users": []}),
        ]
        self.assertEqual([response.status_code for response in responses], [403, 403, 403])

    def test_admin_can_manage_journals_and_rules(self) -> None:
        journal = {
            "id": "example-journal",
            "enabled": True,
            "journal_name": "Example Journal",
            "source_strategy": "official_feed",
            "source_locator": "https://example.com/feed.xml",
        }
        created = self.client.post("/api/v1/config/journals", headers=self.headers, json=journal)
        listing = self.client.get("/api/v1/config/journals", headers=self.headers)
        invalid_rules = self.client.put(
            "/api/v1/config/category-rules",
            headers=self.headers,
            json={"categories": [{"id": "genomics"}]},
        )
        deleted = self.client.delete(
            "/api/v1/config/journals/example-journal",
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(listing.json()["journals"][0]["id"], "example-journal")
        self.assertEqual(invalid_rules.status_code, 422)
        self.assertEqual(deleted.status_code, 204)

    def test_rejects_malformed_category_entries(self) -> None:
        response = self.client.put(
            "/api/v1/config/category-rules",
            headers=self.headers,
            json={"categories": [{"id": "other"}, "invalid"]},
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_private_or_non_http_journal_sources(self) -> None:
        locators = ["file:///etc/passwd", "http://127.0.0.1/feed", "http://metadata.internal/feed"]
        for index, locator in enumerate(locators):
            response = self.client.post(
                "/api/v1/config/journals",
                headers=self.headers,
                json={"id": f"blocked-{index}", "source_locator": locator},
            )
            self.assertEqual(response.status_code, 422, locator)

    def test_rejects_configuration_writes_during_active_run(self) -> None:
        active_id = "a" * 32
        self.store.acquire_active_slot(active_id)
        try:
            response = self.client.put(
                "/api/v1/config/category-rules",
                headers=self.headers,
                json={"categories": [{"id": "other"}]},
            )
        finally:
            self.store.release_active_slot(active_id)
        self.assertEqual(response.status_code, 409)

    def test_admin_cannot_delete_self(self) -> None:
        me = self.client.get("/api/v1/me", headers=self.headers).json()
        response = self.client.delete(f"/api/v1/users/{me['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_lists_and_downloads_whitelisted_artifacts(self) -> None:
        record = self.store.create({})
        run_id = str(record["id"])
        work_dir = Path(str(record["work_dir"]))
        work_dir.mkdir(parents=True)
        (work_dir / "digest.csv").write_text("journal,title\n", encoding="utf-8")

        listing = self.client.get(f"/api/v1/runs/{run_id}/artifacts", headers=self.headers)
        download = self.client.get(
            f"/api/v1/runs/{run_id}/artifacts/digest.csv",
            headers=self.headers,
        )
        blocked = self.client.get(
            f"/api/v1/runs/{run_id}/artifacts/status.json",
            headers=self.headers,
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["name"], "digest.csv")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.text, "journal,title\n")
        self.assertEqual(blocked.status_code, 404)


if __name__ == "__main__":
    unittest.main()
