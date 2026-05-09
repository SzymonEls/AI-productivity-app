import json
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..markdown_utils import render_markdown, strip_repeated_title
from ..models import AIPlan, Project
from .service import (
    AIConfigurationError,
    AIServiceError,
    MARKDOWN_RESPONSE,
    PROJECT_ORGANIZATION_PLAN,
    generate_markdown_response,
    is_openai_configured,
    organize_project_plan,
)


ai_bp = Blueprint("ai", __name__, url_prefix="/ai")
MANUAL_DAILY_PLAN = "manual_daily_plan"
HOME_PLAN_TYPES = [MARKDOWN_RESPONSE, "daily_plan", MANUAL_DAILY_PLAN]


@ai_bp.route("/daily-planning")
@login_required
def daily_planning():
    starred_projects = (
        Project.query.filter_by(user_id=current_user.id, is_starred=True)
        .order_by(Project.updated_at.desc())
        .all()
    )
    return render_template(
        "ai/daily_planning.html",
        today=date.today(),
        starred_projects=starred_projects,
        is_openai_ready=is_openai_configured(),
    )


@ai_bp.route("/project-plan", methods=["POST"])
@login_required
def generate_project_plan():
    project_id = request.form.get("project_id", type=int)
    user_prompt = request.form.get("prompt", "").strip()

    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    if not user_prompt:
        if _wants_json_response():
            return jsonify({"ok": False, "error": "Wpisz prompt dla AI."}), 400
        flash("Wpisz prompt dla AI, aby uporzadkowac plan projektu.", "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    try:
        result = organize_project_plan(project, user_prompt)
    except (AIConfigurationError, AIServiceError) as exc:
        if _wants_json_response():
            return jsonify({"ok": False, "error": str(exc)}), 400
        flash(str(exc), "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    project.short_goal = result["short_goal"]
    project.frequency = result["frequency"]
    project.long_goal = result["long_goal"]

    history_entry = AIPlan(
        owner=current_user,
        project=project,
        plan_type=PROJECT_ORGANIZATION_PLAN,
        title=result["history_title"],
        user_prompt=user_prompt,
        project_title_snapshot=project.title,
        content=result["history_content"],
        request_payload=result["request_payload"],
        response_payload=result["response_payload"],
    )
    db.session.add(history_entry)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"ok": False, "error": "Nie udalo sie zapisac zmian projektu i historii AI."}), 500
        flash("Nie udalo sie zapisac zmian projektu i historii AI.", "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))
    if _wants_json_response():
        return jsonify(
            {
                "ok": True,
                "message": "AI uporzadkowalo plan projektu.",
                "project": {
                    "title": project.title,
                    "short_goal": project.short_goal,
                    "frequency": project.frequency,
                    "long_goal": project.long_goal,
                    "long_goal_html": str(render_markdown(project.long_goal)),
                    "updated_label": "just now",
                },
                "history_url": url_for("ai.history_detail", plan_id=history_entry.id),
            }
        )
    flash("AI uporzadkowalo plan projektu i zapisalo wynik w historii.", "success")
    return redirect(url_for("projects.project_detail", project_id=project.id))


@ai_bp.route("/daily-plan", methods=["POST"])
@login_required
def create_daily_plan():
    user_prompt = request.form.get("prompt", "").strip()
    raw_date = request.form.get("target_date", "").strip()

    if not user_prompt:
        if _wants_json_response():
            return jsonify({"ok": False, "error": "Wpisz prompt dla AI."}), 400
        flash("Wpisz prompt dla AI, aby wygenerowac odpowiedz markdown.", "danger")
        return redirect(url_for("ai.daily_planning"))

    try:
        target_date = date.fromisoformat(raw_date)
    except ValueError:
        if _wants_json_response():
            return jsonify({"ok": False, "error": "Wybierz poprawna date."}), 400
        flash("Wybierz poprawna date planu dnia.", "danger")
        return redirect(url_for("ai.daily_planning"))

    projects = (
        Project.query.filter_by(user_id=current_user.id, is_starred=True)
        .order_by(Project.updated_at.desc())
        .all()
    )

    try:
        result = generate_markdown_response(user_prompt, target_date, projects)
    except (AIConfigurationError, AIServiceError) as exc:
        if _wants_json_response():
            return jsonify({"ok": False, "error": str(exc)}), 400
        flash(str(exc), "danger")
        return redirect(url_for("ai.daily_planning"))

    history_entry = AIPlan(
        owner=current_user,
        plan_type=MARKDOWN_RESPONSE,
        title=result["title"],
        user_prompt=user_prompt,
        target_date=target_date,
        content=result["content"],
        request_payload=result["request_payload"],
        response_payload=result["response_payload"],
        is_pinned=True,
    )
    _unpin_home_plans()
    db.session.add(history_entry)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"ok": False, "error": "Nie udalo sie zapisac odpowiedzi AI w historii."}), 500
        flash("Nie udalo sie zapisac odpowiedzi AI w historii.", "danger")
        return redirect(url_for("ai.daily_planning"))
    if _wants_json_response():
        visible_content = strip_repeated_title(history_entry.content, history_entry.title)
        return jsonify(
            {
                "ok": True,
                "plan": {
                    "id": history_entry.id,
                    "title": history_entry.title,
                    "plan_type": history_entry.plan_type.replace("_", " "),
                    "content_html": str(render_markdown(visible_content)),
                    "detail_url": url_for("ai.history_detail", plan_id=history_entry.id),
                },
            }
        )
    flash("AI przygotowalo odpowiedz markdown i zapisalo ja w historii.", "success")
    return redirect(url_for("ai.history_detail", plan_id=history_entry.id))


@ai_bp.route("/daily-plan/manual", methods=["GET", "POST"])
@login_required
def manual_daily_plan():
    projects = (
        Project.query.filter_by(user_id=current_user.id)
        .order_by(Project.is_starred.desc(), Project.title.asc())
        .all()
    )

    if request.method == "GET":
        return render_template(
            "ai/manual_daily_plan.html",
            today=date.today(),
            projects=projects,
        )

    raw_date = request.form.get("target_date", "").strip()
    try:
        target_date = date.fromisoformat(raw_date)
    except ValueError:
        flash("Wybierz poprawna date planu dnia.", "danger")
        return render_template("ai/manual_daily_plan.html", today=date.today(), projects=projects), 400

    selected_project_ids = _parse_project_ids(request.form.getlist("project_ids"))
    if not selected_project_ids:
        flash("Wybierz przynajmniej jeden projekt do planu recznego.", "danger")
        return render_template("ai/manual_daily_plan.html", today=target_date, projects=projects), 400

    selected_projects = (
        Project.query.filter(Project.user_id == current_user.id, Project.id.in_(selected_project_ids))
        .all()
    )
    project_by_id = {project.id: project for project in selected_projects}
    ordered_projects = [project_by_id[project_id] for project_id in selected_project_ids if project_id in project_by_id]

    if len(ordered_projects) != len(selected_project_ids):
        flash("Nie udalo sie znalezc wszystkich wybranych projektow.", "danger")
        return render_template("ai/manual_daily_plan.html", today=target_date, projects=projects), 400

    tasks = []
    for project in ordered_projects:
        task = request.form.get(f"task_{project.id}", "").strip()
        if not task:
            flash(f"Wpisz zadanie dla projektu: {project.title}.", "danger")
            return render_template("ai/manual_daily_plan.html", today=target_date, projects=projects), 400
        tasks.append({"project": project, "task": task})

    title = f"Plan dnia - {target_date.isoformat()}"
    content = _render_manual_daily_plan(target_date, tasks)
    request_payload = {
        "mode": "manual_daily_plan",
        "selected_date": target_date.isoformat(),
        "projects": [
            {
                "id": item["project"].id,
                "title": item["project"].title,
                "short_goal": item["project"].short_goal,
                "frequency": item["project"].frequency,
                "long_goal": item["project"].long_goal,
                "task": item["task"],
            }
            for item in tasks
        ],
    }

    history_entry = AIPlan(
        owner=current_user,
        plan_type=MANUAL_DAILY_PLAN,
        title=title,
        user_prompt="Plan reczny",
        target_date=target_date,
        content=content,
        request_payload=json.dumps(request_payload, ensure_ascii=False, indent=2),
        response_payload=json.dumps(
            {"format": "markdown", "content": content, "source": "manual"},
            ensure_ascii=False,
            indent=2,
        ),
        is_pinned=True,
    )
    _unpin_home_plans()
    db.session.add(history_entry)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Nie udalo sie zapisac recznego planu dnia.", "danger")
        return render_template("ai/manual_daily_plan.html", today=target_date, projects=projects), 500

    flash("Reczny plan dnia zostal zapisany i przypiety na home.", "success")
    return redirect(url_for("ai.history_detail", plan_id=history_entry.id))


@ai_bp.route("/history")
@login_required
def history():
    plans = (
        AIPlan.query.filter_by(user_id=current_user.id)
        .order_by(AIPlan.created_at.desc())
        .all()
    )
    return render_template(
        "ai/history.html",
        plans=plans,
        is_openai_ready=is_openai_configured(),
        home_plan_types=HOME_PLAN_TYPES,
    )


@ai_bp.route("/history/<int:plan_id>")
@login_required
def history_detail(plan_id):
    plan = AIPlan.query.filter_by(id=plan_id, user_id=current_user.id).first_or_404()
    parsed_request_payload = None
    parsed_payload = None
    if plan.request_payload:
        try:
            parsed_request_payload = json.loads(plan.request_payload)
        except ValueError:
            parsed_request_payload = None
    try:
        parsed_payload = json.loads(plan.response_payload)
    except ValueError:
        parsed_payload = None

    return render_template(
        "ai/detail.html",
        plan=plan,
        parsed_request_payload=parsed_request_payload,
        parsed_payload=parsed_payload,
        is_openai_ready=is_openai_configured(),
        home_plan_types=HOME_PLAN_TYPES,
    )


@ai_bp.route("/history/<int:plan_id>/edit", methods=["POST"])
@login_required
def edit_history_plan(plan_id):
    plan = (
        AIPlan.query.filter_by(id=plan_id, user_id=current_user.id)
        .filter(AIPlan.plan_type.in_(HOME_PLAN_TYPES))
        .first_or_404()
    )
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    raw_date = request.form.get("target_date", "").strip()

    if not title or not content:
        flash("Tytul i tresc planu nie moga byc puste.", "danger")
        return redirect(url_for("ai.history_detail", plan_id=plan.id))

    target_date = None
    if raw_date:
        try:
            target_date = date.fromisoformat(raw_date)
        except ValueError:
            flash("Wybierz poprawna date planu.", "danger")
            return redirect(url_for("ai.history_detail", plan_id=plan.id))

    plan.title = title
    plan.content = content
    plan.target_date = target_date

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Nie udalo sie zapisac edycji planu.", "danger")
        return redirect(url_for("ai.history_detail", plan_id=plan.id))

    flash("Plan zostal zapisany.", "success")
    return redirect(url_for("ai.history_detail", plan_id=plan.id))


@ai_bp.route("/history/<int:plan_id>/pin", methods=["POST"])
@login_required
def pin_history_plan(plan_id):
    plan = (
        AIPlan.query.filter_by(id=plan_id, user_id=current_user.id)
        .filter(AIPlan.plan_type.in_(HOME_PLAN_TYPES))
        .first_or_404()
    )
    _pin_plan(plan)

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Nie udalo sie przypiac planu.", "danger")
        return redirect(url_for("ai.history_detail", plan_id=plan.id))

    flash("Plan jest teraz przypiety na home.", "success")
    return redirect(request.form.get("next") or url_for("ai.history_detail", plan_id=plan.id))


def _wants_json_response():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def _unpin_home_plans():
    with db.session.no_autoflush:
        AIPlan.query.filter_by(user_id=current_user.id, is_pinned=True).filter(
            AIPlan.plan_type.in_(HOME_PLAN_TYPES)
        ).update({"is_pinned": False}, synchronize_session=False)


def _pin_plan(plan):
    _unpin_home_plans()
    plan.is_pinned = True


def _parse_project_ids(raw_project_ids):
    project_ids = []
    for raw_project_id in raw_project_ids:
        try:
            project_id = int(raw_project_id)
        except (TypeError, ValueError):
            continue
        if project_id not in project_ids:
            project_ids.append(project_id)
    return project_ids


def _render_manual_daily_plan(target_date, tasks):
    lines = [f"# Plan dnia - {target_date.isoformat()}", ""]
    for item in tasks:
        project = item["project"]
        lines.append(f"- **{project.title}:** {item['task']}")
    return "\n".join(lines).strip() + "\n"
