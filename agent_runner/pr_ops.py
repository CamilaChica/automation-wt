import json
import urllib.request
from typing import Optional


def create_pull_request(
    owner: str,
    repo: str,
    token: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str,
    draft: bool = True,
) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = {
        "title": title,
        "body": body,
        "head": head_branch,
        "base": base_branch,
        "draft": draft,
    }
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, method="POST")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as response:
        body_data = json.loads(response.read().decode("utf-8"))

    pr_url = body_data.get("html_url")
    if not pr_url:
        raise RuntimeError("GitHub API did not return pull request URL")
    return str(pr_url)


def post_issue_comment(owner: str, repo: str, issue_number: int, token: str, body: str) -> Optional[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    payload = {"body": body}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, method="POST")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req) as response:
        body_data = json.loads(response.read().decode("utf-8"))

    return body_data.get("html_url")
