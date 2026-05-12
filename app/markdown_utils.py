import re

from markdown import markdown
from markupsafe import Markup


TASK_ITEM_PATTERN = re.compile(
    r"<li>\s*\[(?P<checked>[xX ])\]\s*(?P<content>.*?)</li>",
    re.DOTALL,
)
HEADING_PATTERN = re.compile(r"<h(?P<level>[1-6])(?P<attrs>[^>]*)>.*?</h(?P=level)>", re.DOTALL)


def render_markdown(value):
    if not value:
        return ""

    return Markup(_render_markdown_html(value))


def render_project_markdown(value):
    if not value:
        return ""

    html = _render_markdown_html(value)
    sections = list(HEADING_PATTERN.finditer(html))
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
    html = markdown(
        value,
        extensions=["extra", "sane_lists", "nl2br"],
    )
    html = TASK_ITEM_PATTERN.sub(_render_task_item, html)
    html = html.replace("<ul>\n<li><input", '<ul class="task-list">\n<li class="task-list-item"><input')
    html = html.replace("<li><input", '<li class="task-list-item"><input')
    return html


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
        f"{content}</li>"
    )
