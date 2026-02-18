"""Tests for the Maintenance Window feature (no down alerts during window)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta as td, timezone

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")

import django
django.setup()

from django.utils.timezone import now

from hc.api.management.commands.sendalerts import notify
from hc.api.models import Channel, Check, Flip, Notification
from hc.test import BaseTestCase


# ---- Model: field existence and persistence ----

class MaintenanceWindowModelFieldsTestCase(BaseTestCase):
    """Check has maintenance_start and maintenance_end fields."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_in_maintenance_window_method_exists(self):
        self.assertTrue(callable(getattr(Check, "in_maintenance_window", None)))

    def test_maintenance_start_field_exists(self):
        self.assertTrue(hasattr(Check, "maintenance_start"))

    def test_maintenance_end_field_exists(self):
        self.assertTrue(hasattr(Check, "maintenance_end"))

    def test_both_fields_save_and_load(self):
        start = now()
        end = now() + td(hours=1)
        self.check.maintenance_start = start
        self.check.maintenance_end = end
        self.check.save()
        self.check.refresh_from_db()
        self.assertIsNotNone(self.check.maintenance_start)
        self.assertIsNotNone(self.check.maintenance_end)

    def test_fields_default_null(self):
        self.assertIsNone(self.check.maintenance_start)
        self.assertIsNone(self.check.maintenance_end)

    def test_can_clear_window_after_setting(self):
        self.check.maintenance_start = now()
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        self.check.maintenance_start = None
        self.check.maintenance_end = None
        self.check.save()
        self.check.refresh_from_db()
        self.assertIsNone(self.check.maintenance_start)
        self.assertIsNone(self.check.maintenance_end)


# ---- Model: in_maintenance_window() ----

class InMaintenanceWindowTestCase(BaseTestCase):
    """in_maintenance_window() returns correct value for various window configurations."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_returns_false_when_both_none(self):
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_when_only_start_set(self):
        self.check.maintenance_start = now() - td(hours=1)
        self.check.maintenance_end = None
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_when_only_end_set(self):
        self.check.maintenance_start = None
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_true_when_now_inside_window(self):
        self.check.maintenance_start = now() - td(minutes=10)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        self.assertTrue(self.check.in_maintenance_window())

    def test_returns_false_when_now_before_start(self):
        self.check.maintenance_start = now() + td(hours=1)
        self.check.maintenance_end = now() + td(hours=2)
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_when_now_after_end(self):
        self.check.maintenance_start = now() - td(hours=2)
        self.check.maintenance_end = now() - td(hours=1)
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_true_when_now_exactly_at_start(self):
        t = now()
        self.check.maintenance_start = t
        self.check.maintenance_end = t + td(hours=1)
        self.check.save()
        self.assertTrue(self.check.in_maintenance_window())

    def test_returns_false_when_now_exactly_at_end(self):
        t = now()
        self.check.maintenance_start = t - td(hours=1)
        self.check.maintenance_end = t
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_when_window_fully_in_past(self):
        self.check.maintenance_start = now() - td(hours=2)
        self.check.maintenance_end = now() - td(hours=1)
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_when_window_fully_in_future(self):
        self.check.maintenance_start = now() + td(hours=1)
        self.check.maintenance_end = now() + td(hours=2)
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_true_for_long_window(self):
        self.check.maintenance_start = now() - td(days=1)
        self.check.maintenance_end = now() + td(days=1)
        self.check.save()
        self.assertTrue(self.check.in_maintenance_window())

    def test_returns_false_when_start_after_end(self):
        self.check.maintenance_start = now() + td(hours=1)
        self.check.maintenance_end = now()
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_returns_false_for_zero_duration_window(self):
        t = now()
        self.check.maintenance_start = t
        self.check.maintenance_end = t
        self.check.save()
        self.assertFalse(self.check.in_maintenance_window())

    def test_in_maintenance_window_after_refresh_from_db(self):
        self.check.maintenance_start = now() - td(minutes=5)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        check2 = Check.objects.get(pk=self.check.pk)
        self.assertTrue(check2.in_maintenance_window())


# ---- Notify: down alert sent when NOT in maintenance ----

class DownAlertSentWhenNotInMaintenanceTestCase(BaseTestCase):
    """Without maintenance window, down flips result in notifications."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="Test",
            status="down",
            last_ping=now() - td(days=1),
        )
        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.save()
        self.check.channel_set.add(self.channel)

    def test_down_flip_sends_notification_when_no_window(self):
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_down_flip_marked_processed_when_no_window(self):
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        notify(flip)
        flip.refresh_from_db()
        self.assertIsNotNone(flip.processed)

    def test_down_flip_sends_when_only_start_set(self):
        self.check.maintenance_start = now() - td(hours=1)
        self.check.maintenance_end = None
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_down_flip_sends_when_window_in_past(self):
        self.check.maintenance_start = now() - td(hours=2)
        self.check.maintenance_end = now() - td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_down_flip_sends_when_window_in_future(self):
        self.check.maintenance_start = now() + td(hours=1)
        self.check.maintenance_end = now() + td(hours=2)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_down_flip_old_status_new_sends_when_not_in_maintenance(self):
        flip = Flip(owner=self.check, created=now(), old_status="new", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_down_flip_multiple_channels_send_multiple_notifications(self):
        ch2 = Channel(project=self.project, kind="email")
        ch2.value = "bob@example.org"
        ch2.save()
        self.check.channel_set.add(ch2)
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreaterEqual(Notification.objects.count(), initial + 2)


# ---- Notify: down alert NOT sent when IN maintenance ----

class DownAlertSuppressedWhenInMaintenanceTestCase(BaseTestCase):
    """When check is in maintenance window, down flips do not send notifications."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="Test",
            status="down",
            last_ping=now() - td(days=1),
        )
        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.save()
        self.check.channel_set.add(self.channel)

    def test_down_flip_no_notification_when_in_maintenance(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertEqual(Notification.objects.count(), initial)

    def test_down_flip_still_marked_processed_when_suppressed(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        notify(flip)
        flip.refresh_from_db()
        self.assertIsNotNone(flip.processed)

    def test_down_flip_suppressed_when_now_just_after_start(self):
        self.check.maintenance_start = now() - td(seconds=1)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertEqual(Notification.objects.count(), initial)

    def test_down_flip_suppressed_when_now_just_before_end(self):
        self.check.maintenance_start = now() - td(hours=1)
        self.check.maintenance_end = now() + td(seconds=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertEqual(Notification.objects.count(), initial)

    def test_down_flip_with_multiple_channels_no_notifications(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        ch2 = Channel(project=self.project, kind="email")
        ch2.value = "bob@example.org"
        ch2.save()
        self.check.channel_set.add(ch2)
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertEqual(Notification.objects.count(), initial)


# ---- Notify: up and other alerts unchanged ----

class UpAlertUnchangedTestCase(BaseTestCase):
    """Maintenance window only suppresses DOWN alerts; UP alerts still send."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="Test",
            status="up",
            last_ping=now() - td(days=1),
        )
        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.save()
        self.check.channel_set.add(self.channel)

    def test_up_flip_sent_when_in_maintenance(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="down", new_status="up")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_up_flip_sent_when_no_maintenance(self):
        flip = Flip(owner=self.check, created=now(), old_status="down", new_status="up")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)

    def test_up_flip_sent_when_maintenance_window_in_past(self):
        self.check.maintenance_start = now() - td(hours=2)
        self.check.maintenance_end = now() - td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="down", new_status="up")
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertGreater(Notification.objects.count(), initial)


# ---- Notify: edge cases ----

class NotifyEdgeCasesTestCase(BaseTestCase):
    """Edge cases: already processed, no channels, different checks."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="Test",
            status="down",
            last_ping=now() - td(days=1),
        )
        self.channel = Channel(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.save()
        self.check.channel_set.add(self.channel)

    def test_down_flip_no_channels_in_maintenance_still_processed(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        self.check.channel_set.clear()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        notify(flip)
        flip.refresh_from_db()
        self.assertIsNotNone(flip.processed)

    def test_two_checks_one_in_maintenance_only_that_one_suppressed(self):
        check2 = Check.objects.create(
            project=self.project,
            name="Other",
            status="down",
            last_ping=now() - td(days=1),
        )
        check2.channel_set.add(self.channel)
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip1 = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip1.save()
        flip2 = Flip(owner=check2, created=now(), old_status="up", new_status="down")
        flip2.save()
        initial = Notification.objects.count()
        notify(flip1)
        self.assertEqual(Notification.objects.count(), initial)
        notify(flip2)
        self.assertGreater(Notification.objects.count(), initial)

    def test_same_check_first_flip_in_maintenance_second_not(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(minutes=31)
        self.check.save()
        flip1 = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip1.save()
        initial = Notification.objects.count()
        notify(flip1)
        self.assertEqual(Notification.objects.count(), initial)
        self.check.maintenance_start = None
        self.check.maintenance_end = None
        self.check.save()
        flip2 = Flip(owner=self.check, created=now() + td(seconds=1), old_status="up", new_status="down")
        flip2.save()
        notify(flip2)
        self.assertGreater(Notification.objects.count(), initial)

    def test_already_processed_down_flip_in_maintenance_no_duplicate_notifications(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down", processed=now())
        flip.save()
        initial = Notification.objects.count()
        notify(flip)
        self.assertEqual(Notification.objects.count(), initial)

    def test_notify_returns_none_for_suppressed_down(self):
        self.check.maintenance_start = now() - td(minutes=30)
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip.save()
        result = notify(flip)
        self.assertIsNone(result)

    def test_different_project_check_in_maintenance_does_not_affect_our_flips(self):
        other_check = Check.objects.create(
            project=self.bobs_project,
            name="Bob Check",
            status="down",
            last_ping=now() - td(days=1),
        )
        other_check.maintenance_start = now() - td(hours=1)
        other_check.maintenance_end = now() + td(hours=1)
        other_check.save()
        ch_bob = Channel(project=self.bobs_project, kind="email")
        ch_bob.value = "bob@example.org"
        ch_bob.save()
        other_check.channel_set.add(ch_bob)
        flip_ours = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        flip_ours.save()
        initial = Notification.objects.count()
        notify(flip_ours)
        self.assertGreater(Notification.objects.count(), initial)


# ---- Serialization: to_dict() includes maintenance window ----

class ToDictMaintenanceTestCase(BaseTestCase):
    """to_dict() must include maintenance_start and maintenance_end."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_to_dict_has_maintenance_start_key(self):
        d = self.check.to_dict()
        self.assertIn("maintenance_start", d)

    def test_to_dict_has_maintenance_end_key(self):
        d = self.check.to_dict()
        self.assertIn("maintenance_end", d)

    def test_to_dict_maintenance_null_by_default(self):
        d = self.check.to_dict()
        self.assertIsNone(d["maintenance_start"])
        self.assertIsNone(d["maintenance_end"])

    def test_to_dict_maintenance_set_values_iso(self):
        start = now()
        end = now() + td(hours=2)
        self.check.maintenance_start = start
        self.check.maintenance_end = end
        self.check.save()
        d = self.check.to_dict()
        self.assertIsNotNone(d["maintenance_start"])
        self.assertIsNotNone(d["maintenance_end"])
        self.assertIn("T", d["maintenance_start"])

    def test_to_dict_maintenance_cleared_after_reset(self):
        self.check.maintenance_start = now()
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        self.check.maintenance_start = None
        self.check.maintenance_end = None
        self.check.save()
        d = self.check.to_dict()
        self.assertIsNone(d["maintenance_start"])
        self.assertIsNone(d["maintenance_end"])


# ---- API: set maintenance window via update endpoint ----

def single_url(check, v=3):
    return f"/api/v{v}/checks/{check.code}"

class ApiUpdateMaintenanceTestCase(BaseTestCase):
    """API update endpoint must accept maintenance_start and maintenance_end."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Api Test")

    def test_set_maintenance_via_api(self):
        start = now().replace(microsecond=0)
        end = (now() + td(hours=2)).replace(microsecond=0)
        r = self.client.post(
            single_url(self.check),
            json.dumps({
                "api_key": "X" * 32,
                "maintenance_start": start.isoformat(),
                "maintenance_end": end.isoformat(),
            }),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertIsNotNone(self.check.maintenance_start)
        self.assertIsNotNone(self.check.maintenance_end)

    def test_clear_maintenance_via_api(self):
        self.check.maintenance_start = now()
        self.check.maintenance_end = now() + td(hours=1)
        self.check.save()
        r = self.client.post(
            single_url(self.check),
            json.dumps({
                "api_key": "X" * 32,
                "maintenance_start": "",
                "maintenance_end": "",
            }),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.check.refresh_from_db()
        self.assertIsNone(self.check.maintenance_start)
        self.assertIsNone(self.check.maintenance_end)

    def test_get_check_includes_maintenance_in_response(self):
        start = now().replace(microsecond=0)
        end = (now() + td(hours=2)).replace(microsecond=0)
        self.check.maintenance_start = start
        self.check.maintenance_end = end
        self.check.save()
        r = self.client.get(
            single_url(self.check),
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["maintenance_start"], start.isoformat())
        self.assertEqual(data["maintenance_end"], end.isoformat())
