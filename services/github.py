import json
import re
from html import escape
from pathlib import Path

GITHUB_HOSTS = {"github.com","www.github.com"}
GITHUB_VIEWPORT = '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
GITHUB_CSS = f"""
<style id="legacy-proxy-github">
{(Path(__package__).parent/"css"/"github.css").read_text(encoding="utf-8")}
</style>
"""
GITHUB_JS = f"""
<script id="legacy-proxy-github-script">
{(Path(__package__).parent/"js"/"github.js").read_text(encoding="utf-8")}
</script>
"""

def issue_timeline(html):
    data_match = re.search(
        r'<script type="application/json" data-target="react-app\.embeddedData">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if not data_match or 'data-testid="issue-viewer-container"' not in html:
        return html

    try:
        data = json.loads(data_match.group(1))
        issue = data["payload"]["preloadedQueries"][0]["result"]["data"]["repository"]["issue"]
    except (json.JSONDecodeError,KeyError,IndexError,TypeError):
        return html

    items = (
        issue.get("frontTimelineItems",{}).get("edges",[])+
        issue.get("backTimelineItems",{}).get("edges",[])
    )
    timeline = []
    for edge in items:
        item = edge.get("node",{})
        item_type = item.get("__typename","")
        actor = item.get("author") or item.get("actor") or {}
        actor_name = actor.get("login","GitHub")
        actor_url = actor.get("profileUrl") or actor.get("url") or f"/{actor_name}"
        created = item.get("createdAt","")

        if item_type == "IssueComment":
            timeline.append(
                '<article class="legacy-issue-comment">'
                '<div class="legacy-issue-comment-header">'
                f'<a href="{escape(actor_url,quote=True)}">{escape(actor_name)}</a>'
                f' commented <relative-time datetime="{escape(created,quote=True)}">'
                f'{escape(created[:10])}</relative-time>'
                '</div>'
                f'<div class="markdown-body">{item.get("bodyHTML","")}</div>'
                '</article>'
            )
        elif item_type in {"ClosedEvent","ReopenedEvent"}:
            action = "closed" if item_type == "ClosedEvent" else "reopened"
            timeline.append(
                '<div class="legacy-issue-event">'
                f'<a href="{escape(actor_url,quote=True)}">{escape(actor_name)}</a> '
                f'{action} this issue'
                f' <relative-time datetime="{escape(created,quote=True)}">'
                f'{escape(created[:10])}</relative-time>'
                '</div>'
            )

    replacement = '<div class="legacy-issue-timeline">'+"".join(timeline)+"</div>"
    return re.sub(
        r'<div\b(?=[^>]*data-testid="issue-timeline-loading")[^>]*>.*?(?=<div\b[^>]*data-testid="issue-viewer-metadata-container")',
        replacement,
        html,
        count=1,
        flags=re.DOTALL,
    )

class GitHubProxy:
    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","")
        if flow.request.pretty_host not in GITHUB_HOSTS or "text/html" not in content_type:
            return False

        html = flow.response.text
        if 'id="legacy-proxy-github"' in html:
            return True
        if ('id="js-repo-pjax-container"' not in html and
                'js-profile-editable-area' not in html):
            return False

        html = re.sub(
            r'<link\b(?=[^>]*\brel=["\']stylesheet["\'])(?=[^>]*github\.githubassets\.com)[^>]*>',
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r'<meta\b(?=[^>]*\bname=["\']viewport["\'])[^>]*>',
            GITHUB_VIEWPORT,
            html,
            count=1,
            flags=re.IGNORECASE,
        )
        html = issue_timeline(html)
        html = html.replace("</head>",GITHUB_CSS+"</head>",1)
        html = html.replace("</body>",GITHUB_JS+"</body>",1)
        flow.response.text = html

        content_security_policy = flow.response.headers.get("Content-Security-Policy","")
        script_policy = re.search(r"script-src\s+([^;]+)",content_security_policy)
        if script_policy and "'unsafe-inline'" not in script_policy.group(1):
            content_security_policy = re.sub(
                r"script-src\s+",
                "script-src 'unsafe-inline' ",
                content_security_policy,
                count=1,
            )
            flow.response.headers["Content-Security-Policy"] = content_security_policy
        return True
