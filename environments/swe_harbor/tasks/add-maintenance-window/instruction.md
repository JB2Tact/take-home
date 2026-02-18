# Add Maintenance Window (No Down Alerts During Window)

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs and sending alerts when checks go down.

## What to build

Add an **optional maintenance window** (start and end time) per check. While the current time falls within a check's maintenance window, the system must **not send** "check is down" alerts for that check. Alerts for "up" or other status transitions are unchanged.

**You must discover where to implement this.** The application has logic that decides when to send a down alert (when a check transitions to "down", notifications are sent to channels). Find where that decision is made and where the actual sending happens. Add a condition there: when the alert would be a **down** alert and the check is currently inside its maintenance window, do not send the notification (but do mark the alert as handled so it is not retried). Do not assume file names, command names, or function names—search the codebase.

## 1. Model: store the window on the check

Add two optional datetime fields to the model that represents a check (the same model that has status, grace, etc.). The fields represent the start and end of the maintenance window (e.g. `maintenance_start` and `maintenance_end`). Use nullable/blank so existing checks are unchanged. Generate and run a migration for the API app (use a descriptive migration name).

Define "in maintenance" as: both fields are set, and the current time (timezone-aware now) is greater than or equal to the start and strictly less than the end. You may add a small helper on the check model that returns whether the current time is inside the window; use it from the place that sends alerts.

## 2. Serialization: include the window in API responses

The API endpoint that returns a check's details as JSON uses a serialization method on the model. Find that method and add the two new fields so they appear in the response. Use the same ISO 8601 format used for other datetime fields.

## 3. API: allow setting the window via the update endpoint

The API provides an endpoint to create and update checks. It validates the request body using a schema/spec. Add the two new fields to the validation layer and to the update logic so that clients can set or clear the maintenance window by sending ISO 8601 datetime strings (or empty strings to clear). Discover how the existing fields like `timeout`, `tz`, etc. are validated and applied, and follow the same pattern.

## 4. Behavior: skip sending down alerts when in window

Find the code path that runs when the system sends a "check is down" notification. When that code is about to send for a **down** transition, first check whether the check (the one that transitioned) is currently in its maintenance window. If it is, do not send any channel notifications; still mark the alert as processed so it is not retried. If the check is not in a window (or has no window set), send as today.

Do not change when down alerts are *created* or when the check's status is set to "down"—only change whether the notification is actually sent to channels.

## Constraints

- Do not modify existing tests outside this task's `tests/` directory.
- Down alerts only are suppressed during the window; "up" and other alerts are unchanged.
- Use the same timezone-aware "now" as the rest of the app (e.g. `django.utils.timezone.now`).
- Changes span **at least** the check model, the API views (serialization and update), and the alerting command.
