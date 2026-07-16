import re
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
