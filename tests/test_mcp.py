"""
The MCP endpoint, and above all the promise it makes about private projects:
nothing written in one leaves the server, and nothing in one is changed.

Run with ``python -m unittest discover tests`` from the repository root. Each
run builds a fresh SQLite database in a temporary folder through the real
migrations.
"""

import json
import os
import tempfile
import unittest
from datetime import timedelta

_DB_DIR = tempfile.mkdtemp(prefix="mcp-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_DB_DIR, 'app.db')}"
os.environ.setdefault("SECRET_KEY", "test")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import InboxItem, Project, ProjectDaySlot, ProjectTimeEntry, User  # noqa: E402
from app.mcp import tools  # noqa: E402
from app.projects.slots import today_local  # noqa: E402

# Every piece of a private project's contents carries this marker, so one
# substring check over an answer finds a leak wherever it came from.
SECRET = "SECRET"


class McpTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        for table in reversed(db.metadata.sorted_tables):
            if table.name != "alembic_version":
                db.session.execute(table.delete())
        db.session.commit()

        self.user = User(username="owner", email="owner@example.com")
        self.user.set_password("pw")
        self.user.regenerate_mcp_credential("token")
        self.user.regenerate_mcp_credential("url")
        db.session.add(self.user)

        self.public = Project(
            owner=self.user,
            title="Public project",
            short_goal="open thoughts",
            long_goal="# Write chapter one\n- [ ] outline",
        )
        self.private = Project(
            owner=self.user,
            title="Hidden project",
            short_goal=f"{SECRET} thoughts",
            long_goal=f"# {SECRET} step\n- [ ] {SECRET} todo",
            archived_long_goal=f"# {SECRET} archived",
            is_private=True,
        )
        db.session.add_all([self.public, self.private])
        db.session.flush()
        # The private project waits for the public one at a milestone of its own.
        self.private.waiting_for_project_id = self.public.id
        self.private.waiting_for_note = f"{SECRET} milestone"
        today = today_local()
        db.session.add(ProjectDaySlot(user_id=self.user.id, project_id=self.private.id, slot_date=today, slot="A"))
        db.session.add(
            ProjectDaySlot(
                user_id=self.user.id, project_id=self.private.id, slot_date=today + timedelta(days=2), slot="B"
            )
        )
        db.session.add(InboxItem(user_id=self.user.id, body="a thought to file"))
        db.session.commit()

        self.client = self.app.test_client()
        self.headers = {"Authorization": f"Bearer {self.user.mcp_token}"}
        self.answers = []

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    # --- helpers ---

    def rpc(self, method, params=None, headers=None, path="/mcp"):
        response = self.client.post(
            path,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers=self.headers if headers is None else headers,
        )
        self.answers.append(response.get_data(as_text=True))
        return response

    def call(self, name, **arguments):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()["result"]
        return json.loads(result["content"][0]["text"])

    def assertNoSecretLeaked(self):
        for answer in self.answers:
            self.assertNotIn(SECRET, answer)


class AuthenticationTests(McpTestCase):
    def test_no_credential_is_refused(self):
        self.assertEqual(self.rpc("ping", headers={}).status_code, 401)

    def test_api_token_does_not_open_mcp(self):
        response = self.rpc("ping", headers={"Authorization": f"Bearer {self.user.api_token}"})
        self.assertEqual(response.status_code, 401)

    def test_url_secret_works_and_a_wrong_one_does_not(self):
        self.assertEqual(self.rpc("ping", headers={}, path=f"/mcp/{self.user.mcp_url_secret}").status_code, 200)
        self.assertEqual(self.rpc("ping", headers={}, path="/mcp/not-the-secret").status_code, 401)

    def test_switching_one_off_leaves_the_other(self):
        secret = self.user.mcp_url_secret
        self.user.disable_mcp_credential("token")
        db.session.commit()
        self.assertEqual(self.rpc("ping").status_code, 401)
        self.assertEqual(self.rpc("ping", headers={}, path=f"/mcp/{secret}").status_code, 200)

    def test_regenerating_retires_the_old_token(self):
        old = dict(self.headers)
        self.user.regenerate_mcp_credential("token")
        db.session.commit()
        self.assertEqual(self.rpc("ping", headers=old).status_code, 401)

    def test_foreign_origin_is_refused(self):
        headers = {**self.headers, "Origin": "https://evil.example"}
        self.assertEqual(self.rpc("ping", headers=headers).status_code, 403)


class ProtocolTests(McpTestCase):
    def test_initialize_and_list(self):
        answer = self.rpc("initialize", {"protocolVersion": "2025-06-18"}).get_json()["result"]
        self.assertEqual(answer["protocolVersion"], "2025-06-18")
        self.assertIn("tools", answer["capabilities"])
        names = {entry["name"] for entry in self.rpc("tools/list").get_json()["result"]["tools"]}
        self.assertTrue({"get_today", "get_project", "book_session", "update_project"} <= names)

    def test_notification_gets_202(self):
        response = self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 202)

    def test_unknown_tool_is_an_error(self):
        self.assertIn("error", self.rpc("tools/call", {"name": "nope"}).get_json())


class PrivacyTests(McpTestCase):
    def test_no_read_tool_leaks_private_contents(self):
        today = today_local()
        self.call("get_today")
        self.call("list_projects", include_archived=True)
        project = self.call("get_project", project_id=self.private.id)["project"]
        self.call("get_schedule", start_date=(today - timedelta(days=3)).isoformat())
        self.call("block_options", date=(today + timedelta(days=5)).isoformat(), slot="C")
        self.call("list_tasks", include_done=True)
        self.call("list_inbox")

        self.assertEqual(project["thoughts"], tools.PRIVATE)
        self.assertEqual(project["plan"], tools.PRIVATE)
        self.assertEqual(project["archived_plan"], tools.PRIVATE)
        self.assertEqual(project["current_step"], tools.PRIVATE)
        self.assertEqual(project["waiting_for"]["milestone"], tools.PRIVATE)
        self.assertEqual(project["title"], "Hidden project")
        self.assertNoSecretLeaked()

    def test_public_project_is_read_in_full(self):
        project = self.call("get_project", project_id=self.public.id)["project"]
        self.assertEqual(project["thoughts"], "open thoughts")
        self.assertIn("Write chapter one", project["plan"])
        self.assertEqual(project["current_step"], "Write chapter one")

    def test_private_thoughts_and_plan_cannot_be_changed(self):
        for field in ("thoughts", "plan"):
            answer = self.call("update_project", project_id=self.private.id, **{field: "overwritten"})
            self.assertFalse(answer["ok"])
        db.session.refresh(self.private)
        self.assertTrue(self.private.short_goal.startswith(SECRET))
        self.assertTrue(self.private.long_goal.startswith(f"# {SECRET}"))

    def test_private_settings_can_still_be_planned(self):
        answer = self.call("update_project", project_id=self.private.id, sessions_per_week=2)
        self.assertTrue(answer["ok"], answer)
        db.session.refresh(self.private)
        self.assertEqual(self.private.sessions_per_week, 2)
        self.assertTrue(self.private.is_private)

    def test_privacy_cannot_be_switched_off(self):
        self.call("update_project", project_id=self.private.id, is_private=False, title="Still hidden")
        db.session.refresh(self.private)
        self.assertTrue(self.private.is_private)

    def test_created_projects_are_never_private(self):
        answer = self.call("create_project", title="New one", is_private=True)
        self.assertTrue(answer["ok"], answer)
        self.assertFalse(db.session.get(Project, answer["project"]["id"]).is_private)

    def test_inbox_item_cannot_be_filed_into_a_private_project(self):
        item = InboxItem.query.first()
        answer = self.call("file_inbox_item", item_id=item.id, project_id=self.private.id)
        self.assertFalse(answer["ok"])
        self.assertIsNotNone(db.session.get(InboxItem, item.id))
        db.session.refresh(self.private)
        self.assertNotIn("a thought to file", self.private.long_goal)

    def test_timer_on_a_private_project_hides_its_note(self):
        answer = self.call("start_timer", project_id=self.private.id)
        self.assertTrue(answer["ok"], answer)
        # The timer is started with the plan's first heading as its note, as on the pages.
        self.assertIn(SECRET, ProjectTimeEntry.query.first().description)
        self.assertEqual(answer["timer"]["note"], tools.PRIVATE)
        self.call("get_today")
        self.call("stop_timer")
        self.assertNoSecretLeaked()

    def test_writes_do_not_echo_private_contents(self):
        today = today_local()
        self.call("set_session_state", date=today.isoformat(), slot="A", state="done")
        self.call("move_session", from_date=(today + timedelta(days=2)).isoformat(), from_slot="B",
                  to_date=(today + timedelta(days=3)).isoformat(), to_slot="A")
        self.call("book_session", project_id=self.private.id, date=(today + timedelta(days=4)).isoformat(), slot="A")
        self.call("set_project_deadline", project_id=self.private.id, date=(today + timedelta(days=1)).isoformat())
        self.call("take_day_off", date=(today + timedelta(days=1)).isoformat())
        self.assertNoSecretLeaked()


class PlanningTests(McpTestCase):
    def test_booking_follows_the_two_block_rule(self):
        today = today_local()
        first = self.call("book_session", project_id=self.public.id, date=(today + timedelta(days=1)).isoformat(), slot="A")
        self.assertTrue(first["ok"], first)
        second = self.call("book_session", project_id=self.public.id, date=(today + timedelta(days=2)).isoformat(), slot="A")
        self.assertFalse(second["ok"])
        taken = self.call("book_session", project_id=self.public.id, date=today.isoformat(), slot="A")
        self.assertFalse(taken["ok"])
        self.assertIn("Hidden project", taken["message"])

    def test_done_session_warns_when_nothing_is_next(self):
        today = today_local()
        self.call("book_session", project_id=self.public.id, date=today.isoformat(), slot="B")
        answer = self.call("set_session_state", date=today.isoformat(), slot="B", state="done")
        self.assertTrue(answer["ok"], answer)
        self.assertIn("plan its next session", answer["warning"])

    def test_tasks_notes_and_inbox_round_trip(self):
        today = today_local().isoformat()
        task = self.call("add_task", title="Call the bank", due_date=today)["task"]
        self.assertTrue(self.call("update_task", task_id=task["id"], is_done=True)["ok"])
        note = self.call("add_day_note", date=today, text="Slept badly")["note"]
        self.assertTrue(self.call("delete_day_note", note_id=note["id"])["ok"])
        item = InboxItem.query.first()
        filed = self.call("file_inbox_item", item_id=item.id, project_id=self.public.id)
        self.assertTrue(filed["ok"], filed)
        db.session.refresh(self.public)
        self.assertIn("- [ ] a thought to file", self.public.long_goal)


if __name__ == "__main__":
    unittest.main()
