#!/usr/bin/env python3
"""
Sync GitHub assignments (issues assigned, PRs assigned, PR review requests)
into Todoist as tasks.

Runs as a scheduled GitHub Action. Reads two secrets from the environment:
  GH_PAT          - classic GitHub personal access token, scopes: notifications, repo
  TODOIST_TOKEN   - Todoist API token (Settings > Integrations > Developer)

State (which notifications have already been turned into a Todoist task) is
kept in state.json, which this script rewrites and the workflow commits back
to the repo after every run.

Design notes:
  - We always re-scan the last LOOKBACK_HOURS of GitHub notifications rather
    than trusting a fragile "last checked" cursor, and rely on the
    processed-IDs set for de-duplication. That way a single missed or failed
    run can't create a silent gap in coverage.
  - We use all=true (not just unread) so that reading your GitHub
    notifications inbox for your own purposes never causes a missed task.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

GH_API = "https://api.github.com"
TODOIST_TASKS_API = "https://api.todoist.com/api/v1/tasks"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

LOOKBACK_HOURS = 2       # overlap window scanned every run; runs are every ~15 min
MAX_PROCESSED_IDS = 3000 # cap on how many old IDs we remember, to keep state.json small

# Which notification "reason" values count as "a task assigned to me"
REASONS = {"assign", "review_requested"}


def gh_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-todoist-sync",
    }


def http_request(url, headers=None, data=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = body
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        parsed = json.loads(raw) if raw else None
        return parsed, resp.headers.get("Link", "") or ""


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"processed_ids": [], "last_run_at": None}


def save_state(state):
    # Keep only the most recent MAX_PROCESSED_IDS to bound file size forever.
    state["processed_ids"] = state.get("processed_ids", [])[-MAX_PROCESSED_IDS:]
    state["last_run_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def parse_next_link(link_header):
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return None


def fetch_notifications(token):
    since = (
        datetime.datetime.utcnow() - datetime.timedelta(hours=LOOKBACK_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    notifications = []
    url = f"{GH_API}/notifications?all=true&since={since}&per_page=50"
    headers = gh_headers(token)
    for _ in range(10):  # hard cap on pagination, personal-use volumes never need this
        if not url:
            break
        data, link = http_request(url, headers=headers)
        notifications.extend(data or [])
        url = parse_next_link(link)
    return notifications


def notif_id(n):
    return str(n.get("id") or n["subject"]["url"])


def build_task(n):
    subject = n["subject"]
    repo_full_name = n["repository"]["full_name"]
    reason = n["reason"]
    number = subject["url"].rstrip("/").split("/")[-1]
    kind = "pull" if subject["type"] == "PullRequest" else "issues"
    html_url = f"https://github.com/{repo_full_name}/{kind}/{number}"

    if reason == "review_requested":
        content = f"[GH] Review requested: {subject['title']} ({repo_full_name}#{number})"
    else:
        content = f"[GH] {subject['type']} assigned: {subject['title']} ({repo_full_name}#{number})"

    return content, html_url


def create_todoist_task(token, content, url):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"content": content, "description": url}
    return http_request(TODOIST_TASKS_API, headers=headers, data=body, method="POST")


def main():
    gh_token = os.environ.get("GH_PAT")
    todoist_token = os.environ.get("TODOIST_TOKEN")
    if not gh_token or not todoist_token:
        print("Missing GH_PAT or TODOIST_TOKEN environment variable.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    processed = set(state.get("processed_ids", []))

    try:
        notifications = fetch_notifications(gh_token)
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"GitHub API request failed: {e}", file=sys.stderr)
        sys.exit(1)

    relevant = [n for n in notifications if n.get("reason") in REASONS]
    new_items = [n for n in relevant if notif_id(n) not in processed]

    print(f"Fetched {len(notifications)} notifications, {len(relevant)} relevant, {len(new_items)} new.")

    failures = 0
    for n in new_items:
        content, url = build_task(n)
        try:
            create_todoist_task(todoist_token, content, url)
            processed.add(notif_id(n))
            print(f"Created Todoist task: {content}")
        except urllib.error.HTTPError as e:
            failures += 1
            print(f"Todoist API error for '{content}': {e.code} {e.read().decode(errors='replace')}", file=sys.stderr)
        except urllib.error.URLError as e:
            failures += 1
            print(f"Todoist request failed for '{content}': {e}", file=sys.stderr)

    state["processed_ids"] = list(processed)
    save_state(state)

    if failures:
        print(f"{failures} task(s) failed to create; see log above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
