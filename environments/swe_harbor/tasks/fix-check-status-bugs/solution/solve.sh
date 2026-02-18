#!/bin/bash
set -e
cd /app

# Fix Bug 1: models.py get_grace_start() — restore UTC conversion for cron checks.
python3 << 'FIX1'
with open("hc/api/models.py") as f:
    content = f.read()

old = (
    '            result = next(CronSim(self.schedule, last_local))\n'
    '        elif self.kind == "oncalendar"'
)

new = (
    '            result = next(CronSim(self.schedule, last_local))\n'
    '            # Important: convert from the local timezone back to UTC.\n'
    '            # If the result is kept in the local timezone, adding\n'
    '            # a timedelta to it later (in `going_down_after` and in `get_status`)\n'
    '            # may yield incorrect results during DST transitions.\n'
    '            result = result.astimezone(timezone.utc)\n'
    '        elif self.kind == "oncalendar"'
)

if old in content:
    content = content.replace(old, new, 1)
    with open("hc/api/models.py", "w") as f:
        f.write(content)
FIX1

# Fix Bug 2: models.py to_dict() — restore next_ping to use get_grace_start().
python3 << 'FIX2'
with open("hc/api/models.py") as f:
    content = f.read()

old = '"next_ping": isostring(self.last_ping),'
new = '"next_ping": isostring(self.get_grace_start()),'

if old in content:
    content = content.replace(old, new, 1)
    with open("hc/api/models.py", "w") as f:
        f.write(content)
FIX2

# Fix Bug 3: views.py badge() — restore correct priority (down > grace).
python3 << 'FIX3'
with open("hc/api/views.py") as f:
    content = f.read()

old = (
    '        if check_status == "grace":\n'
    '            grace += 1\n'
    '            if with_late:\n'
    '                status = "late"\n'
    '        elif check_status == "down":\n'
    '            down += 1\n'
    '            status = "down"\n'
    '            if fmt == "svg":\n'
    '                break'
)

new = (
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
    '                status = "late"'
)

if old in content:
    content = content.replace(old, new, 1)
    with open("hc/api/views.py", "w") as f:
        f.write(content)
FIX3

# Fix Bug 4: lib/badges.py — restore correct late color (orange).
python3 << 'FIX4'
with open("hc/lib/badges.py") as f:
    content = f.read()

old = 'COLORS = {"up": "#4c1", "late": "#4c1", "down": "#e05d44"}'
new = 'COLORS = {"up": "#4c1", "late": "#fe7d37", "down": "#e05d44"}'

if old in content:
    content = content.replace(old, new, 1)
    with open("hc/lib/badges.py", "w") as f:
        f.write(content)
FIX4

echo "All 4 bugs fixed."
