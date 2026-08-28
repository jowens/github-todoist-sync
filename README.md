# github-todoist-sync

Turns GitHub assignments (issues assigned to you, PRs assigned to you, PR
review requests) into Todoist tasks, automatically, across **every** repo
you have access to — including ones that don't exist yet. No per-repo setup,
ever: it works by polling your GitHub notifications feed, which is
account-wide, not repo-by-repo.

Runs on a schedule via GitHub Actions. No third-party service, no vendor
that can quietly cut off a free tier.

## Why this repo is public

GitHub Actions minutes are unlimited and free on public repos, regardless of
how often the workflow runs. There's nothing sensitive in this code — your
actual credentials live only in encrypted repo secrets (below), which stay
hidden even in a public repo. Keeping it public is what makes "runs every 15
minutes, forever, for free" a guarantee rather than something that depends on
GitHub's free-minutes quota never changing.

If you'd strongly rather this repo be private, that's fine too — just edit
`.github/workflows/sync.yml` and change the cron schedule from `*/15 * * * *`
to `*/30 * * * *` (every 30 min instead of 15), which comfortably fits in the
2,000 free Actions minutes/month that private repos get on the Free/Pro plan.

## One-time setup

1. **Create a GitHub personal access token** (classic — the notifications API
   doesn't support fine-grained tokens):
   - Go to https://github.com/settings/tokens → "Generate new token (classic)"
   - Scopes: check **`notifications`** and **`repo`** (repo is required to see
     notifications from private repositories)
   - Set whatever expiration you're comfortable with (you'll need to rotate
     this token and update the secret when it expires)
   - Copy the token — you won't be able to see it again

2. **Get your Todoist API token:**
   - Todoist → Settings → Integrations → Developer tab → copy the API token

3. **Add both as repo secrets** (in this repo: Settings → Secrets and
   variables → Actions → New repository secret):
   - `GH_PAT` = the GitHub token from step 1
   - `TODOIST_TOKEN` = the Todoist token from step 2

4. **Trigger a test run:** Actions tab → "Sync GitHub assignments to Todoist"
   → "Run workflow". Check the run's log — it'll print how many notifications
   it found and which tasks it created. If it says "Fetched 0 notifications",
   that's expected if nothing's been assigned to you in the last 2 hours; use
   a real issue assignment to test if you want certainty.

That's it. From here it runs unattended every 15 minutes.

## What lands in Todoist

New tasks go to your Todoist **Inbox**, formatted like:

```
[GH] Issue assigned: Fix the flaky CI test (myorg/paper-repo#42)
```

with the GitHub URL in the task's description field. Want them in a specific
project instead, or want the format changed? Edit `build_task()` in
`sync.py` — e.g. add `"project_id": "<id>"` to the `body` dict in
`create_todoist_task()`.

## How it avoids duplicates and silent gaps

Every run re-scans the last 2 hours of your GitHub notifications (not just
"since last time") and skips any it's already turned into a Todoist task,
tracked by notification ID in `state.json`, which the workflow commits back
to the repo after each run. That means a single failed or delayed run can't
create a silent gap — the next run's window overlaps it many times over.

## How you'll know if it breaks

Failed runs show up with a red X on the repo's Actions tab, and if you
haven't disabled it, GitHub emails you by default when a scheduled workflow
run fails. Worth double-checking your notification settings
(https://github.com/settings/notifications, under "Actions") so those
emails actually reach you.

## Scope

Catches, account-wide:
- Issues assigned to you (`reason: assign`, subject type `Issue`)
- PRs assigned to you (`reason: assign`, subject type `PullRequest`)
- PRs where your review was requested (`reason: review_requested`)

To narrow this (e.g. issues only), edit the `REASONS` set at the top of
`sync.py`.
