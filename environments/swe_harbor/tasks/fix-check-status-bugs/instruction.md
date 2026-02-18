# Fix Check Status and Badge Bugs

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs. Several interacting bugs have been reported across the status computation, API serialization, and badge rendering code. You must find and fix **all** of them — partial fixes will not resolve the issues because the bugs cascade across different parts of the system.

## Reported symptoms

### 1. Cron-based checks show wrong status

Checks configured with a **cron schedule** (not simple timeout) report incorrect status. A cron check that should be in **grace period** or **down** is instead shown as **up**. The issue appears to be related to timezone handling when calculating when the next ping is expected. Simple (timeout-based) checks are unaffected.

### 2. The `next_ping` field in API responses is wrong

When fetching a check via the API, the **`next_ping`** field always equals `last_ping` instead of showing the next expected ping time. This affects all check types. The serialization logic that produces the API response is returning the wrong datetime for this field.

### 3. Badge aggregation shows "late" when it should show "down"

The **badge API** (the endpoint that returns SVG/JSON/Shields badges for a tag or project) has a status priority bug. When one check is **down** and another is in **grace period**, the badge should show **"down"** (the worst status), but instead it shows **"late"**. The aggregation logic in the badge view has the priority order reversed.

### 4. Badge color for "late" status is wrong

The badge rendering uses **green** (`#4c1`) for the **"late"** status instead of the correct **orange/warning** color (`#fe7d37`). This means even when the badge correctly reports a "late" status, it visually appears as healthy/green.

## What to do

Search the codebase to find the root cause of each symptom. The bugs are in different parts of the system — status computation, API serialization, badge view logic, and badge rendering. Fix all four issues. Do not assume file names or function names; trace the behavior through the code.

## Constraints

- Do not modify existing tests outside this task's `tests/` directory.
- All four bugs must be fixed for the system to behave correctly; fixing only some will still produce wrong results due to how they interact.
- Preserve existing behavior for simple (timeout-based) checks, which are unaffected by bug #1.
