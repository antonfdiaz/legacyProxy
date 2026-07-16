import re
from urllib.parse import urlsplit,urlunsplit

WIKIPEDIA_HOSTS = {"en.wikipedia.org","es.wikipedia.org","fr.wikipedia.org","de.wikipedia.org"}

class WikipediaProxy:
    def request(self,flow):
        #if the request is not for a wikipedia image, ignore it
        if (
            flow.request.pretty_host not in WIKIPEDIA_HOSTS
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
        if flow.request.pretty_host not in WIKIPEDIA_HOSTS or "text/html" not in content_type:
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
        flow.response.text = html
        return True
