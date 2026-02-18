"""Tests for the Check Notes feature."""
from __future__ import annotations

import json
import uuid

import os
import sys
sys.path.insert(0, "/app")  # so Python can find the app code
import django  # type: ignore[import-untyped]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()  # start Django so models and URLs work

from hc.api.models import Check  # type: ignore[import-untyped]
from hc.test import BaseTestCase  # type: ignore[import-untyped]  # gives us self.project, self.client, self.bobs_project, etc.


# 1. Model tests: does the Note model exist and behave correctly?

class NoteModelTestCase(BaseTestCase):
    """Tests for the Note model itself."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")  # one check for all tests in this class

    def test_note_model_exists(self):
        """The Note model should be importable."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        self.assertTrue(hasattr(Note, "objects"))  # real Django models have .objects

    def test_create_note(self):
        """Can create a note linked to a check."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        n = Note.objects.create(owner=self.check, body="Investigating timeout")
        self.assertIsNotNone(n.code)  # code (UUID) should be auto-generated
        self.assertEqual(n.body, "Investigating timeout")

    def test_note_has_uuid(self):
        """Each note should have a unique UUID code."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        n1 = Note.objects.create(owner=self.check, body="First")
        n2 = Note.objects.create(owner=self.check, body="Second")
        self.assertNotEqual(n1.code, n2.code)  # two notes must have different IDs

    def test_note_to_dict(self):
        """to_dict() returns correct keys and values."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        n = Note.objects.create(owner=self.check, body="Test body")
        d = n.to_dict()
        self.assertEqual(d["uuid"], str(n.code))  # uuid in dict is the code as string
        self.assertEqual(d["body"], "Test body")
        self.assertIn("created", d)  # must include created timestamp

    def test_to_dict_created_no_microseconds(self):
        """created in to_dict() should have no microseconds (ISO without decimal)."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        n = Note.objects.create(owner=self.check, body="Test")
        d = n.to_dict()
        created_str = d["created"]
        self.assertNotIn(".", created_str, "created should not contain microseconds")  # no decimal = no microseconds

    def test_note_ordering(self):
        """Notes should be ordered newest first by default."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        Note.objects.create(owner=self.check, body="First")
        Note.objects.create(owner=self.check, body="Second")
        notes = list(Note.objects.filter(owner=self.check))
        self.assertEqual(notes[0].body, "Second")  # newest first
        self.assertEqual(notes[1].body, "First")

    def test_cascade_delete(self):
        """Deleting a check deletes its notes."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        Note.objects.create(owner=self.check, body="Will be deleted")
        self.assertEqual(Note.objects.count(), 1)
        self.check.delete()  # delete the check
        self.assertEqual(Note.objects.count(), 0)  # notes should be gone too (CASCADE)

    def test_related_name(self):
        """check.notes should work as reverse relation."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        Note.objects.create(owner=self.check, body="Via relation")
        self.assertEqual(self.check.notes.count(), 1)  # we can get notes from the check via .notes


# 2. POST tests: creating a note via the API

class CreateNoteApiTestCase(BaseTestCase):
    """Tests for POST /api/v3/checks/<code>/notes/"""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")
        self.url = f"/api/v3/checks/{self.check.code}/notes/"  # the URL we will POST to

    def post(self, data, api_key=None):
        """Helper: POST to the notes URL with optional api_key (default = our project's key)."""
        if api_key is None:
            api_key = "X" * 32  # our project's API key (from BaseTestCase)
        return self.client.post(
            self.url,
            json.dumps({**data, "api_key": api_key}),  # merge body + api_key into one JSON
            content_type="application/json",
        )

    def test_create_note_success(self):
        """POST with body should create a note and return 201."""
        r = self.post({"body": "Investigating timeout"})
        self.assertEqual(r.status_code, 201)  # created
        doc = r.json()
        self.assertEqual(doc["body"], "Investigating timeout")
        self.assertIn("uuid", doc)
        self.assertIn("created", doc)

    def test_missing_body(self):
        """POST without body should return 400."""
        r = self.post({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("body", r.json()["error"].lower())  # error message should mention body

    def test_empty_body(self):
        """POST with empty body should return 400."""
        r = self.post({"body": ""})
        self.assertEqual(r.status_code, 400)

    def test_whitespace_only_body(self):
        """POST with whitespace-only body should return 400."""
        r = self.post({"body": "   "})
        self.assertEqual(r.status_code, 400)

    def test_body_too_long(self):
        """POST with body > 1000 chars should return 400."""
        r = self.post({"body": "x" * 1001})
        self.assertEqual(r.status_code, 400)
        self.assertIn("too long", r.json()["error"].lower())

    def test_wrong_api_key(self):
        """POST with wrong API key should return 401."""
        r = self.post({"body": "Test"}, api_key="Y" * 32)  # wrong key
        self.assertEqual(r.status_code, 401)

    def test_wrong_project(self):
        """POST for a check in a different project should return 403."""
        other_check = Check.objects.create(project=self.bobs_project, name="Bob's Check")  # Bob's check
        url = f"/api/v3/checks/{other_check.code}/notes/"
        r = self.client.post(
            url,
            json.dumps({"body": "Hack attempt", "api_key": "X" * 32}),  # our key on Bob's check = forbidden
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_check(self):
        """POST for a nonexistent check should return 404."""
        fake_uuid = uuid.uuid4()
        url = f"/api/v3/checks/{fake_uuid}/notes/"
        r = self.client.post(
            url,
            json.dumps({"body": "Ghost", "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_note_limit(self):
        """POST should return 403 when check already has 50 notes."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        for i in range(50):
            Note.objects.create(owner=self.check, body=f"Note {i}")  # fill up to 50
        r = self.post({"body": "One too many"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("too many", r.json()["error"].lower())


# 3. GET tests: listing notes via the API

class ListNotesApiTestCase(BaseTestCase):
    """Tests for GET /api/v3/checks/<code>/notes/"""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")
        self.url = f"/api/v3/checks/{self.check.code}/notes/"

    def get(self, api_key=None):
        """Helper: GET the notes URL with optional api_key."""
        if api_key is None:
            api_key = "X" * 32
        return self.client.get(self.url, HTTP_X_API_KEY=api_key)  # API key goes in header

    def test_list_empty(self):
        """GET should return empty list when no notes exist."""
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notes"], [])

    def test_list_notes(self):
        """GET should return all notes for the check."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        Note.objects.create(owner=self.check, body="First")
        Note.objects.create(owner=self.check, body="Second")
        r = self.get()
        self.assertEqual(r.status_code, 200)
        notes = r.json()["notes"]
        self.assertEqual(len(notes), 2)

    def test_list_newest_first(self):
        """GET should return notes newest first."""
        from hc.api.models import Note  # type: ignore[import-untyped]
        Note.objects.create(owner=self.check, body="Older")
        Note.objects.create(owner=self.check, body="Newer")
        r = self.get()
        notes = r.json()["notes"]
        self.assertEqual(notes[0]["body"], "Newer")  # first in list = newest
        self.assertEqual(notes[1]["body"], "Older")

    def test_wrong_api_key(self):
        """GET with wrong API key should return 401."""
        r = self.get(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_wrong_project(self):
        """GET for a check in a different project should return 403."""
        other_check = Check.objects.create(project=self.bobs_project, name="Bob's Check")
        url = f"/api/v3/checks/{other_check.code}/notes/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)  # our key, Bob's check
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_check(self):
        """GET for a nonexistent check should return 404."""
        fake_uuid = uuid.uuid4()
        url = f"/api/v3/checks/{fake_uuid}/notes/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_cors_headers(self):
        """Response should include CORS headers."""
        r = self.get()
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")  # CORS header must be present


# 4. URL routing: notes endpoint works under v1, v2, v3

class NoteUrlRoutingTestCase(BaseTestCase):
    """Tests that the notes URL works for all API versions."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_v1_endpoint(self):
        """The notes endpoint should work under /api/v1/."""
        url = f"/api/v1/checks/{self.check.code}/notes/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v2_endpoint(self):
        """The notes endpoint should work under /api/v2/."""
        url = f"/api/v2/checks/{self.check.code}/notes/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v3_endpoint(self):
        """The notes endpoint should work under /api/v3/."""
        url = f"/api/v3/checks/{self.check.code}/notes/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)
