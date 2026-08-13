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

def _add_webkit_prefixes(css):
    props = (
        "transform|transition|animation|appearance|user-select|"
        "flex|flex-grow|flex-shrink|flex-basis|flex-direction|flex-wrap|"
        "align-items|align-self|align-content|justify-content|order"
    )

    css = re.sub(
        rf'(?i)(?<!-webkit-)\b({props})\s*:\s*([^;}}]+)',
        r'-webkit-\1: \2; \1: \2',
        css,
    )

    css = re.sub(
        r'(?i)\bdisplay\s*:\s*flex\s*;',
        'display: -webkit-flex; display: flex;',
        css,
    )

    css = re.sub(
        r'(?i)\bdisplay\s*:\s*inline-flex\s*;',
        'display: -webkit-inline-flex; display: inline-flex;',
        css,
    )

    # Modern alignment keywords -> older flexbox equivalents
    css = re.sub(
        r'(?i)(justify-content|align-items|align-self)\s*:\s*end\b',
        lambda m: f'{m.group(1)}: flex-end',
        css,
    )

    css = re.sub(
        r'(?i)(justify-content|align-items|align-self)\s*:\s*start\b',
        lambda m: f'{m.group(1)}: flex-start',
        css,
    )

    return css

def _resolve_root_variables(css):
    variables = {}

    for block in re.findall(
        r':root\s*\{(.*?)\}',
        css,
        flags=re.I | re.S
    ):
        for name, value in re.findall(
            r'(--[\w-]+)\s*:\s*([^;]+);',
            block
        ):
            variables[name] = value.strip()

    def replace_var(match):
        name = match.group(1)
        fallback = match.group(2)

        if name in variables:
            return variables[name]

        if fallback:
            return fallback.strip()

        return match.group(0)

    return re.sub(
        r'var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)',
        replace_var,
        css
    )
    
def _expand_inset(css):
    def repl(match):
        value = match.group(1).strip()

        return (
            f"top: {value}; "
            f"right: {value}; "
            f"bottom: {value}; "
            f"left: {value};"
        )

    return re.sub(
        r'(?i)\binset\s*:\s*([^;}]+)\s*;?',
        repl,
        css,
    )
    
def _convert_modern_rgb(css):
    def repl(match):
        r = match.group(1)
        g = match.group(2)
        b = match.group(3)
        alpha = float(match.group(4)) / 100.0

        return f"rgba({r}, {g}, {b}, {alpha:g})"

    return re.sub(
        r'rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*/\s*(\d+(?:\.\d+)?)%\s*\)',
        repl,
        css,
        flags=re.I,
    )
    
def _replace_safe_unset(css):
    replacements = {
        "box-shadow": "none",
        "background": "none",
        "height": "auto",
        "width": "auto",
        "overflow": "visible",
        "overflow-x": "visible",
        "overflow-y": "visible",
    }

    for prop, fallback in replacements.items():
        css = re.sub(
            rf'(?i)\b{re.escape(prop)}\s*:\s*unset\s*;',
            f'{prop}: {fallback};',
            css,
        )

    return css

def adapt_css(css):
    css = _add_webkit_prefixes(css)
    css = _resolve_root_variables(css)
    css = _expand_inset(css)
    css = _convert_modern_rgb(css)
    css = _replace_safe_unset(css)
    return css