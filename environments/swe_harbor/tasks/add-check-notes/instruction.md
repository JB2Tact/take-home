# Add Check Notes

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

Add a notes feature to the REST API so users can attach a short text note to a check (e.g. "Investigating timeout", "Fixed in deploy"). Each check can have multiple notes.

**You must discover where to implement this.** The app has an API that already supports checks (list, get, pause, resume) and other sub-resources under a check (e.g. pings, flips). Find where the Check model lives, where API routes are registered, and where similar “list/create under a check” endpoints are implemented. Follow those patterns; do not assume file names or function names—search the codebase.

## 1. Note model

Add a new model for notes, in the same app/module where the Check model is defined (so migrations and imports stay consistent). The model must have:

| Field | Type | Details |
|-------|------|---------|
| `code` | `UUIDField` | `default=uuid.uuid4, editable=False, unique=True` |
| `owner` | `ForeignKey` to `Check` | `on_delete=models.CASCADE, related_name="notes"` |
| `created` | `DateTimeField` | `default=now` |
| `body` | `TextField` | no max_length on model; enforce 1000 chars in API |

Add a `to_dict()` method returning: `uuid` (str of code), `created` (ISO 8601, no microseconds—use the same datetime helper already used elsewhere in the codebase for API responses), `body`.

Set `Meta.ordering = ["-created"]`.

## 2. Migration

Generate a migration for the new model (use a descriptive name like `check_notes`) and run `migrate`. The migration must live in the same migrations directory as the rest of the API app.

## 3. API endpoints

Add two behaviors:

- **Create a note for a check:** POST that accepts a JSON body with `body` (required string). Enforce: non-empty after stripping whitespace, max 1000 characters. Return the created note as JSON with status 201. Use the same write-authorization pattern as other check-mutating endpoints (the decorator that requires the project’s write key). Return 400 with `{"error": "..."}` for validation errors (missing/empty/too long body), 403 if the check belongs to another project or if the check already has 50 notes (error message `"too many notes"`), 404 if the check doesn’t exist.

- **List notes for a check:** GET that returns `{"notes": [...]}` (newest first). Use the same read-authorization pattern as other check-reading endpoints. Return 403/404 for wrong project or missing check.

Find where other “under a check” routes are registered (e.g. pings or flips). Register the new notes endpoint under the same URL pattern: something like `checks/<uuid:code>/notes/`, so that the full path is consistent with the existing API versioning (e.g. `/api/v3/checks/<code>/notes/`). Use one view that dispatches GET to the list handler and POST to the create handler, with the same CORS and CSRF handling used for other API views.

## Constraints

- Do not modify existing tests.
- Limit: 50 notes per check; 1000 characters per note body (enforce in the create endpoint).
- Follow existing patterns for decorators, error responses, and datetime formatting.
