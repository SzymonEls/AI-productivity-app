/**
 * The tag list page: every #tag written into a plan's list items, and what
 * carries it.
 *
 * Nothing here is stored as a tag - "- [ ] call the printer #shop" is a line of
 * a plan and stays one - so the list is searched when the page opens rather than
 * kept anywhere in step. That is a pass over every active plan, which is why the
 * page arrives with a spinner in it and fills itself in afterwards; the
 * alternative was a table to maintain and a plan edited elsewhere quietly
 * disagreeing with it.
 */
(function () {
    "use strict";

    const page = document.querySelector("[data-tags-page]");
    if (!page) {
        return;
    }

    const SEARCH_ENDPOINT = "/projects/tags/search";
    // Same rule as the server's, so a tag in an item's text is picked out here too.
    // Unicode properties, not \w: JavaScript's \w is ASCII and stops at "ó".
    const TAG_PATTERN = /(^|[^\p{L}\p{N}_#(])#(\p{L}[\p{L}\p{N}_-]*)/gu;

    const body = page.querySelector("[data-tags-body]");

    function renderMessage(message, tone) {
        body.innerHTML = "";
        const paragraph = document.createElement("p");
        paragraph.className = `planner-status${tone ? ` planner-status-${tone}` : ""} mb-0`;
        paragraph.textContent = message;
        body.appendChild(paragraph);
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
        body.innerHTML = "";

        if (!tags.length) {
            renderMessage("No tags yet. Write #something in a list item of a plan.", "");
            return;
        }

        const safeMode = document.documentElement.getAttribute("data-safe-mode") === "on";

        tags.forEach((tag) => {
            const group = document.createElement("section");
            group.className = "tag-group";

            const heading = document.createElement("h2");
            heading.className = "tag-group-title";
            const name = document.createElement("span");
            name.className = "plan-tag";
            name.textContent = `#${tag.name}`;
            const count = document.createElement("span");
            count.className = "tag-group-count";
            count.textContent = tag.count === 1 ? "1 item" : `${tag.count} items`;
            heading.append(name, count);
            group.appendChild(heading);

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

            body.appendChild(group);
        });
    }

    fetch(SEARCH_ENDPOINT, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(async (response) => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "Could not read the tags.");
            }
            return payload;
        })
        .then((payload) => renderTags(payload.tags || []))
        .catch((error) => renderMessage(error.message, "danger"));
})();
