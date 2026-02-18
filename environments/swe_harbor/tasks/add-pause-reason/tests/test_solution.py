"""Tests for the Pause Reason feature."""
from __future__ import annotations

import json
import uuid

import os
import sys
sys.path.insert(0, "/app")
import django  # type: ignore[import-untyped]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from hc.api.models import Check  # type: ignore[import-untyped]
from hc.test import BaseTestCase  # type: ignore[import-untyped]


def pause_url(check: Check, v: int = 3) -> str:
    return f"/api/v{v}/checks/{check.code}/pause"


def resume_url(check: Check, v: int = 3) -> str:
    return f"/api/v{v}/checks/{check.code}/resume"


def single_url(check: Check, v: int = 3) -> str:
    return f"/api/v{v}/checks/{check.code}"


class PauseReasonModelTestCase(BaseTestCase):
    """Check model has pause_reason field and to_dict includes it."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_pause_reason_field_exists(self):
        self.assertTrue(hasattr(Check, "pause_reason"))
        self.check.pause_reason = "maintenance"
        self.check.save()
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "maintenance")

    def test_to_dict_includes_pause_reason_when_paused(self):
        self.check.status = "paused"
        self.check.pause_reason = "deploy in progress"
        d = self.check.to_dict(v=3)
        self.assertIn("pause_reason", d)
        self.assertEqual(d["pause_reason"], "deploy in progress")

    def test_to_dict_pause_reason_empty_when_not_paused(self):
        # Use status "new" so get_status() returns early and doesn't need last_ping
        self.check.status = "new"
        self.check.pause_reason = "should not show"
        d = self.check.to_dict(v=3)
        self.assertIn("pause_reason", d)
        self.assertEqual(d["pause_reason"], "")

    def test_to_dict_pause_reason_empty_when_status_new(self):
        self.check.status = "new"
        d = self.check.to_dict(v=3)
        self.assertEqual(d["pause_reason"], "")

    def test_to_dict_pause_reason_empty_when_status_down(self):
        self.check.status = "down"
        self.check.pause_reason = "old"
        d = self.check.to_dict(v=3)
        self.assertEqual(d["pause_reason"], "")


class PauseWithReasonTestCase(BaseTestCase):
    """POST pause with optional reason."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test", status="new")

    def post_pause(self, data: dict | None = None, api_key: str | None = None):
        if api_key is None:
            api_key = "X" * 32
        body = {"api_key": api_key}
        if data is not None:
            body.update(data)
        return self.client.post(
            pause_url(self.check),
            json.dumps(body),
            content_type="application/json",
        )

    def test_pause_with_reason_stores_it(self):
        r = self.post_pause({"reason": "maintenance window"})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "paused")
        self.assertEqual(self.check.pause_reason, "maintenance window")
        doc = r.json()
        self.assertEqual(doc["pause_reason"], "maintenance window")

    def test_pause_without_reason_defaults_empty(self):
        r = self.post_pause()
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "")
        self.assertEqual(r.json().get("pause_reason"), "")

    def test_pause_with_empty_body_reason_empty(self):
        r = self.post_pause({})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "")

    def test_pause_reason_stripped(self):
        r = self.post_pause({"reason": "  short  "})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "short")

    def test_pause_reason_capped_at_500(self):
        long_reason = "x" * 600
        r = self.post_pause({"reason": long_reason})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(len(self.check.pause_reason), 500)

    def test_pause_reason_exactly_500_accepted(self):
        exact = "a" * 500
        r = self.post_pause({"reason": exact})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, exact)

    def test_pause_reason_not_string_returns_400(self):
        r = self.post_pause({"reason": 123})
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.json()["error"].lower())

    def test_pause_reason_array_returns_400(self):
        r = self.post_pause({"reason": ["a", "b"]})
        self.assertEqual(r.status_code, 400)

    def test_pause_reason_object_returns_400(self):
        r = self.post_pause({"reason": {"x": 1}})
        self.assertEqual(r.status_code, 400)

    def test_pause_wrong_api_key_401(self):
        r = self.post_pause({"reason": "ok"}, api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_pause_wrong_project_403(self):
        other = Check.objects.create(project=self.bobs_project, name="Other", status="new")
        r = self.client.post(
            pause_url(other),
            json.dumps({"api_key": "X" * 32, "reason": "nope"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_pause_nonexistent_check_404(self):
        fake = uuid.uuid4()
        r = self.client.post(
            f"/api/v3/checks/{fake}/pause",
            json.dumps({"api_key": "X" * 32, "reason": "x"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)


class ResumeClearsReasonTestCase(BaseTestCase):
    """Resume clears pause_reason."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project, name="Test", status="paused", pause_reason="was debugging"
        )

    def post_resume(self, api_key: str | None = None):
        if api_key is None:
            api_key = "X" * 32
        return self.client.post(
            resume_url(self.check),
            json.dumps({"api_key": api_key}),
            content_type="application/json",
        )

    def test_resume_clears_pause_reason(self):
        r = self.post_resume()
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "new")
        self.assertEqual(self.check.pause_reason, "")
        self.assertEqual(r.json().get("pause_reason"), "")

    def test_resume_wrong_api_key_401(self):
        r = self.post_resume(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_resume_when_not_paused_409(self):
        self.check.status = "up"
        self.check.save()
        r = self.post_resume()
        self.assertEqual(r.status_code, 409)


class GetCheckReturnsPauseReasonTestCase(BaseTestCase):
    """GET single check returns pause_reason."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test")

    def get_check(self, api_key: str | None = None):
        if api_key is None:
            api_key = "X" * 32
        return self.client.get(single_url(self.check), HTTP_X_API_KEY=api_key)

    def test_get_check_includes_pause_reason_key(self):
        r = self.get_check()
        self.assertEqual(r.status_code, 200)
        self.assertIn("pause_reason", r.json())

    def test_get_check_paused_with_reason_returns_it(self):
        self.check.status = "paused"
        self.check.pause_reason = "outage"
        self.check.save()
        r = self.get_check()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "outage")

    def test_get_check_not_paused_returns_empty_pause_reason(self):
        # Use status "new" so get_status() doesn't call get_grace_start() (which needs last_ping)
        self.check.status = "new"
        self.check.save()
        r = self.get_check()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "")


class PauseReasonApiVersionsTestCase(BaseTestCase):
    """pause_reason works under v1, v2, v3."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test", status="new")

    def test_pause_with_reason_v1(self):
        r = self.client.post(
            pause_url(self.check, v=1),
            json.dumps({"api_key": "X" * 32, "reason": "v1"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "v1")

    def test_pause_with_reason_v2(self):
        r = self.client.post(
            pause_url(self.check, v=2),
            json.dumps({"api_key": "X" * 32, "reason": "v2"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "v2")

    def test_pause_with_reason_v3(self):
        r = self.client.post(
            pause_url(self.check, v=3),
            json.dumps({"api_key": "X" * 32, "reason": "v3"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "v3")

    def _post_pause(self, data=None):
        body = {"api_key": "X" * 32}
        if data is not None:
            body.update(data)
        return self.client.post(
            pause_url(self.check),
            json.dumps(body),
            content_type="application/json",
        )

    def test_pause_reason_boolean_returns_400(self):
        r = self._post_pause({"reason": True})
        self.assertEqual(r.status_code, 400)

    def test_pause_reason_null_returns_400(self):
        r = self.client.post(
            pause_url(self.check),
            json.dumps({"api_key": "X" * 32, "reason": None}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_pause_reason_nested_object_returns_400(self):
        r = self._post_pause({"reason": {"nested": "value"}})
        self.assertEqual(r.status_code, 400)

    def test_pause_twice_overwrites_reason(self):
        self._post_pause({"reason": "first"})
        self._post_pause({"reason": "second"})
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "second")

    def test_pause_reason_with_unicode(self):
        r = self._post_pause({"reason": "maintenance \u2014 d\u00e9ploiement \U0001f680"})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertIn("\u2014", self.check.pause_reason)
        self.assertIn("\U0001f680", self.check.pause_reason)

    def test_pause_reason_with_newlines(self):
        r = self._post_pause({"reason": "line1\nline2\nline3"})
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertIn("\n", self.check.pause_reason)

    def test_resume_clears_long_reason(self):
        self._post_pause({"reason": "x" * 500})
        self.check.refresh_from_db()
        self.assertEqual(len(self.check.pause_reason), 500)
        r = self.client.post(
            resume_url(self.check),
            json.dumps({"api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertEqual(self.check.pause_reason, "")

    def test_get_check_pause_reason_round_trip(self):
        self._post_pause({"reason": "round trip test"})
        r = self.client.get(
            single_url(self.check),
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pause_reason"], "round trip test")
