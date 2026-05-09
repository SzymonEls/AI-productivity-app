import json

import requests
from flask import current_app


OPENAI_API_URL = "https://api.openai.com/v1/responses"
PROJECT_ORGANIZATION_PLAN = "project_organization"
MARKDOWN_RESPONSE = "markdown_response"


class AIServiceError(Exception):
    """Base user-safe error for AI planning operations."""


class AIConfigurationError(AIServiceError):
    """Raised when the app is not configured for OpenAI usage."""


def is_openai_configured():
    return bool(current_app.config.get("OPENAI_API_KEY"))


def organize_project_plan(project, user_prompt):
    payload, request_payload = _request_structured_output(
        schema_name="project_organization_result",
        schema=_project_organization_schema(),
        system_prompt=(
            "You are an assistant that organizes a user's project plan. "
            "Return JSON only. Keep the user's language. Rewrite the mini goal and "
            "frequency to be concrete and actionable. Rewrite long_goal as a useful "
            "Markdown project plan, not as a single broad objective. The plan should "
            "look like a practical working note: short sections, checklists, milestones, "
            "or day-by-day steps when appropriate. Do not wrap Markdown in code fences. "
            "Do not invent a different project."
        ),
        user_payload={
            "task": current_app.config.get("OPENAI_PROJECT_TASK"),
            "user_prompt": user_prompt,
            "project": {
                "title": project.title,
                "short_goal": project.short_goal,
                "frequency": project.frequency,
                "plan": project.long_goal,
            },
        },
        timeout=current_app.config.get("OPENAI_PROJECT_TIMEOUT", 90),
        temperature=current_app.config.get("OPENAI_PROJECT_TEMPERATURE", 0.5),
    )

    result = {
        "short_goal": payload["short_goal"].strip(),
        "frequency": payload["frequency"].strip(),
        "long_goal": payload["long_goal"].strip(),
        "summary": payload["summary"].strip(),
        "history_title": f"Plan projektu: {project.title}",
        "history_content": _render_project_history_content(project.title, user_prompt, payload),
        "request_payload": json.dumps(request_payload, ensure_ascii=False, indent=2),
        "response_payload": json.dumps(payload, ensure_ascii=False, indent=2),
    }
    _validate_project_result(result)
    return result


def generate_markdown_response(user_prompt, target_date, projects):
    content, request_payload = _request_markdown_output(
        system_prompt=(
            "You are a productivity assistant. Return only clean Markdown, without JSON "
            "and without wrapping the answer in a code fence. The user is planning a day. "
            "Use the selected date, the user's prompt, and the list of starred project names "
            "as context. Keep the user's language and make the output practical."
        ),
        user_payload={
            "task": current_app.config.get("OPENAI_MARKDOWN_TASK"),
            "selected_date": target_date.isoformat(),
            "user_prompt": user_prompt,
            "starred_projects": [
                {
                    "id": project.id,
                    "title": project.title,
                }
                for project in projects
            ],
        },
    )

    result = {
        "title": _extract_markdown_title(content, f"AI note for {target_date.isoformat()}"),
        "content": content,
        "request_payload": json.dumps(request_payload, ensure_ascii=False, indent=2),
        "response_payload": json.dumps(
            {"format": "markdown", "content": content},
            ensure_ascii=False,
            indent=2,
        ),
    }
    return result


def _request_markdown_output(system_prompt, user_payload):
    api_key = current_app.config.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIConfigurationError(
            "Brakuje OPENAI_API_KEY. Dodaj go do pliku .env, aby wlaczyc planowanie AI."
        )

    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
    timeout = current_app.config.get("OPENAI_TIMEOUT", 30)
    temperature = current_app.config.get("OPENAI_TEMPERATURE", 0.7)
    request_payload = {
        "model": model,
        "temperature": temperature,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}],
            },
        ],
    }

    response_data = _post_openai_request(request_payload, api_key, timeout)
    output_text = response_data.get("output_text") or _extract_output_text_from_items(response_data)
    if not output_text or not output_text.strip():
        raise AIServiceError("OpenAI returned no usable content.")

    return _strip_markdown_code_fence(output_text.strip()), request_payload


def _request_structured_output(
    schema_name,
    schema,
    system_prompt,
    user_payload,
    timeout=None,
    temperature=None,
):
    api_key = current_app.config.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIConfigurationError(
            "Brakuje OPENAI_API_KEY. Dodaj go do pliku .env, aby wlaczyc planowanie AI."
        )

    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
    timeout = timeout or current_app.config.get("OPENAI_TIMEOUT", 30)
    temperature = temperature if temperature is not None else current_app.config.get("OPENAI_TEMPERATURE", 0.7)
    request_payload = {
        "model": model,
        "temperature": temperature,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }

    response_data = _post_openai_request(request_payload, api_key, timeout)

    output_text = response_data.get("output_text")
    if not output_text:
        output_text = _extract_output_text_from_items(response_data)
    if not output_text:
        raise AIServiceError("OpenAI returned no usable content.")

    try:
        return json.loads(output_text), request_payload
    except json.JSONDecodeError as exc:
        raise AIServiceError("OpenAI returned invalid structured data.") from exc


def _post_openai_request(request_payload, api_key, timeout):
    try:
        response = requests.post(
            OPENAI_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise AIServiceError("OpenAI nie zdazylo odpowiedziec. Sprobuj ponownie za chwile.") from exc
    except requests.RequestException as exc:
        raise AIServiceError(f"Could not reach OpenAI: {exc}") from exc

    if response.status_code >= 400:
        raise AIServiceError(_extract_openai_error(response))

    try:
        response_data = response.json()
    except ValueError as exc:
        raise AIServiceError("OpenAI returned an unreadable response.") from exc

    refusal = response_data.get("refusal")
    if refusal:
        raise AIServiceError(f"OpenAI refused this request: {refusal}")

    return response_data


def _extract_openai_error(response):
    try:
        payload = response.json()
    except ValueError:
        return f"OpenAI request failed with status {response.status_code}."

    error = payload.get("error") or {}
    message = error.get("message")
    if message:
        return f"OpenAI request failed: {message}"
    return f"OpenAI request failed with status {response.status_code}."


def _extract_output_text_from_items(response_data):
    for item in response_data.get("output", []):
        for content_item in item.get("content", []):
            if content_item.get("type") == "output_text":
                return content_item.get("text", "")
    return ""


def _validate_project_result(result):
    required_fields = ("short_goal", "frequency", "long_goal", "summary")
    if any(not result[field] for field in required_fields):
        raise AIServiceError("AI returned an incomplete project update.")


def _render_project_history_content(project_title, user_prompt, payload):
    return (
        f"# Project organization: {project_title}\n\n"
        f"## User prompt\n{user_prompt.strip()}\n\n"
        f"## AI summary\n{payload['summary'].strip()}\n\n"
        f"## Updated mini-goal\n{payload['short_goal'].strip()}\n\n"
        f"## Updated frequency\n{payload['frequency'].strip()}\n\n"
        f"## Updated plan\n{payload['long_goal'].strip()}\n"
    )


def _extract_markdown_title(content, fallback):
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title[:200]
    return fallback


def _strip_markdown_code_fence(content):
    lines = content.splitlines()
    if len(lines) >= 2 and lines[0].strip().lower() in ("```markdown", "```md", "```"):
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return content


def _project_organization_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "short_goal", "frequency", "long_goal"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "A short summary of what changed, in the user's language.",
            },
            "short_goal": {
                "type": "string",
                "description": "The next concrete action or small outcome.",
            },
            "frequency": {
                "type": "string",
                "description": "A concise cadence for returning to this project.",
            },
            "long_goal": {
                "type": "string",
                "description": "A Markdown project plan with practical sections, checklist items, and steps.",
            },
        },
    }
