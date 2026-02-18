#!/bin/bash
set -e

# --- add the Note model to the end of models.py ---
cat >> /app/hc/api/models.py << 'PYEOF'
class Note(models.Model):
    code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    owner = models.ForeignKey(Check, models.CASCADE, related_name="notes")
    created = models.DateTimeField(default=now)
    body = models.TextField()

    class Meta:
        ordering = ["-created"]

    def to_dict(self) -> dict:
        return {
            "uuid": str(self.code),
            "created": isostring(self.created),
            "body": self.body,
        }
PYEOF

# create the DB migration and apply it (so the notes table actually exists)
cd /app
python manage.py makemigrations api --name check_notes
python manage.py migrate

# --- add the API views at the end of views.py ---
# list_notes = GET handler, create_note = POST handler, check_notes = routes to one of them
cat >> /app/hc/api/views.py << 'VIEWEOF'


@authorize_read
def list_notes(request: ApiRequest, code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    from hc.api.models import Note

    q = Note.objects.filter(owner=check)
    return JsonResponse({"notes": [n.to_dict() for n in q]})


@authorize
def create_note(request: ApiRequest, code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    from hc.api.models import Note

    if check.notes.count() >= 50:
        return JsonResponse({"error": "too many notes"}, status=403)

    body = request.json.get("body", "")
    if not isinstance(body, str) or not body.strip():
        return JsonResponse({"error": "body is required"}, status=400)
    if len(body) > 1000:
        return JsonResponse({"error": "body is too long"}, status=400)

    note = Note(owner=check, body=body.strip())
    note.save()

    return JsonResponse(note.to_dict(), status=201)


@csrf_exempt
@cors("GET", "POST")
def check_notes(request: HttpRequest, code: UUID) -> HttpResponse:
    if request.method == "POST":
        return create_note(request, code)
    return list_notes(request, code)
VIEWEOF

# --- wire up the URL: add the notes route to api_urls (in urls.py, not views!) ---
# we find one existing line and replace it with that line plus our new path
cd /app
python3 << 'PATCH'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '''    path("channels/", views.channels),'''

new = '''    path("checks/<uuid:code>/notes/", views.check_notes, name="hc-api-notes"),
    path("channels/", views.channels),'''

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)
PATCH
