import html
import re


DEFAULT_CSS = """
:root {
  color-scheme: light;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans JP",
    "Yu Gothic UI", Meiryo, Arial, sans-serif;
}

body {
  margin: 0;
  color: #172b4d;
  line-height: 1.55;
}

main {
  max-width: 1180px;
  padding: 0 32px 32px;
  background: #fff;
}

h1, h2, h3, h4, h5, h6 {
  margin: 28px 0 12px;
  line-height: 1.25;
  color: #091e42;
}

p {
  margin: 8px 0;
  white-space: pre-wrap;
}

a {
  color: #0052cc;
}

.contentLayout2 {
  width: 100%;
}

.columnLayout {
  display: block;
  width: 100%;
  margin: 0 auto;
  padding: 24px 0 8px;
}

.columnLayout + .columnLayout {
  border-top: 1px solid #ebecf0;
}

.columnLayout.fixed-width {
  max-width: 100%;
}

.columnLayout.single {
  max-width: 100%;
}

.cell {
  width: 100%;
}

.innerCell {
  width: 100%;
}

.file-attachment {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  padding: 8px 10px;
  background: #f4f5f7;
  border: 1px solid #dfe1e6;
  border-radius: 4px;
}

.file-attachment::before {
  content: "[File]";
  color: #42526e;
  font-size: 12px;
  font-weight: 600;
}

.file-attachment a {
  color: #172b4d;
  font-weight: 600;
  text-decoration: none;
}

.file-attachment a:hover {
  text-decoration: underline;
}

.table-wrap {
  margin: 16px 0 24px;
  overflow-x: auto;
  max-width: 100%;
}

table {
  border-collapse: collapse;
  width: max-content;
  min-width: min(520px, 100%);
  max-width: 100%;
  background: #fff;
}

th, td {
  border: 1px solid #c1c7d0;
  padding: 8px 10px;
  vertical-align: top;
  min-width: 120px;
}

th {
  background: #f4f5f7;
  font-weight: 600;
}

td > p:first-child,
th > p:first-child {
  margin-top: 0;
}

td > p:last-child,
th > p:last-child {
  margin-bottom: 0;
}

img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 16px 0;
  border: 1px solid #dfe1e6;
}

.confluence-embedded-file-wrapper {
  display: block;
  max-width: 100%;
  margin: 16px 0;
}

.confluence-embedded-file-wrapper img {
  margin-top: 0;
  margin-bottom: 0;
}

.image-center-wrapper {
  text-align: center;
}

.image-center-wrapper img,
img.image-center,
img.align-center {
  margin-left: auto;
  margin-right: auto;
}

.image-right-wrapper {
  text-align: right;
}

.image-right-wrapper img,
img.image-right,
img.align-right {
  margin-left: auto;
  margin-right: 0;
}

.align-center,
.text-align-center,
.wysiwyg-text-align-center {
  text-align: center;
}

.align-right,
.text-align-right,
.wysiwyg-text-align-right {
  text-align: right;
}

code, pre {
  font-family: Consolas, "Courier New", monospace;
}

pre {
  padding: 12px;
  overflow: auto;
  background: #f4f5f7;
  border: 1px solid #dfe1e6;
}
""".strip()


def convert_confluence_images(fragment: str, assets_dir: str | None) -> str:
    base = assets_dir.replace("\\", "/").rstrip("/") + "/" if assets_dir else ""

    def image_replacer(match: re.Match[str]) -> str:
        body = match.group(1)
        filename_match = re.search(r'<ri:attachment\b[^>]*\bri:filename="([^"]+)"', body)
        if not filename_match:
            filename_match = re.search(r"<ri:attachment\b[^>]*\bri:filename='([^']+)'", body)
        if not filename_match:
            return ""

        filename = html.unescape(filename_match.group(1))
        src = html.escape(base + filename, quote=True)

        alt_match = re.search(r'<ac:parameter\b[^>]*\bac:name="alt"[^>]*>(.*?)</ac:parameter>', body, re.S)
        alt = html.unescape(re.sub(r"<[^>]+>", "", alt_match.group(1))).strip() if alt_match else filename

        width_match = re.search(r'<ac:parameter\b[^>]*\bac:name="width"[^>]*>(.*?)</ac:parameter>', body, re.S)
        width_attr = ""
        if width_match:
            width = re.sub(r"\D", "", width_match.group(1))
            if width:
                width_attr = f' width="{width}"'
        align = image_alignment(match.group(0), body)
        class_attr = f' class="align-{align}"' if align in {"center", "right"} else ""

        return f'<img src="{src}" alt="{html.escape(alt, quote=True)}"{width_attr}{class_attr}/>'

    fragment = re.sub(r"<ac:image\b[^>]*>(.*?)</ac:image>", image_replacer, fragment, flags=re.S)
    fragment = re.sub(r"<ac:image\b[^>]*/>", "", fragment)
    return fragment


def image_alignment(tag: str, body: str) -> str | None:
    align = (
        get_attr(tag, "ac:align")
        or get_attr(tag, "align")
        or get_attr(tag, "data-align")
    )
    if not align:
        align_match = re.search(r'<ac:parameter\b[^>]*\bac:name="align"[^>]*>(.*?)</ac:parameter>', body, re.S | re.I)
        if align_match:
            align = re.sub(r"<[^>]+>", "", align_match.group(1))
    if not align:
        return None
    normalized = html.unescape(align).strip().lower()
    return normalized if normalized in {"center", "right", "left"} else None


def get_attr(tag: str, name: str) -> str | None:
    match = re.search(rf'\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\')', tag, flags=re.I | re.S)
    if not match:
        return None
    return match.group(2) if match.group(2) is not None else match.group(3)


def set_attr(tag: str, name: str, value: str) -> str:
    escaped = html.escape(value, quote=True)
    if re.search(rf"\b{name}\s*=", tag, flags=re.I):
        return re.sub(rf'\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\')', f'{name}="{escaped}"', tag, count=1, flags=re.I | re.S)
    return re.sub(r"\s*/?>$", f' {name}="{escaped}"/>', tag, count=1)


def remove_attr(tag: str, name: str) -> str:
    return re.sub(rf'\s+\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\')', "", tag, flags=re.I | re.S)


def merge_style(tag: str, style: str) -> str:
    current = get_attr(tag, "style")
    value = f"{current.rstrip(';')}; {style}" if current else style
    return set_attr(tag, "style", value)


def apply_alignment_attrs(fragment: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        tag = match.group(0)
        align = get_attr(tag, "data-align") or get_attr(tag, "align") or get_attr(tag, "ac:align")
        if not align:
            return tag
        normalized = html.unescape(align).strip().lower()
        if normalized not in {"center", "right", "left"}:
            return tag
        tag = merge_style(tag, f"text-align: {normalized}")
        tag = remove_attr(tag, "data-align")
        tag = remove_attr(tag, "align")
        tag = remove_attr(tag, "ac:align")
        return tag

    return re.sub(r"<(?:p|div|h[1-6]|td|th|li|span)\b[^>]*>", replacer, fragment, flags=re.I | re.S)


def apply_table_width_attrs(fragment: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        tag = match.group(0)
        width = get_attr(tag, "data-table-width")
        if not width:
            return tag
        normalized = re.sub(r"\D", "", html.unescape(width))
        if not normalized:
            return remove_attr(tag, "data-table-width")
        tag = merge_style(tag, f"width: {normalized}px")
        return remove_attr(tag, "data-table-width")

    return re.sub(r"<table\b[^>]*>", replacer, fragment, flags=re.I | re.S)


def prefer_embedded_image_src(match: re.Match[str]) -> str:
    tag = match.group(0)
    embedded_src = get_attr(tag, "data-image-src")
    if embedded_src and embedded_src.startswith("data:image/"):
        tag = set_attr(tag, "src", html.unescape(embedded_src))
        tag = remove_attr(tag, "srcset")
    return tag


def replace_file_attachment_previews(fragment: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        wrapper = match.group(0)
        if "data-image-src=\"data:image/" in wrapper or "data-image-src='data:image/" in wrapper:
            return wrapper

        anchor_match = re.search(r"<a\b[^>]*\bclass=(?:\"[^\"]*confluence-embedded-file[^\"]*\"|'[^']*confluence-embedded-file[^']*')[^>]*>", wrapper, flags=re.I | re.S)
        if not anchor_match:
            return wrapper

        anchor = anchor_match.group(0)
        filename = (
            get_attr(anchor, "data-linked-resource-default-alias")
            or get_attr(anchor, "data-linked-resource-id")
            or "attachment"
        )
        href = get_attr(anchor, "href") or get_attr(anchor, "data-file-src") or "#"

        return (
            '<span class="file-attachment">'
            f'<a href="{html.escape(html.unescape(href), quote=True)}">'
            f'{html.escape(html.unescape(filename))}'
            "</a></span>"
        )

    return re.sub(
        r"<span\b[^>]*\bconfluence-embedded-file-wrapper\b[^>]*>.*?</span>",
        replacer,
        fragment,
        flags=re.I | re.S,
    )


def clean_fragment(fragment: str) -> str:
    fragment = replace_file_attachment_previews(fragment)
    fragment = apply_alignment_attrs(fragment)
    fragment = apply_table_width_attrs(fragment)
    fragment = re.sub(r"<img\b[^>]*>", prefer_embedded_image_src, fragment, flags=re.I | re.S)
    fragment = re.sub(
        r'(<(?:td|th)\b[^>]*?)\sdata-highlight-colou?r="([^"]+)"([^>]*>)',
        lambda m: f'{m.group(1)} style="background-color: {html.escape(m.group(2), quote=True)}"{m.group(3)}',
        fragment,
        flags=re.I,
    )
    fragment = re.sub(r'\s(?:local-id|data-local-id|data-table-width|data-layout)="[^"]*"', "", fragment)
    fragment = re.sub(r'\sclass="(?:confluenceTable|confluenceTd|confluenceTh)"', "", fragment)
    fragment = re.sub(r'\srel="nofollow"', "", fragment)
    return fragment


def extract_title(fragment: str) -> str:
    heading_match = re.search(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", fragment, flags=re.I | re.S)
    if not heading_match:
        return "Converted Confluence Page"

    title = re.sub(r"<[^>]+>", "", heading_match.group(1))
    title = html.unescape(title).strip()
    return title or "Converted Confluence Page"


def build_html(title: str, fragment: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
{DEFAULT_CSS}
  </style>
</head>
<body>
  <main>
{fragment}
  </main>
</body>
</html>
"""


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "縺" not in text and "繝" not in text and "譁" not in text:
            return text

    return content.decode("utf-8-sig", errors="replace")


def convert_content(content: bytes, assets_dir: str | None = None) -> tuple[str, str]:
    fragment = decode_text(content)
    fragment = convert_confluence_images(fragment, assets_dir)
    fragment = clean_fragment(fragment)
    title = extract_title(fragment)
    return title, build_html(title, fragment)
