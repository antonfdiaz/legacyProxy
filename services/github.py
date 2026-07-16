import re
from pathlib import Path

GITHUB_HOSTS = {"github.com","www.github.com"}
GITHUB_VIEWPORT = '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
GITHUB_CSS = f"""
<style id="legacy-proxy-github">
{(Path(__package__).parent/"css"/"github.css").read_text(encoding="utf-8")}
</style>
"""

class GitHubProxy:
    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","")
        if flow.request.pretty_host not in GITHUB_HOSTS or "text/html" not in content_type:
            return False

        html = flow.response.text
        if 'id="legacy-proxy-github"' in html:
            return True
        if 'id="js-repo-pjax-container"' not in html:
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
        html = html.replace("</head>",GITHUB_CSS+"</head>",1)
        flow.response.text = html
        return True
