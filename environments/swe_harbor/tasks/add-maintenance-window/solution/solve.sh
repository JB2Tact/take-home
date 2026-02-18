#!/bin/bash
set -e

cd /app

# --- 1. Add maintenance_start, maintenance_end to Check (after status) ---
python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """    alert_after = models.DateTimeField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=6, choices=STATUSES, default="new")

    class Meta:
        indexes = ["""

new = """    alert_after = models.DateTimeField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=6, choices=STATUSES, default="new")
    maintenance_start = models.DateTimeField(null=True, blank=True)
    maintenance_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = ["""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

# --- 2. Add in_maintenance_window() on Check (after __str__) ---
python3 << 'PATCH2'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """    def __str__(self) -> str:
        return "%s (%d)" % (self.name or self.code, self.id)

    def name_then_code(self) -> str:
        if self.name:
            return self.name

        return str(self.code)"""

new = """    def __str__(self) -> str:
        return "%s (%d)" % (self.name or self.code, self.id)

    def in_maintenance_window(self) -> bool:
        if self.maintenance_start is None or self.maintenance_end is None:
            return False
        t = now()
        return self.maintenance_start <= t < self.maintenance_end

    def name_then_code(self) -> str:
        if self.name:
            return self.name

        return str(self.code)"""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH2

# --- 3. Add maintenance_start, maintenance_end to CheckDict TypedDict ---
python3 << 'PATCH2B'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """    pause_url: str
    resume_url: str
    channels: str
    timeout: int
    schedule: str
    tz: str"""

new = """    pause_url: str
    resume_url: str
    channels: str
    maintenance_start: str | None
    maintenance_end: str | None
    timeout: int
    schedule: str
    tz: str"""

if old in content:
    content = content.replace(old, new, 1)
else:
    old2 = """    resume_url: str
    channels: str
    timeout: int
    schedule: str
    tz: str"""
    new2 = """    resume_url: str
    channels: str
    maintenance_start: str | None
    maintenance_end: str | None
    timeout: int
    schedule: str
    tz: str"""
    content = content.replace(old2, new2, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH2B

# --- 4. Add maintenance_start, maintenance_end to to_dict() ---
python3 << 'PATCH2C'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """            "filter_subject": self.filter_subject,
            "filter_body": self.filter_body,
        }

        if self.last_duration:"""

new = """            "filter_subject": self.filter_subject,
            "filter_body": self.filter_body,
            "maintenance_start": isostring(self.maintenance_start),
            "maintenance_end": isostring(self.maintenance_end),
        }

        if self.last_duration:"""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH2C

# --- 5. Run migration ---
python manage.py makemigrations api --name maintenance_window
python manage.py migrate

# --- 6. Add maintenance_start, maintenance_end to Spec in views.py ---
python3 << 'PATCH4'
with open("hc/api/views.py", "r") as f:
    content = f.read()

old = """    tz: str | None = None
    unique: list[Literal["name", "slug", "tags", "timeout", "grace"]] | None = None"""

new = """    tz: str | None = None
    maintenance_start: str | None = None
    maintenance_end: str | None = None
    unique: list[Literal["name", "slug", "tags", "timeout", "grace"]] | None = None"""

content = content.replace(old, new, 1)
with open("hc/api/views.py", "w") as f:
    f.write(content)
PATCH4

# --- 7. Handle maintenance_start/end in _update() in views.py ---
python3 << 'PATCH5'
with open("hc/api/views.py", "r") as f:
    content = f.read()

old = """    if need_save:
        check.alert_after = check.going_down_after()
        check.save()

    # This needs to be done after saving the check, because of
    # the M2M relation between checks and channels:
    if new_channels is not None:
        check.channel_set.set(new_channels)"""

new = """    if spec.maintenance_start is not None:
        if spec.maintenance_start == "":
            check.maintenance_start = None
        else:
            from datetime import datetime as _dt
            check.maintenance_start = _dt.fromisoformat(spec.maintenance_start)
        need_save = True

    if spec.maintenance_end is not None:
        if spec.maintenance_end == "":
            check.maintenance_end = None
        else:
            from datetime import datetime as _dt
            check.maintenance_end = _dt.fromisoformat(spec.maintenance_end)
        need_save = True

    if need_save:
        check.alert_after = check.going_down_after()
        check.save()

    # This needs to be done after saving the check, because of
    # the M2M relation between checks and channels:
    if new_channels is not None:
        check.channel_set.set(new_channels)"""

content = content.replace(old, new, 1)
with open("hc/api/views.py", "w") as f:
    f.write(content)
PATCH5

# --- 8. In sendalerts notify(): skip sending down alerts when check in maintenance ---
python3 << 'PATCH3'
with open("hc/api/management/commands/sendalerts.py", "r") as f:
    content = f.read()

old = """def notify(flip: Flip) -> str | None:
    # First, mark the flip as processed:
    q = Flip.objects.filter(id=flip.id, processed=None)
    num_updated = q.update(processed=now())
    if num_updated != 1:
        # Nothing got updated: another sendalerts process got there first.
        return None

    # Set or clear dates for followup nags
    check = flip.owner"""

new = """def notify(flip: Flip) -> str | None:
    check = flip.owner
    if flip.new_status == "down" and check.in_maintenance_window():
        q = Flip.objects.filter(id=flip.id, processed=None)
        q.update(processed=now())
        return None

    # First, mark the flip as processed:
    q = Flip.objects.filter(id=flip.id, processed=None)
    num_updated = q.update(processed=now())
    if num_updated != 1:
        # Nothing got updated: another sendalerts process got there first.
        return None

    # Set or clear dates for followup nags
    check = flip.owner"""

content = content.replace(old, new, 1)
with open("hc/api/management/commands/sendalerts.py", "w") as f:
    f.write(content)
PATCH3

echo "Solution applied."
