import re

from markdown import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import SimpleTagInlineProcessor
from markupsafe import Markup


TASK_ITEM_PATTERN = re.compile(
    r"<li>\s*\[(?P<checked>[xX ])\]\s*(?P<content>.*?)(?=</li>|<ul>|<ol>)",
    re.DOTALL,
)
TOP_LEVEL_HEADING_PATTERN = re.compile(r"<h1(?P<attrs>[^>]*)>.*?</h1>", re.DOTALL)
LIST_ITEM_PATTERN = re.compile(r"^(?P<indent>\s*)(?:[-*+]\s|\d+\.\s)")

# A tag is written straight into the plan - "- [ ] call the printer #shop" - and
# stored as nothing but those characters, so this pattern is the whole definition
# of one. It has to start with a letter (a bare "#2" is a number) and may not
# follow a word character or an opening bracket, which keeps "C#" out and leaves
# the "#anchor" of a Markdown link alone. Kept here rather than in
# projects/routes.py because painting one is what the app mostly does with it;
# the tag list imports it from here.
TAG_PATTERN = re.compile(r"(?<![\w#(])#([^\W\d_][\w-]*)")
# Only inside a list item: a tag marks something to do, and a "#" anywhere else
# in Markdown is a heading.
LIST_TAG_SPLIT_PATTERN = re.compile(r"(<[^>]+>)")
OPEN_LIST_ITEM_PATTERN = re.compile(r"<li[\s>]", re.IGNORECASE)


def render_markdown(value):
    if not value:
        return ""

    return Markup(_render_markdown_html(value))


def render_project_markdown(value):
    if not value:
        return ""

    html = _render_markdown_html(value)
    sections = list(TOP_LEVEL_HEADING_PATTERN.finditer(html))
    if not sections:
        return Markup(html)

    output = ['<div class="project-section-markdown">']
    preface = html[: sections[0].start()].strip()
    if preface:
        output.append(f'<div class="project-section-preface">{preface}</div>')

    for index, match in enumerate(sections):
        next_start = sections[index + 1].start() if index + 1 < len(sections) else len(html)
        heading = match.group(0)
        body = html[match.end() : next_start].strip()
        tone = (index % 6) + 1
        output.append(f'<section class="project-markdown-section project-markdown-section-tone-{tone}">')
        output.append('<div class="project-markdown-step" aria-hidden="true"></div>')
        output.append('<div class="project-markdown-section-card">')
        output.append(heading)
        if body:
            output.append(body)
        output.append("</div></section>")

    output.append("</div>")
    return Markup("".join(output))


def _render_markdown_html(value):
    value = _normalize_two_space_nested_lists(value)
    html = markdown(
        value,
        extensions=["extra", "sane_lists", "nl2br", StrikethroughExtension()],
    )
    html = TASK_ITEM_PATTERN.sub(_render_task_item, html)
    html = html.replace("<ul>\n<li><input", '<ul class="task-list">\n<li class="task-list-item"><input')
    html = html.replace("<li><input", '<li class="task-list-item"><input')
    return paint_tags(html)


def paint_tags(html):
    """Wrap the #tags inside list items in a span, leaving the rest alone.

    Walks the tags and the text between them rather than running the pattern over
    the whole document: a "#" in an attribute - ``href="#top"`` - is not a tag,
    and neither is a heading. Only the text of an ``<li>`` is painted.
    """
    if "#" not in html:
        return html

    painted = []
    depth = 0
    for part in LIST_TAG_SPLIT_PATTERN.split(html):
        if part.startswith("<"):
            if OPEN_LIST_ITEM_PATTERN.match(part):
                depth += 1
            elif part.lower().startswith("</li"):
                depth = max(depth - 1, 0)
        elif depth:
            part = TAG_PATTERN.sub(r'<span class="plan-tag">#\1</span>', part)
        painted.append(part)
    return "".join(painted)


def _normalize_two_space_nested_lists(value):
    lines = value.splitlines()
    normalized_lines = []
    in_list_block = False
    two_space_list_block = False

    for line in lines:
        list_match = LIST_ITEM_PATTERN.match(line)
        list_indent = len(list_match.group("indent").replace("\t", "    ")) if list_match else None

        if list_match and (list_indent == 2 or (two_space_list_block and list_indent and list_indent > 0)):
            two_space_list_block = True
            line = f"{' ' * list_indent}{line}"
            list_match = LIST_ITEM_PATTERN.match(line)
            list_indent = len(list_match.group("indent").replace("\t", "    "))

        normalized_lines.append(line)

        if list_match:
            in_list_block = True
            if list_indent == 2:
                two_space_list_block = True
        elif not line.strip() and in_list_block:
            continue
        elif line.strip():
            in_list_block = False
            two_space_list_block = False

    trailing_newline = "\n" if value.endswith("\n") else ""
    return "\n".join(normalized_lines) + trailing_newline


def strip_repeated_title(content, title):
    if not content or not title:
        return content

    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and stripped.lstrip("#").strip().casefold() == title.strip().casefold():
            return "\n".join(lines[index + 1 :]).lstrip()
        return content

    return content


def _render_task_item(match):
    checked = "checked" if match.group("checked").lower() == "x" else ""
    content = match.group("content")
    return (
        '<li class="task-list-item">'
        f'<input class="task-list-checkbox" type="checkbox" disabled {checked}> '
        f"{content}"
    )


class StrikethroughExtension(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            SimpleTagInlineProcessor(r"(?<!~)(~~)(.+?)(~~)(?!~)", "del"),
            "strikethrough",
            175,
        )
