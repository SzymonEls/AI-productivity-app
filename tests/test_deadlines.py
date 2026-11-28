"""
A session ticked done puts away its project's deadline only once that has gone by.

Projects are booked on as many days as they need, so a session done before the
deadline is rarely the last one for it - and clearing the deadline then took the
purple D off the schedule while the work was still under way.
"""

from datetime import timedelta

from test_mcp import McpTestCase

from app.extensions import db
from app.models import ProjectDaySlot
from app.projects.slots import set_block_done, today_local


class DeadlineTests(McpTestCase):
    def _tick_today(self, project, deadline, problematic=False):
        today = today_local()
        project.session_deadline = deadline
        project.is_problematic = problematic
        db.session.add(ProjectDaySlot(user_id=self.user.id, project_id=project.id, slot_date=today, slot="B"))
        db.session.commit()
        ok, message, _ = set_block_done(self.user.id, today, "B", True)
        self.assertTrue(ok, message)
        db.session.commit()
        db.session.refresh(project)
        return project

    def test_a_deadline_still_to_come_stays(self):
        deadline = today_local() + timedelta(days=5)
        project = self._tick_today(self.public, deadline)
        self.assertEqual(project.session_deadline, deadline)

    def test_a_deadline_today_stays(self):
        deadline = today_local()
        self.assertEqual(self._tick_today(self.public, deadline).session_deadline, deadline)

    def test_a_past_deadline_goes(self):
        project = self._tick_today(self.public, today_local() - timedelta(days=1), problematic=True)
        self.assertIsNone(project.session_deadline)
        self.assertFalse(project.session_deadline_day_before)
        self.assertFalse(project.is_problematic)

    def test_problematic_clears_whatever_the_deadline(self):
        project = self._tick_today(self.public, today_local() + timedelta(days=5), problematic=True)
        self.assertFalse(project.is_problematic)
        self.assertIsNotNone(project.session_deadline)
