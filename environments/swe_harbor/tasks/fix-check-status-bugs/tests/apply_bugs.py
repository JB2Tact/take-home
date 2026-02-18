"""Inject 4 interacting bugs into the clean Healthchecks codebase."""
import sys

def patch(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        print(f"WARNING: patch target not found in {path}", file=sys.stderr)
        return
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)

# Bug 1: models.py get_grace_start() — remove UTC conversion for cron checks.
# This leaves the result in local timezone, causing wrong comparisons with UTC now().
patch(
    "hc/api/models.py",
    '            result = next(CronSim(self.schedule, last_local))\n'
    '            # Important: convert from the local timezone back to UTC.\n'
    '            # If the result is kept in the local timezone, adding\n'
    '            # a timedelta to it later (in `going_down_after` and in `get_status`)\n'
    '            # may yield incorrect results during DST transitions.\n'
    '            result = result.astimezone(timezone.utc)',
    '            result = next(CronSim(self.schedule, last_local))',
)

# Bug 2: models.py to_dict() — next_ping shows last_ping instead of get_grace_start().
patch(
    "hc/api/models.py",
    '"next_ping": isostring(self.get_grace_start()),',
    '"next_ping": isostring(self.last_ping),',
)

# Bug 3: views.py badge() — swap priority so grace overrides down.
patch(
    "hc/api/views.py",
    '        if check_status == "down":\n'
    '            down += 1\n'
    '            status = "down"\n'
    '            if fmt == "svg":\n'
    '                # For SVG badges, we can leave the loop as soon as we\n'
    '                # find the first "down"\n'
    '                break\n'
    '        elif check_status == "grace":\n'
    '            grace += 1\n'
    '            if status == "up" and with_late:\n'
    '                status = "late"',
    '        if check_status == "grace":\n'
    '            grace += 1\n'
    '            if with_late:\n'
    '                status = "late"\n'
    '        elif check_status == "down":\n'
    '            down += 1\n'
    '            status = "down"\n'
    '            if fmt == "svg":\n'
    '                break',
)

# Bug 4: lib/badges.py — late color changed to green (#4c1) instead of orange.
patch(
    "hc/lib/badges.py",
    'COLORS = {"up": "#4c1", "late": "#fe7d37", "down": "#e05d44"}',
    'COLORS = {"up": "#4c1", "late": "#4c1", "down": "#e05d44"}',
)

print("All 4 bugs injected.")
