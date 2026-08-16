import json
import re
from html import escape
from pathlib import Path

GITHUB_HOSTS = {"github.com","www.github.com"}
GITHUB_AUTH_PATHS = (
    "/login",
    "/session",
    "/sessions",
    "/signup",
    "/password_reset",
    "/two-factor-authentication",
)
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
GITHUB_HEADER = """
<header id="legacy-github-header">
    <button id="legacy-github-menu-button" type="button" aria-label="Navigation Menu">
        <span></span>
        <span></span>
        <span></span>
    </button>

    <a id="legacy-github-logo" href="/" aria-label="GitHub">
        <svg viewBox="0 0 16 16" width="28" height="28">
            <path fill-rule="evenodd"
                  d="M8 0C3.58 0 0 3.64 0 8.13c0 3.59 2.29 6.64
                     5.47 7.71.4.08.55-.18.55-.39
                     0-.19-.01-.83-.01-1.5-2.01.38-2.53-.5
                     -2.69-.96-.09-.23-.48-.96-.82-1.15
                     -.28-.15-.68-.52-.01-.53.63-.01
                     1.08.59 1.23.83.72 1.23 1.87.88
                     2.33.67.07-.53.28-.88.51-1.08
                     -1.78-.21-3.64-.91-3.64-4.02
                     0-.89.31-1.62.82-2.19-.08-.21
                     -.36-1.04.08-2.16 0 0 .67-.22
                     2.2.84A7.42 7.42 0 0 1 8 3.87
                     c.68 0 1.36.09 2 .27 1.53-1.06
                     2.2-.84 2.2-.84.44 1.12.16
                     1.95.08 2.16.51.57.82 1.3
                     .82 2.19 0 3.12-1.87 3.81-3.65
                     4.02.29.26.54.75.54 1.52
                     0 1.1-.01 1.99-.01 2.27
                     0 .21.15.47.55.39A8.16 8.16
                     0 0 0 16 8.13C16 3.64 12.42 0 8 0z"/>
        </svg>
    </a>

    <a id="legacy-github-signin" href="/login">
        Sign in
    </a>

    <button id="legacy-github-settings" type="button" aria-label="Appearance settings">
        <svg viewBox="0 0 16 16"
            width="16"
            height="16"
            aria-hidden="true">
            <path d="M2 4h3M9 4h5M5 2v4M2 8h7M13 8h1M9 6v4M2 12h2M8 12h6M4 10v4"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"/>
        </svg>
    </button>
</header>

<div id="legacy-github-drawer">
    <a href="/features">Platform</a>
    <a href="/solutions">Solutions</a>
    <a href="/resources">Resources</a>
    <a href="/open-source">Open Source</a>
    <a href="/enterprise">Enterprise</a>
    <a href="/pricing">Pricing</a>

    <form action="/search" method="get">
        <input type="text"
               name="q"
               placeholder="Search">
    </form>

    <a class="legacy-github-signup" href="/signup">
        Sign up
    </a>
</div>
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
        path = flow.request.path.split("?",1)[0]
        auth_page = any(
            path == auth_path or path.startswith(auth_path+"/")
            for auth_path in GITHUB_AUTH_PATHS
        )
        if ('id="js-repo-pjax-container"' not in html and
                'js-profile-editable-area' not in html and not auth_page):
            return False

        html = re.sub(
            r'(<body\b[^>]*>)',
            lambda match: match.group(1)+GITHUB_HEADER,
            html,
            count=1,
            flags=re.IGNORECASE,
        )
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
