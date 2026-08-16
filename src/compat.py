import copy
import re
import tinycss2
from tinycss2.ast import Declaration, WhitespaceToken

_PREFIXED_PROPERTIES = {
    "transform","transition","animation","appearance","user-select",
    "flex","flex-grow","flex-shrink","flex-basis","flex-direction",
    "flex-wrap","align-items","align-self","align-content",
    "justify-content","order",
}
_UNSET_FALLBACKS = {
    "box-shadow": "none","background": "none","height": "auto",
    "width": "auto","overflow": "visible","overflow-x": "visible",
    "overflow-y": "visible",
}
_DECLARATION_AT_RULES = {"font-face","page"}
_RULE_AT_RULES = {
    "media","supports","container","document","keyframes","layer",
    "scope","starting-style",
}

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

def _value(css):
    return tinycss2.parse_component_value_list(css)

def _text(tokens):
    return tinycss2.serialize(tokens).strip()

def _is_ident_value(tokens,value):
    meaningful = [token for token in tokens if token.type != "whitespace"]
    return (len(meaningful) == 1 and meaningful[0].type == "ident"
            and meaningful[0].value.lower() == value)

def _new_declaration(name,value,original):
    return Declaration(
        original.source_line,
        original.source_column,
        name,
        name.lower(),
        value,
        original.important,
    )

def _replacement_value(css,original):
    prefix = " " if original.value and original.value[0].type == "whitespace" else ""
    suffix = " " if original.important else ""
    return _value(prefix+css+suffix)

def _separator(node):
    return WhitespaceToken(node.source_line,node.source_column," ")

def _prepare_rules(nodes):
    for node in nodes:
        if node.type == "qualified-rule":
            node.content = tinycss2.parse_blocks_contents(
                node.content,skip_comments=False,skip_whitespace=False)
        elif node.type == "at-rule" and node.content is not None:
            if node.lower_at_keyword in _DECLARATION_AT_RULES:
                node.content = tinycss2.parse_blocks_contents(
                    node.content,skip_comments=False,skip_whitespace=False)
            elif node.lower_at_keyword in _RULE_AT_RULES:
                node.content = tinycss2.parse_blocks_contents(
                    node.content,skip_comments=False,skip_whitespace=False)
                _prepare_rules(node.content)

def _root_variables(nodes):
    variables = {}
    for node in nodes:
        if node.type == "qualified-rule" and _text(node.prelude) == ":root":
            for declaration in node.content:
                if declaration.type == "declaration" and declaration.name.startswith("--"):
                    variables[declaration.name] = declaration.value
        elif (node.type == "at-rule" and node.content is not None
              and node.lower_at_keyword in _RULE_AT_RULES):
            variables.update(_root_variables(node.content))
    return variables

def _replace_variables(tokens,variables):
    result = []
    for token in tokens:
        if token.type == "function" and token.lower_name == "var":
            arguments = token.arguments
            comma = next((i for i, item in enumerate(arguments)
                          if item.type == "literal" and item.value == ","), None)
            name = _text(arguments[:comma] if comma is not None else arguments)
            replacement = variables.get(name)
            if replacement is None and comma is not None:
                replacement = arguments[comma+1:]
            result.extend(copy.deepcopy(replacement) if replacement is not None else [token])
        elif hasattr(token,"content") and token.content is not None:
            token.content = _replace_variables(token.content, variables)
            result.append(token)
        elif hasattr(token,"arguments"):
            token.arguments = _replace_variables(token.arguments,variables)
            result.append(token)
        else:
            result.append(token)
    return result

def _convert_rgb(tokens):
    converted = []
    for token in tokens:
        if token.type == "function" and token.lower_name == "rgb":
            parts = [item for item in token.arguments if item.type != "whitespace"]
            if (len(parts) == 5 and parts[3].type == "literal" and parts[3].value == "/"
                    and all(item.type == "number" for item in parts[:3])
                    and parts[4].type == "percentage"):
                red, green, blue = (item.representation for item in parts[:3])
                alpha = parts[4].value / 100
                converted.extend(_value(f"rgba({red}, {green}, {blue}, {alpha:g})"))
                continue
        if hasattr(token, "content") and token.content is not None:
            token.content = _convert_rgb(token.content)
        elif hasattr(token, "arguments"):
            token.arguments = _convert_rgb(token.arguments)
        converted.append(token)
    return converted

def _inset_values(tokens):
    values, current = [], []
    for token in tokens:
        if token.type == "whitespace":
            if current:
                values.append(_text(current))
                current = []
        else:
            current.append(token)
    if current:
        values.append(_text(current))
    if not 1 <= len(values) <= 4:
        return None
    top = values[0]
    right = values[1] if len(values) > 1 else top
    bottom = values[2] if len(values) > 2 else top
    left = values[3] if len(values) > 3 else right
    return top, right, bottom, left

def _transform_declarations(nodes, variables):
    transformed = []
    for declaration in nodes:
        if declaration.type != "declaration":
            transformed.append(declaration)
            continue

        try:
            name = declaration.lower_name
            value = _convert_rgb(_replace_variables(
                copy.deepcopy(declaration.value),variables))

            if name in {"justify-content", "align-items", "align-self"}:
                if _is_ident_value(value, "start"):
                    value = _replacement_value("flex-start",declaration)
                elif _is_ident_value(value, "end"):
                    value = _replacement_value("flex-end",declaration)
            elif name in _UNSET_FALLBACKS and _is_ident_value(value, "unset"):
                value = _replacement_value(_UNSET_FALLBACKS[name],declaration)

            if name == "inset":
                values = _inset_values(value)
                if values:
                    for index,(side,side_value) in enumerate(zip(
                            ("top", "right", "bottom", "left"),values)):
                        transformed.append(_new_declaration(
                            side,_replacement_value(side_value,declaration),declaration))
                        if index < 3:
                            transformed.append(_separator(declaration))
                    continue

            if name == "display" and _is_ident_value(value, "flex"):
                transformed.append(_new_declaration(
                    "display",_replacement_value("-webkit-flex",declaration),declaration))
                transformed.append(_separator(declaration))
            elif name == "display" and _is_ident_value(value, "inline-flex"):
                transformed.append(_new_declaration(
                    "display",_replacement_value("-webkit-inline-flex",declaration),declaration))
                transformed.append(_separator(declaration))
            elif name in _PREFIXED_PROPERTIES:
                transformed.append(_new_declaration(
                    f"-webkit-{declaration.name}",copy.deepcopy(value),declaration))
                transformed.append(_separator(declaration))

            declaration.value = value
        except Exception:
            pass
        transformed.append(declaration)
    return transformed

def _transform_rules(rules, variables):
    for rule in rules:
        if rule.type == "qualified-rule":
            rule.content = _transform_declarations(rule.content, variables)
        elif rule.type == "at-rule" and rule.content is not None:
            if rule.lower_at_keyword in _DECLARATION_AT_RULES:
                rule.content = _transform_declarations(rule.content, variables)
            elif rule.lower_at_keyword in _RULE_AT_RULES:
                _transform_rules(rule.content, variables)

def adapt_css(css):
    try:
        rules = tinycss2.parse_stylesheet(
            css,skip_comments=False,skip_whitespace=False)
        _prepare_rules(rules)
        _transform_rules(rules,_root_variables(rules))
        return tinycss2.serialize(rules)
    except Exception:
        return css