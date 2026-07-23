import re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

ROOT = Path(__file__).resolve().parents[2]
WIKIPEDIA_CSS = f"""
<style id="legacy-proxy-wikipedia">
{(ROOT/"css"/"wikipedia.css").read_text(encoding="utf-8")}
</style>
"""
WIKIPEDIA_JS = f"""
<script id="legacy-proxy-wikipedia-script">
{(ROOT/"js"/"wikipedia.js").read_text(encoding="utf-8")}
</script>
"""

def is_wikipedia_host(host):
    host = host.lower().rstrip(".")
    return host == "wikipedia.org" or host.endswith(".wikipedia.org")

class WikipediaProxy:
    def request(self,flow):
        #if the request is not for a wikipedia image, ignore it
        if (
            not is_wikipedia_host(flow.request.pretty_host)
            or not flow.request.path.startswith("/legacy-proxy-wikipedia-image/")
        ):
            return False

        #rewrite the request to point to the original image
        image_parts = urlsplit(flow.request.url)
        image_path = "/"+image_parts.path[len("/legacy-proxy-wikipedia-image/"):]
        flow.request.url = urlunsplit(
            ("https","upload.wikimedia.org",image_path,image_parts.query,"")
        )
        flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
        return True

    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","")
        if not is_wikipedia_host(flow.request.pretty_host) or "text/html" not in content_type:
            return False

        html = flow.response.text
        image_prefix = (
            "https://"+flow.request.pretty_host+"/legacy-proxy-wikipedia-image/"
        )
        html = html.replace("https://upload.wikimedia.org/",image_prefix)
        html = html.replace("//upload.wikimedia.org/",image_prefix)
        html = re.sub(
            r'\s+(?:srcset|loading|decoding)=(?:"[^"]*"|\'[^\']*\')',
            "",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r'<button\b(?=[^>]*\bid=["\']searchIcon["\'])(?P<attrs>[^>]*)>'
            r'(?P<body>.*?)</button>',
            lambda match: (
                '<a'+match.group("attrs")
                +' href="/wiki/Special:Search">'
                +match.group("body")+"</a>"
            ),
            html,
            count=1,
            flags=re.IGNORECASE|re.DOTALL,
        )
        if 'id="legacy-proxy-wikipedia"' not in html:
            html = html.replace("</head>",WIKIPEDIA_CSS+"</head>",1)
        if 'id="legacy-proxy-wikipedia-script"' not in html:
            html = html.replace("</body>",WIKIPEDIA_JS+"</body>",1)
        flow.response.text = html
        return True
