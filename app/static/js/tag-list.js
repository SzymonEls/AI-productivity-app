/**
 * The tag list: every #tag written into a plan's list items, and what carries it.
 *
 * Nothing here is stored as a tag - "- [ ] call the printer #shop" is a line of
 * a plan and stays one - so the list is searched when this dialog opens rather
 * than kept anywhere in step. That is a pass over every active plan, hence the
 * spinner; the alternative was a table to maintain and a plan edited elsewhere
 * quietly disagreeing with it.
 *
 * Built on the same backdrop as the session planner, so the two read alike.
 */
(function () {
    "use strict";

    const TAGS_ENDPOINT = "/projects/tags";
    // Same rule as the server's, so a tag in an item's text is picked out here too.
    // Unicode properties, not \w: JavaScript's \w is ASCII and stops at "ó".
    const TAG_PATTERN = /(^|[^\p{L}\p{N}_#(])#(\p{L}[\p{L}\p{N}_-]*)/gu;

    let dialog = null;

    function buildDialog() {
        const element = document.createElement("div");
        element.className = "planner-backdrop";
        element.hidden = true;
        element.innerHTML = `
            <div class="planner-dialog" role="dialog" aria-modal="true" aria-labelledby="tagListTitle">
                <header class="planner-header">
                    <h2 class="h6 mb-0" id="tagListTitle">Tags</h2>
                    <button type="button" class="icon-button" data-tags-close aria-label="Close">&times;</button>
                </header>
                <div class="tag-list" data-tags-body></div>
            </div>
        `;
        document.body.appendChild(element);

        element.addEventListener("click", (event) => {
            if (event.target === element || event.target.closest("[data-tags-close]")) {
                closeDialog();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !element.hidden) {
                closeDialog();
            }
        });
        return element;
    }

    function ensureDialog() {
        if (!dialog) {
            dialog = buildDialog();
        }
        return dialog;
    }

    function closeDialog() {
        if (dialog) {
            dialog.hidden = true;
        }
    }

    function body() {
        return ensureDialog().querySelector("[data-tags-body]");
    }

    function renderLoading() {
        body().innerHTML = `
            <div class="tag-list-loading">
                <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                <span>Reading your plans…</span>
            </div>
        `;
    }

    function renderMessage(message, tone) {
        body().innerHTML = "";
        const paragraph = document.createElement("p");
        paragraph.className = `planner-status${tone ? ` planner-status-${tone}` : ""} mb-0`;
        paragraph.textContent = message;
        body().appendChild(paragraph);
    }

    /** The item's own text, with its tags picked out of it. */
    function renderItemText(target, text) {
        TAG_PATTERN.lastIndex = 0;
        let index = 0;
        let match;
        while ((match = TAG_PATTERN.exec(text)) !== null) {
            const start = match.index + match[1].length;
            target.appendChild(document.createTextNode(text.slice(index, start)));
            const tag = document.createElement("span");
            tag.className = "plan-tag";
            tag.textContent = `#${match[2]}`;
            target.appendChild(tag);
            index = start + match[2].length + 1;
        }
        target.appendChild(document.createTextNode(text.slice(index)));
    }

    function renderTags(tags) {
        const container = body();
        container.innerHTML = "";

        if (!tags.length) {
            renderMessage("No tags yet. Write #something in a list item of a plan.", "");
            return;
        }

        tags.forEach((tag) => {
            const group = document.createElement("section");
            group.className = "tag-group";

            const heading = document.createElement("h3");
            heading.className = "tag-group-title";
            const name = document.createElement("span");
            name.className = "plan-tag";
            name.textContent = `#${tag.name}`;
            const count = document.createElement("span");
            count.className = "tag-group-count";
            count.textContent = tag.count === 1 ? "1 item" : `${tag.count} items`;
            heading.append(name, count);
            group.appendChild(heading);

            const safeMode = document.documentElement.getAttribute("data-safe-mode") === "on";

            tag.items.forEach((item) => {
                // A link, not a button: the item leads back to the line it came
                // from, and a middle click should open it in a tab like any other.
                const row = document.createElement("a");
                const covered = safeMode && item.is_private;
                row.className = `tag-item${item.is_done && !covered ? " is-done" : ""}`;
                row.href = item.url;

                const text = document.createElement("span");
                text.className = "tag-item-text";
                if (covered) {
                    // The line itself stays behind the curtain safe mode drew over
                    // the project it belongs to; that it exists is not the secret.
                    text.classList.add("tag-item-covered");
                    text.textContent = "Hidden — private project";
                } else {
                    renderItemText(text, item.text);
                }

                const project = document.createElement("span");
                project.className = "tag-item-project";
                project.textContent = item.project_title;

                row.append(text, project);
                group.appendChild(row);
            });

            container.appendChild(group);
        });
    }

    function openDialog() {
        ensureDialog().hidden = false;
        renderLoading();

        fetch(TAGS_ENDPOINT, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not read the tags.");
                }
                return payload;
            })
            .then((payload) => renderTags(payload.tags || []))
            .catch((error) => renderMessage(error.message, "danger"));
    }

    document.addEventListener("click", (event) => {
        if (event.target.closest("[data-open-tags]")) {
            event.preventDefault();
            openDialog();
        }
    });
})();
