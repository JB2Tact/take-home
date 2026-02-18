#!/bin/bash
set -e

cd /app

# --- 1. Add pause_reason field to Check model (after status) ---
python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """    alert_after = models.DateTimeField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=6, choices=STATUSES, default="new")

    class Meta:
        indexes = ["""

new = """    alert_after = models.DateTimeField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=6, choices=STATUSES, default="new")
    pause_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        indexes = ["""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

# --- 2. Add pause_reason to CheckDict TypedDict ---
python3 << 'PATCH2'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """    pause_url: str
    resume_url: str
    channels: str
    timeout: int
    schedule: str"""

new = """    pause_url: str
    resume_url: str
    channels: str
    pause_reason: str
    timeout: int
    schedule: str"""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH2

# --- 3. Add pause_reason to to_dict() result ---
python3 << 'PATCH3'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = """            "filter_subject": self.filter_subject,
            "filter_body": self.filter_body,
        }

        if self.last_duration:"""

new = """            "filter_subject": self.filter_subject,
            "filter_body": self.filter_body,
            "pause_reason": self.pause_reason if self.status == "paused" else "",
        }

        if self.last_duration:"""

content = content.replace(old, new, 1)
with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH3

# --- 4. Run migrations ---
python manage.py makemigrations api --name pause_reason
python manage.py migrate

# --- 5. Pause view: read reason, validate string, cap 500, save ---
python3 << 'PATCH4'
with open("hc/api/views.py", "r") as f:
    content = f.read()

old = """    check.status = "paused"
    check.last_start = None
    check.alert_after = None
    check.save()

    # After pausing a check we must check if all checks are up,"""

new = """    check.status = "paused"
    check.last_start = None
    check.alert_after = None
    reason = request.json.get("reason", "")
    if not isinstance(reason, str):
        return JsonResponse({"error": "reason must be a string"}, status=400)
    check.pause_reason = reason.strip()[:500]
    check.save()

    # After pausing a check we must check if all checks are up,"""

content = content.replace(old, new, 1)
with open("hc/api/views.py", "w") as f:
    f.write(content)
PATCH4

# --- 6. Resume view: clear pause_reason ---
python3 << 'PATCH5'
with open("hc/api/views.py", "r") as f:
    content = f.read()

old = """    check.status = "new"
    check.last_start = None
    check.last_ping = None
    check.alert_after = None
    check.save()

    return JsonResponse(check.to_dict(v=request.v))


@cors("GET")
@csrf_exempt
@authorize
def pings(request: ApiRequest, code: UUID) -> HttpResponse:"""

new = """    check.status = "new"
    check.pause_reason = ""
    check.last_start = None
    check.last_ping = None
    check.alert_after = None
    check.save()

    return JsonResponse(check.to_dict(v=request.v))


@cors("GET")
@csrf_exempt
@authorize
def pings(request: ApiRequest, code: UUID) -> HttpResponse:"""

content = content.replace(old, new, 1)
with open("hc/api/views.py", "w") as f:
    f.write(content)
PATCH5
