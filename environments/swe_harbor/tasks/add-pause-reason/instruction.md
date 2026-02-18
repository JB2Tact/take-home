# Add Pause Reason

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

When a user pauses a check via the **API**, they may optionally send a **reason** (e.g. "maintenance window"). That reason must be stored, returned whenever the API returns check data (e.g. GET single check, or the response body of pause/resume), and **cleared** when the check is resumed via the API.

**Scope:** Only the **API** pause and resume behavior is in scope. Do not modify front-end or other apps.

**You must discover where to implement this.** The API already has endpoints that pause and resume a check. Find those endpoints (the code that runs when the client POSTs to pause or resume). Find where the check model is defined and where check data is serialized for API responses—that serialization is used by GET single check and by the pause/resume responses. Your solution extends that existing behavior; do not assume file or function names.

## 1. Store the reason on the check

Add one new field on the check model (the same model that has `status` and is used by the pause/resume logic):

- **`pause_reason`** — `CharField(max_length=500, blank=True, default="")`

Place it near other check state (e.g. near the `status` field). Then create and run a migration (use a descriptive name like `pause_reason`).

## 2. Expose the reason in API responses

Find the code that builds the dictionary (or similar) used when the API returns a check—e.g. for GET single check and for the JSON body of the pause and resume endpoints. That serialization likely lives near the check model or in a method that “turns a check into a dict for the API.” Add a key **`"pause_reason"`** to that output:

- When the check is **paused**, use the stored reason (the new field).
- When the check is **not** paused, use **`""`** so the key is always present.

If the codebase uses a TypedDict or similar for that serialized shape, add **`pause_reason: str`** there too.

## 3. Pause endpoint: accept optional reason

Find the view (or handler) that runs when the client POSTs to pause a check. It already sets the check’s status to paused and saves. In addition:

- Read **`reason`** from the request body (e.g. from the parsed JSON, with a default of `""`).
- If the client sends a **`reason`** key:
  - The value **must be a string**. If it is not (e.g. number, array, object), return **400** with **`{"error": "reason must be a string"}`**.
  - Otherwise, strip whitespace and store at most **500 characters** in the new field before saving.
- If **`reason`** is missing or empty/whitespace-only, set the new field to **`""`** before save.

Do not change the existing pause logic (e.g. flip creation, status, last_start, alert_after, or similar).

## 4. Resume endpoint: clear the reason

Find the view (or handler) that runs when the client POSTs to resume a check. When it sets the check back to active and saves, set the **pause_reason** field to **`""`** so that after resume the reason is cleared. Do not change the rest of the resume logic.

## Constraints

- Do not modify existing tests outside this task's **`tests/`** directory.
- Follow existing patterns (e.g. how the request body is read, how JSON responses and errors are returned).
- Max length for the stored reason is **500** characters (enforce in the pause handler when saving).
