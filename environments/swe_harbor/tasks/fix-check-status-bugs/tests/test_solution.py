"""Tests for Fix Check Status and Badge Bugs."""
from __future__ import annotations

import os
import sys
from datetime import timedelta as td

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")

import django
django.setup()

from django.conf import settings
from django.core.signing import base64_hmac
from django.utils.timezone import now

from hc.api.models import Check
from hc.lib.badges import COLORS, get_badge_svg
from hc.test import BaseTestCase


# ---------------------------------------------------------------------------
# 1. get_status() for cron checks (10 tests)
# ---------------------------------------------------------------------------

class CronCheckStatusTestCase(BaseTestCase):
    """Cron-based checks must report correct status via get_status()."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            kind="cron",
            schedule="* * * * *",
            tz="UTC",
            status="up",
        )

    def test_cron_check_up_when_recent_ping(self):
        self.check.last_ping = now()
        self.check.save()
        self.assertEqual(self.check.get_status(), "up")

    def test_cron_check_grace_when_past_schedule(self):
        self.check.last_ping = now() - td(minutes=2)
        self.check.grace = td(hours=1)
        self.check.save()
        self.assertEqual(self.check.get_status(), "grace")

    def test_cron_check_down_when_past_grace(self):
        self.check.last_ping = now() - td(hours=2)
        self.check.grace = td(minutes=1)
        self.check.save()
        self.assertEqual(self.check.get_status(), "down")

    def test_simple_check_up_unaffected(self):
        simple = Check.objects.create(
            project=self.project,
            kind="simple",
            timeout=td(days=1),
            status="up",
            last_ping=now(),
        )
        self.assertEqual(simple.get_status(), "up")

    def test_simple_check_down_unaffected(self):
        simple = Check.objects.create(
            project=self.project,
            kind="simple",
            timeout=td(minutes=1),
            grace=td(seconds=1),
            status="up",
            last_ping=now() - td(hours=1),
        )
        self.assertEqual(simple.get_status(), "down")

    def test_cron_check_america_new_york_timezone(self):
        self.check.tz = "America/New_York"
        self.check.last_ping = now()
        self.check.save()
        self.assertEqual(self.check.get_status(), "up")

    def test_cron_check_asia_tokyo_timezone(self):
        self.check.tz = "Asia/Tokyo"
        self.check.last_ping = now()
        self.check.save()
        self.assertEqual(self.check.get_status(), "up")

    def test_cron_check_new_status_unchanged(self):
        self.check.status = "new"
        self.check.save()
        self.assertEqual(self.check.get_status(), "new")

    def test_cron_check_paused_status_unchanged(self):
        self.check.status = "paused"
        self.check.save()
        self.assertEqual(self.check.get_status(), "paused")

    def test_cron_check_down_with_large_grace(self):
        self.check.last_ping = now() - td(days=2)
        self.check.grace = td(hours=1)
        self.check.save()
        self.assertEqual(self.check.get_status(), "down")


# ---------------------------------------------------------------------------
# 2. to_dict() next_ping serialization (5 tests)
# ---------------------------------------------------------------------------

class NextPingSerializationTestCase(BaseTestCase):
    """to_dict() must return correct next_ping, not last_ping."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            kind="simple",
            timeout=td(hours=1),
            status="up",
            last_ping=now() - td(minutes=10),
        )

    def test_next_ping_differs_from_last_ping(self):
        d = self.check.to_dict()
        self.assertNotEqual(d["next_ping"], d["last_ping"])

    def test_next_ping_is_after_last_ping(self):
        d = self.check.to_dict()
        self.assertGreater(d["next_ping"], d["last_ping"])

    def test_next_ping_none_for_new_check(self):
        new_check = Check.objects.create(project=self.project, status="new")
        d = new_check.to_dict()
        self.assertIsNone(d["next_ping"])

    def test_next_ping_none_for_paused_check(self):
        self.check.status = "paused"
        self.check.save()
        d = self.check.to_dict()
        self.assertIsNone(d["next_ping"])

    def test_next_ping_iso_no_microseconds(self):
        d = self.check.to_dict()
        self.assertNotIn(".", d["next_ping"])

    def test_next_ping_cron_check_differs_from_last_ping(self):
        cron = Check.objects.create(
            project=self.project,
            kind="cron",
            schedule="* * * * *",
            tz="UTC",
            status="up",
            last_ping=now() - td(minutes=5),
        )
        d = cron.to_dict()
        self.assertNotEqual(d["next_ping"], d["last_ping"])


# ---------------------------------------------------------------------------
# 3. Badge aggregation (6 tests)
# ---------------------------------------------------------------------------

class BadgeAggregationTestCase(BaseTestCase):
    """Badge view must aggregate status correctly: down > late > up."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project, tags="prod", status="new"
        )
        sig = base64_hmac(
            str(self.project.badge_key), "prod", settings.SECRET_KEY
        )[:8]
        self.json_url = f"/badge/{self.project.badge_key}/{sig}/prod.json"
        self.late_url = f"/badge/{self.project.badge_key}/{sig}/prod.json"

    def test_all_up_badge_shows_up(self):
        self.check.status = "up"
        self.check.last_ping = now()
        self.check.save()
        doc = self.client.get(self.json_url).json()
        self.assertEqual(doc["status"], "up")

    def test_one_down_badge_shows_down(self):
        self.check.status = "down"
        self.check.save()
        doc = self.client.get(self.json_url).json()
        self.assertEqual(doc["status"], "down")

    def test_one_grace_badge_shows_late(self):
        self.check.last_ping = now() - td(days=1, minutes=10)
        self.check.status = "up"
        self.check.save()
        doc = self.client.get(self.late_url).json()
        self.assertEqual(doc["status"], "late")

    def test_mixed_down_and_grace_badge_shows_down(self):
        self.check.status = "down"
        self.check.save()
        check2 = Check.objects.create(
            project=self.project,
            tags="prod",
            status="up",
            last_ping=now() - td(days=1, minutes=10),
        )
        doc = self.client.get(self.late_url).json()
        self.assertEqual(doc["status"], "down")
        self.assertEqual(doc["down"], 1)
        self.assertEqual(doc["grace"], 1)

    def test_no_matching_checks_badge_shows_up(self):
        self.check.tags = "staging"
        self.check.save()
        doc = self.client.get(self.json_url).json()
        self.assertEqual(doc["status"], "up")
        self.assertEqual(doc["total"], 0)

    def test_grace_does_not_override_down(self):
        check_down = Check.objects.create(
            project=self.project, tags="prod", status="down"
        )
        check_grace = Check.objects.create(
            project=self.project,
            tags="prod",
            status="up",
            last_ping=now() - td(days=1, minutes=10),
        )
        self.check.delete()
        doc = self.client.get(self.late_url).json()
        self.assertEqual(doc["status"], "down")


# ---------------------------------------------------------------------------
# 4. Badge colors (5 tests)
# ---------------------------------------------------------------------------

class BadgeColorsTestCase(BaseTestCase):
    """Badge rendering must use correct colors for each status."""

    def test_up_color_is_green(self):
        self.assertEqual(COLORS["up"], "#4c1")

    def test_down_color_is_red(self):
        self.assertEqual(COLORS["down"], "#e05d44")

    def test_late_color_is_orange(self):
        self.assertEqual(COLORS["late"], "#fe7d37")

    def test_late_color_not_green(self):
        self.assertNotEqual(COLORS["late"], COLORS["up"])

    def test_svg_contains_correct_late_color(self):
        svg = get_badge_svg("test", "late")
        self.assertIn("#fe7d37", svg)
        self.assertNotIn("#4c1", svg)


# ---------------------------------------------------------------------------
# 5. check_badge view (3 tests)
# ---------------------------------------------------------------------------

class CheckBadgeViewTestCase(BaseTestCase):
    """Individual check badge view must reflect correct status."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="mycheck")
        self.badge_key = self.check.prepare_badge_key()

    def test_check_badge_down(self):
        self.check.status = "down"
        self.check.save()
        url = f"/b/2/{self.badge_key}.json"
        doc = self.client.get(url).json()
        self.assertEqual(doc["status"], "down")
        self.assertEqual(doc["down"], 1)

    def test_check_badge_grace_with_three_states(self):
        self.check.last_ping = now() - td(days=1, minutes=10)
        self.check.status = "up"
        self.check.save()
        url = f"/b/3/{self.badge_key}.json"
        doc = self.client.get(url).json()
        self.assertEqual(doc["status"], "late")

    def test_check_badge_grace_with_two_states(self):
        self.check.last_ping = now() - td(days=1, minutes=10)
        self.check.status = "up"
        self.check.save()
        url = f"/b/2/{self.badge_key}.json"
        doc = self.client.get(url).json()
        self.assertEqual(doc["status"], "up")


# ---------------------------------------------------------------------------
# 6. Integration / interaction tests (4 tests)
# ---------------------------------------------------------------------------

class InteractionTestCase(BaseTestCase):
    """Bugs interact: status feeds into badge, badge uses colors."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            tags="web",
            kind="cron",
            schedule="* * * * *",
            tz="UTC",
            status="up",
        )
        sig = base64_hmac(
            str(self.project.badge_key), "web", settings.SECRET_KEY
        )[:8]
        self.late_url = f"/badge/{self.project.badge_key}/{sig}/web.json"

    def test_cron_check_in_grace_badge_shows_late(self):
        self.check.last_ping = now() - td(minutes=2)
        self.check.grace = td(hours=1)
        self.check.save()
        doc = self.client.get(self.late_url).json()
        self.assertEqual(doc["status"], "late")

    def test_cron_check_down_badge_shows_down(self):
        self.check.last_ping = now() - td(hours=2)
        self.check.grace = td(minutes=1)
        self.check.save()
        doc = self.client.get(self.late_url).json()
        self.assertEqual(doc["status"], "down")

    def test_api_to_dict_status_matches_get_status(self):
        self.check.last_ping = now() - td(minutes=2)
        self.check.grace = td(hours=1)
        self.check.save()
        d = self.check.to_dict()
        self.assertEqual(d["status"], self.check.get_status())

    def test_svg_badge_for_late_uses_orange_not_green(self):
        self.check.last_ping = now() - td(minutes=2)
        self.check.grace = td(hours=1)
        self.check.save()
        sig = base64_hmac(
            str(self.project.badge_key), "web", settings.SECRET_KEY
        )[:8]
        svg_url = f"/badge/{self.project.badge_key}/{sig}/web.svg"
        r = self.client.get(svg_url)
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn("#fe7d37", content)


# ---------------------------------------------------------------------------
# 7. Edge cases (2 tests)
# ---------------------------------------------------------------------------

class BadgeEdgeCaseTestCase(BaseTestCase):
    """Badge endpoint edge cases."""

    def test_badge_invalid_format_returns_404(self):
        sig = base64_hmac(
            str(self.project.badge_key), "foo", settings.SECRET_KEY
        )[:8]
        url = f"/badge/{self.project.badge_key}/{sig}/foo.txt"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_badge_wrong_signature_returns_404(self):
        url = f"/badge/{self.project.badge_key}/BADSIG00/foo.svg"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)
