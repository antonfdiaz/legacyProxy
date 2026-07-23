import re
from urllib.parse import urlsplit,urlunsplit

WIKIPEDIA_HOSTS = {"en.wikipedia.org","es.wikipedia.org","fr.wikipedia.org","de.wikipedia.org"}
WIKIPEDIA_CSS = """
<style id="legacy-proxy-wikipedia">
.header-container {
    padding: 0 16px !important;
    background: #eaecf0 !important;
    border-bottom: 1px solid #c8ccd1 !important;
    box-shadow: none !important;
}
.minerva-header {
    display: block !important;
    height: 54px !important;
    border: 0 !important;
}
.minerva-header .navigation-drawer,
.minerva-header .minerva-search-form,
.minerva-header .minerva-user-navigation,
.minerva-header .minerva-badge-container {
    display: none !important;
}
.minerva-header .branding-box {
    display: block !important;
    padding-top: 18px !important;
}
.minerva-header .branding-box a {
    float: left !important;
    margin-left: 0 !important;
}
.page-actions-menu {
    border-top: 1px solid #dadde3 !important;
    border-bottom: 1px solid #c8ccd1 !important;
}
.page-actions-menu__list {
    display: table !important;
    width: 100% !important;
    height: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    table-layout: fixed !important;
}
.page-actions-menu__list-item {
    display: table-cell !important;
    list-style: none !important;
    text-align: center !important;
}
.page-actions-menu .minerva-icon {
    display: none !important;
}
.page-actions-menu .cdx-button {
    display: block !important;
    min-width: 0 !important;
    min-height: 0 !important;
    padding: 8px 4px !important;
    border: 0 !important;
    background: transparent !important;
    color: #36c !important;
    font: inherit !important;
    text-decoration: none !important;
}
.page-actions-menu .cdx-button span + span {
    position: static !important;
    clip: auto !important;
    width: auto !important;
    height: auto !important;
    margin: 0 !important;
    overflow: visible !important;
}
.mw-parser-output img,
.mw-parser-output .infobox {
    max-width: 100% !important;
}
.mw-parser-output img {
    height: auto !important;
}
</style>
"""

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
        if 'id="legacy-proxy-wikipedia"' not in html:
            html = html.replace("</head>",WIKIPEDIA_CSS+"</head>",1)
        flow.response.text = html
        return True
