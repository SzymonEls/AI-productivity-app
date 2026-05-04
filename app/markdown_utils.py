import re

from markdown import markdown
from markupsafe import Markup


TASK_ITEM_PATTERN = re.compile(
    r"<li>\s*\[(?P<checked>[xX ])\]\s*(?P<content>.*?)</li>",
    re.DOTALL,
)


def render_markdown(value):
    if not value:
        return ""

    html = markdown(
        value,
        extensions=["extra", "sane_lists", "nl2br"],
    )

    html = TASK_ITEM_PATTERN.sub(_render_task_item, html)
    html = html.replace("<ul>\n<li><input", '<ul class="task-list">\n<li class="task-list-item"><input')
    html = html.replace("<li><input", '<li class="task-list-item"><input')
    return Markup(html)


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
