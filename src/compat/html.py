import re

def adapt_html(html):
    #modern attributes that old webkit doesn't need
    html = re.sub(
        r'\s+(?:srcset|loading|decoding|fetchpriority|inert)'
        r'=(?:"[^"]*"|\'[^\']*\')',
        "",
        html,
        flags=re.IGNORECASE,
    )

    #boolean inert attribute without value
    html = re.sub(
        r'\s+inert(?=\s|>)',
        "",
        html,
        flags=re.IGNORECASE,
    )

    #promote common lazy load attributes to src
    html = re.sub(
        r'<img\b([^>]*?)\s(?:data-src|data-original|data-lazy-src)'
        r'=["\']([^"\']+)["\']([^>]*)>',
        _adapt_lazy_img,
        html,
        flags=re.IGNORECASE,
    )

    #simplify <picture> to its fallback <img>
    html = re.sub(
        r'<picture\b[^>]*>.*?(<img\b[^>]*>).*?</picture>',
        r'\1',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return html

def _adapt_lazy_img(match):
    before = match.group(1)
    url = match.group(2)
    after = match.group(3)

    attrs = before+after

    attrs = re.sub(
        r'\s+src=(?:"[^"]*"|\'[^\']*\')',
        "",
        attrs,
        flags=re.IGNORECASE,
    )

    return f'<img{attrs} src="{url}">'
