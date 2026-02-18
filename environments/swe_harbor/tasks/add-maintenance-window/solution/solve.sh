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

# --- 3. Run migration ---
python manage.py makemigrations api --name maintenance_window
python manage.py migrate

# --- 4. In sendalerts notify(): skip sending down alerts when check in maintenance ---
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
