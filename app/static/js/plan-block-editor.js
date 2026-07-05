/*
 * Plan block editor — a lightweight, Notion-like block editor for a project plan.
 *
 * The plan is still stored as Markdown in the database (Project.long_goal), so the
 * timeline steps, "download markdown", archived sections and AI planning keep working.
 * This editor only changes how that Markdown is *edited*: it parses the Markdown into
 * blocks, renders them as always-editable rows (no edit/read-only switch), lets the
 * user reorder them by dragging, and serializes back to Markdown on every change so
 * the change can be autosaved.
 *
 * Inline emphasis (**bold**, _italic_, `code`, links) is kept as raw Markdown inside a
 * block so nothing is ever lost on a round-trip; the block *type* (heading, list, to-do,
 * quote, divider) is what gets rendered structurally.
 */
(() => {
    "use strict";

    const LIST_TYPES = ["bulleted", "numbered", "todo"];
    const INDENT = "  "; // two spaces per nesting level (round-trips with parse below)
    const MAX_LEVEL = 6;

    let uidCounter = 0;
    const uid = () => `b${Date.now().toString(36)}${(uidCounter += 1).toString(36)}`;

    const isListType = (type) => LIST_TYPES.includes(type);
    const indentLevel = (spaces) => Math.min(Math.floor(spaces.replace(/\t/g, "  ").length / 2), MAX_LEVEL);

    // --- Markdown -> blocks ------------------------------------------------

    const parseMarkdown = (markdown) => {
        const blocks = [];
        let paragraph = null;

        const flushParagraph = () => {
            if (paragraph !== null) {
                blocks.push({ type: "paragraph", text: paragraph, level: 0 });
                paragraph = null;
            }
        };

        const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
        for (const line of lines) {
            if (!line.trim()) {
                flushParagraph();
                continue;
            }

            let match;
            if ((match = line.match(/^(#{1,6})\s+(.*)$/))) {
                flushParagraph();
                blocks.push({ type: `h${Math.min(match[1].length, 3)}`, text: match[2].trim(), level: 0 });
            } else if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
                flushParagraph();
                blocks.push({ type: "divider", text: "", level: 0 });
            } else if ((match = line.match(/^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$/))) {
                flushParagraph();
                blocks.push({ type: "todo", text: match[3], checked: /x/i.test(match[2]), level: indentLevel(match[1]) });
            } else if ((match = line.match(/^(\s*)[-*+]\s+(.*)$/))) {
                flushParagraph();
                blocks.push({ type: "bulleted", text: match[2], level: indentLevel(match[1]) });
            } else if ((match = line.match(/^(\s*)\d+\.\s+(.*)$/))) {
                flushParagraph();
                blocks.push({ type: "numbered", text: match[2], level: indentLevel(match[1]) });
            } else if ((match = line.match(/^>\s?(.*)$/))) {
                flushParagraph();
                blocks.push({ type: "quote", text: match[1], level: 0 });
            } else {
                paragraph = paragraph === null ? line : `${paragraph}\n${line}`;
            }
        }
        flushParagraph();

        if (!blocks.length) {
            blocks.push({ type: "paragraph", text: "", level: 0 });
        }
        blocks.forEach((block) => {
            block.id = uid();
            if (typeof block.level !== "number") block.level = 0;
        });
        return blocks;
    };

    // --- blocks -> Markdown ------------------------------------------------

    const serializeBlocks = (blocks) => {
        const out = [];
        let previous = null;
        let numberedCounters = {};

        blocks.forEach((block) => {
            const sameListRun = previous && previous.type === block.type && isListType(block.type);
            if (previous && !sameListRun) {
                out.push("");
                numberedCounters = {};
            }

            const indent = isListType(block.type) ? INDENT.repeat(block.level || 0) : "";
            const text = block.text || "";

            switch (block.type) {
                case "h1": out.push(`# ${text}`); break;
                case "h2": out.push(`## ${text}`); break;
                case "h3": out.push(`### ${text}`); break;
                case "bulleted": out.push(`${indent}- ${text}`); break;
                case "todo": out.push(`${indent}- [${block.checked ? "x" : " "}] ${text}`); break;
                case "numbered": {
                    const level = block.level || 0;
                    Object.keys(numberedCounters).forEach((key) => {
                        if (Number(key) > level) delete numberedCounters[key];
                    });
                    numberedCounters[level] = (numberedCounters[level] || 0) + 1;
                    out.push(`${indent}${numberedCounters[level]}. ${text}`);
                    break;
                }
                case "quote": out.push(text.split("\n").map((part) => `> ${part}`).join("\n")); break;
                case "divider": out.push("---"); break;
                default: out.push(text);
            }
            previous = block;
        });

        // No trailing newline: the server strips it, so matching here keeps the
        // hidden textarea equal to the saved value (no phantom "unsaved changes").
        return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
    };

    // --- caret helpers -----------------------------------------------------

    const getCaretOffset = (el) => {
        const selection = window.getSelection();
        if (!selection || !selection.rangeCount) return null;
        const range = selection.getRangeAt(0);
        if (!el.contains(range.startContainer)) return null;
        const pre = range.cloneRange();
        pre.selectNodeContents(el);
        pre.setEnd(range.startContainer, range.startOffset);
        return pre.toString().length;
    };

    const setCaretOffset = (el, offset) => {
        el.focus();
        const selection = window.getSelection();
        const range = document.createRange();
        const length = el.textContent.length;
        const target = Math.max(0, Math.min(offset, length));
        const node = el.firstChild;
        if (node && node.nodeType === Node.TEXT_NODE) {
            range.setStart(node, target);
        } else {
            range.selectNodeContents(el);
            range.collapse(target === 0);
        }
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
    };

    // --- editor ------------------------------------------------------------

    const placeholderFor = (block, isOnlyBlock) => {
        switch (block.type) {
            case "h1": return "Heading 1";
            case "h2": return "Heading 2";
            case "h3": return "Heading 3";
            case "todo": return "To-do";
            case "bulleted":
            case "numbered": return "List item";
            case "quote": return "Quote";
            default: return isOnlyBlock ? "Write your plan, or press \"/\" for commands…" : "Type \"/\" for commands…";
        }
    };

    const SLASH_COMMANDS = [
        { key: "text", label: "Text", hint: "Plain paragraph", apply: (b) => { b.type = "paragraph"; } },
        { key: "h1", label: "Heading 1", hint: "Big section — a timeline step", apply: (b) => { b.type = "h1"; } },
        { key: "h2", label: "Heading 2", hint: "Medium heading", apply: (b) => { b.type = "h2"; } },
        { key: "h3", label: "Heading 3", hint: "Small heading", apply: (b) => { b.type = "h3"; } },
        { key: "todo", label: "To-do list", hint: "Track tasks with a checkbox", apply: (b) => { b.type = "todo"; b.checked = false; } },
        { key: "bulleted", label: "Bulleted list", hint: "Simple bullet point", apply: (b) => { b.type = "bulleted"; } },
        { key: "numbered", label: "Numbered list", hint: "Ordered list", apply: (b) => { b.type = "numbered"; } },
        { key: "quote", label: "Quote", hint: "Capture a quote", apply: (b) => { b.type = "quote"; } },
        { key: "divider", label: "Divider", hint: "Visual separator", divider: true },
    ];

    class PlanBlockEditor {
        constructor(container, options = {}) {
            this.container = container;
            this.options = options;
            this.onSaveMarkdown = options.onSave || (async () => true);
            this.onChange = options.onChange || (() => {});
            this.onStatus = options.onStatus || (() => {});
            this.saveDelay = options.saveDelay || 800;

            this.blocks = parseMarkdown(options.initialMarkdown || "");
            this.saveTimer = null;
            this.saving = false;
            this.dirty = false;
            this.slash = null;
            this.drag = null;
            this.blockMenuFor = null;
            this.selectedIds = [];
            this.undoStack = [];
            this.redoStack = [];
            this._lastGroup = null;
            this._lastCommitTime = 0;

            this.supportsPlaintextOnly = this._detectPlaintextOnly();

            this.root = document.createElement("div");
            this.root.className = "pbe";
            this.list = document.createElement("div");
            this.list.className = "pbe-list";
            this.root.appendChild(this.list);
            this.menu = document.createElement("div");
            this.menu.className = "pbe-slash-menu d-none";
            this.root.appendChild(this.menu);
            this.blockMenu = document.createElement("div");
            this.blockMenu.className = "pbe-block-menu d-none";
            this.root.appendChild(this.blockMenu);
            container.appendChild(this.root);

            this._bind();
            this.renderAll();
            this.undoStack = [this._snapshot()];
        }

        _detectPlaintextOnly() {
            const probe = document.createElement("div");
            probe.contentEditable = "plaintext-only";
            return probe.contentEditable === "plaintext-only";
        }

        _bind() {
            this._onInput = this._onInput.bind(this);
            this._onKeydown = this._onKeydown.bind(this);
            this._onFocusIn = this._onFocusIn.bind(this);
            this._onFocusOut = this._onFocusOut.bind(this);
            this._onClick = this._onClick.bind(this);
            this._onChange = this._onChange.bind(this);
            this._onPaste = this._onPaste.bind(this);
            this._onPointerDown = this._onPointerDown.bind(this);

            this.list.addEventListener("input", this._onInput);
            this.list.addEventListener("keydown", this._onKeydown);
            this.list.addEventListener("focusin", this._onFocusIn);
            this.list.addEventListener("focusout", this._onFocusOut);
            this.list.addEventListener("click", this._onClick);
            this.list.addEventListener("change", this._onChange);
            this.list.addEventListener("paste", this._onPaste);
            this.list.addEventListener("pointerdown", this._onPointerDown);

            // Menus keep the caret in place (mousedown default would blur it) and act on
            // click. stopPropagation keeps these in-editor clicks from reaching page-level
            // handlers (e.g. the project's unsaved-changes navigation guard) — especially
            // since acting on a menu item detaches it from the DOM before the click bubbles.
            this.menu.addEventListener("mousedown", (event) => event.preventDefault());
            this.menu.addEventListener("click", (event) => {
                event.stopPropagation();
                const item = event.target.closest(".pbe-slash-item");
                if (!item || !this.slash) return;
                const command = SLASH_COMMANDS.find((cmd) => cmd.key === item.dataset.key);
                if (command) this._applySlashCommand(command);
            });
            this.blockMenu.addEventListener("mousedown", (event) => event.preventDefault());
            this.blockMenu.addEventListener("click", (event) => {
                event.stopPropagation();
                this._onBlockMenuClick(event);
            });

            this._onDocPointerDown = (event) => {
                if (this.blockMenu.classList.contains("d-none")) return;
                if (this.blockMenu.contains(event.target)) return;
                if (event.target.closest && event.target.closest(".pbe-handle")) return;
                this._closeBlockMenu();
            };
            document.addEventListener("pointerdown", this._onDocPointerDown, true);

            // Multi-block selection: copy/cut whole ranges, and delete them. These live
            // on the document because a block selection has no focused contenteditable.
            this._onCopy = (event) => {
                if (!this.selectedIds.length) return;
                event.preventDefault();
                event.clipboardData.setData("text/plain", this._selectedMarkdown());
            };
            this._onCut = (event) => {
                if (!this.selectedIds.length) return;
                event.preventDefault();
                event.clipboardData.setData("text/plain", this._selectedMarkdown());
                this._deleteSelected();
            };
            this._onDocKeydown = (event) => {
                const target = event.target;
                const inEditor = target && target.closest && target.closest(".pbe") === this.root;
                if (!inEditor && !this.selectedIds.length) return;

                // Undo / redo for structural changes (reorder, type, delete…) and text.
                // renderAll() wipes the browser's native per-field undo, so the editor
                // owns a single consistent history instead.
                const mod = event.ctrlKey || event.metaKey;
                const key = event.key.toLowerCase();
                if (mod && key === "z" && !event.shiftKey) { event.preventDefault(); this.undo(); return; }
                if (mod && (key === "y" || (key === "z" && event.shiftKey))) { event.preventDefault(); this.redo(); return; }

                if (!this.selectedIds.length) return;
                if (event.key === "Escape") {
                    this._clearBlockSelection();
                } else if (event.key === "Delete" || event.key === "Backspace") {
                    event.preventDefault();
                    this._deleteSelected();
                }
            };
            document.addEventListener("copy", this._onCopy);
            document.addEventListener("cut", this._onCut);
            document.addEventListener("keydown", this._onDocKeydown);
            // Note: persisting on page unload is the host's responsibility (it can
            // use a keepalive request that survives the page being torn down).
        }

        destroy() {
            this.flush();
            this.list.removeEventListener("input", this._onInput);
            this.list.removeEventListener("keydown", this._onKeydown);
            this.list.removeEventListener("focusin", this._onFocusIn);
            this.list.removeEventListener("focusout", this._onFocusOut);
            this.list.removeEventListener("click", this._onClick);
            this.list.removeEventListener("change", this._onChange);
            this.list.removeEventListener("paste", this._onPaste);
            this.list.removeEventListener("pointerdown", this._onPointerDown);
            document.removeEventListener("pointerdown", this._onDocPointerDown, true);
            document.removeEventListener("copy", this._onCopy);
            document.removeEventListener("cut", this._onCut);
            document.removeEventListener("keydown", this._onDocKeydown);
            this.root.remove();
        }

        // --- model helpers ---

        indexOf(id) { return this.blocks.findIndex((block) => block.id === id); }
        byId(id) { return this.blocks.find((block) => block.id === id); }

        blockFromEvent(event) {
            const el = event.target.closest(".pbe-block");
            if (!el) return null;
            const block = this.byId(el.dataset.id);
            if (!block) return null;
            return { el, block, content: el.querySelector(".pbe-content") };
        }

        // --- rendering ---

        // Ordered-list numbers, computed the same way serialize resets runs, so the
        // number a user sees matches the "N." written into the saved Markdown.
        _computeNumbers() {
            const map = new Map();
            let previous = null;
            let counters = {};
            this.blocks.forEach((block) => {
                const sameRun = previous && previous.type === block.type && isListType(block.type);
                if (previous && !sameRun) counters = {};
                if (block.type === "numbered") {
                    const level = block.level || 0;
                    Object.keys(counters).forEach((key) => { if (Number(key) > level) delete counters[key]; });
                    counters[level] = (counters[level] || 0) + 1;
                    map.set(block.id, counters[level]);
                }
                previous = block;
            });
            return map;
        }

        renderAll() {
            const activeEl = document.activeElement;
            const activeId = activeEl && activeEl.closest ? activeEl.closest(".pbe-block")?.dataset.id : null;
            const activeOffset = activeId ? getCaretOffset(this.list.querySelector(`[data-id="${activeId}"] .pbe-content`)) : null;

            if (this.blockMenu) this._closeBlockMenu();

            const numbers = this._computeNumbers();
            const onlyBlock = this.blocks.length === 1;
            const hasHeadings = this.blocks.some((block) => block.type === "h1");
            const canArchive = typeof this.options.onArchiveSection === "function";

            this.list.innerHTML = "";
            // With top-level headings, mirror the timeline "section card" look used
            // across the app; otherwise fall back to a plain stack of blocks.
            this.list.className = hasHeadings ? "pbe-list project-section-markdown" : "pbe-list pbe-flat";

            if (!hasHeadings) {
                const fragment = document.createDocumentFragment();
                this.blocks.forEach((block) => fragment.appendChild(this._createBlockEl(block, numbers, onlyBlock)));
                this.list.appendChild(fragment);
            } else {
                let preface = null;
                let card = null;
                let hasSection = false;
                let sectionIndex = -1;
                let archivableIndex = 0;
                this.blocks.forEach((block) => {
                    if (block.type === "h1") {
                        sectionIndex += 1;
                        const section = document.createElement("section");
                        section.className = `project-markdown-section project-markdown-section-tone-${(sectionIndex % 6) + 1}`;
                        const step = document.createElement("div");
                        step.className = "project-markdown-step";
                        step.setAttribute("aria-hidden", "true");
                        card = document.createElement("div");
                        card.className = "project-markdown-section-card";
                        card.appendChild(this._createBlockEl(block, numbers, onlyBlock));
                        section.append(step, card);
                        // The archive endpoint only counts "# " headings that have text,
                        // so only titled sections get an archive button and its index
                        // matches the server's section numbering. Appended to the section
                        // (not the card) so it doesn't disturb block spacing inside the card.
                        if (canArchive && block.text.trim() !== "") {
                            const archiveBtn = document.createElement("button");
                            archiveBtn.type = "button";
                            archiveBtn.className = "project-section-archive-button";
                            archiveBtn.dataset.archiveSection = String(archivableIndex);
                            archiveBtn.title = "Archive section";
                            archiveBtn.setAttribute("aria-label", "Archive section");
                            archiveBtn.innerHTML = "<i class=\"fa-solid fa-box-archive\" aria-hidden=\"true\"></i>";
                            section.appendChild(archiveBtn);
                            archivableIndex += 1;
                        }
                        this.list.appendChild(section);
                        hasSection = true;
                    } else if (hasSection) {
                        card.appendChild(this._createBlockEl(block, numbers, onlyBlock));
                    } else {
                        if (!preface) {
                            preface = document.createElement("div");
                            preface.className = "project-section-preface";
                            this.list.appendChild(preface);
                        }
                        preface.appendChild(this._createBlockEl(block, numbers, onlyBlock));
                    }
                });
            }

            if (activeId != null && activeOffset != null) {
                this.focusBlock(activeId, activeOffset);
            }
            if (this.selectedIds && this.selectedIds.length) {
                this._paintSelection();
            }
        }

        _blockEls() {
            return Array.from(this.list.querySelectorAll(".pbe-block"));
        }

        _createBlockEl(block, numbers, onlyBlock) {
            const el = document.createElement("div");
            el.className = `pbe-block pbe-type-${block.type}`;
            el.dataset.id = block.id;
            if (isListType(block.type)) {
                el.dataset.level = block.level || 0;
                el.style.setProperty("--pbe-indent", block.level || 0);
            }

            const controls = document.createElement("div");
            controls.className = "pbe-controls";
            const handle = document.createElement("button");
            handle.type = "button";
            handle.className = "pbe-handle";
            handle.title = "Drag to move · click to change type";
            handle.setAttribute("aria-label", "Move block or change its type");
            handle.textContent = "⋮⋮";
            controls.append(handle);
            el.appendChild(controls);

            const marker = document.createElement("div");
            marker.className = "pbe-marker";
            if (block.type === "todo") {
                const label = document.createElement("label");
                label.className = "pbe-check";
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.checked = !!block.checked;
                label.appendChild(checkbox);
                marker.appendChild(label);
            } else if (block.type === "bulleted") {
                marker.innerHTML = "<span class=\"pbe-bullet\">•</span>";
            } else if (block.type === "numbered") {
                marker.innerHTML = `<span class="pbe-number">${numbers.get(block.id) || 1}.</span>`;
            }
            el.appendChild(marker);

            if (block.type === "divider") {
                const hr = document.createElement("hr");
                hr.className = "pbe-hr";
                el.appendChild(hr);
            } else {
                const content = document.createElement("div");
                content.className = "pbe-content";
                content.contentEditable = this.supportsPlaintextOnly ? "plaintext-only" : "true";
                content.spellcheck = true;
                content.dataset.placeholder = placeholderFor(block, onlyBlock);
                if (block.type === "todo" && block.checked) {
                    content.classList.add("is-checked");
                }
                content.textContent = block.text || "";
                el.appendChild(content);
            }
            return el;
        }

        focusBlock(id, offset = 0) {
            const content = this.list.querySelector(`[data-id="${id}"] .pbe-content`);
            if (content) {
                setCaretOffset(content, offset === "end" ? content.textContent.length : offset);
            }
        }

        // --- editing behaviours ---

        _onInput(event) {
            const ctx = this.blockFromEvent(event);
            if (!ctx || !ctx.content) return;
            ctx.block.text = ctx.content.textContent;

            if (this._updateSlashMenu(ctx)) {
                this.scheduleSave(`text:${ctx.block.id}`);
                return;
            }
            if (this._maybeTransform(ctx)) {
                return; // re-rendered + saved inside
            }
            // Coalesce a run of typing in the same block into one undo step.
            this.scheduleSave(`text:${ctx.block.id}`);
        }

        _maybeTransform(ctx) {
            const { block, content } = ctx;
            if (block.type !== "paragraph") return false;
            const offset = getCaretOffset(content);
            if (offset == null) return false;
            const before = block.text.slice(0, offset);

            let match;
            let apply = null;
            if ((match = before.match(/^(#{1,3}) $/))) {
                apply = () => { block.type = `h${match[1].length}`; };
            } else if (/^[-*+] $/.test(before)) {
                apply = () => { block.type = "bulleted"; };
            } else if (/^\d+\. $/.test(before)) {
                apply = () => { block.type = "numbered"; };
            } else if ((match = before.match(/^\[( |x|X)?\] $/))) {
                apply = () => { block.type = "todo"; block.checked = /x/i.test(match[1] || ""); };
            } else if (/^> $/.test(before)) {
                apply = () => { block.type = "quote"; };
            } else if (before === "---" || before === "***") {
                block.type = "divider";
                block.text = "";
                const index = this.indexOf(block.id);
                const next = { id: uid(), type: "paragraph", text: "", level: 0 };
                this.blocks.splice(index + 1, 0, next);
                this.renderAll();
                this.focusBlock(next.id, 0);
                this.scheduleSave();
                return true;
            }

            if (!apply) return false;
            apply();
            block.text = block.text.slice(offset);
            this.renderAll();
            this.focusBlock(block.id, 0);
            this.scheduleSave();
            return true;
        }

        _onKeydown(event) {
            if (this.slash && this._slashKeydown(event)) return;

            const ctx = this.blockFromEvent(event);
            if (!ctx) return;
            const { block, content } = ctx;

            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                this._handleEnter(block, content);
            } else if (event.key === "Backspace") {
                const offset = getCaretOffset(content);
                if (offset === 0 && this._selectionCollapsed()) {
                    event.preventDefault();
                    this._handleBackspaceAtStart(block, content);
                }
            } else if (event.key === "Delete") {
                const offset = getCaretOffset(content);
                if (content && offset === content.textContent.length && this._selectionCollapsed()) {
                    if (this._handleDeleteAtEnd(block)) event.preventDefault();
                }
            } else if (event.key === "Tab") {
                if (isListType(block.type)) {
                    event.preventDefault();
                    block.level = event.shiftKey
                        ? Math.max((block.level || 0) - 1, 0)
                        : Math.min((block.level || 0) + 1, MAX_LEVEL);
                    const offset = getCaretOffset(content);
                    this.renderAll();
                    this.focusBlock(block.id, offset ?? 0);
                    this.scheduleSave();
                } else {
                    event.preventDefault();
                }
            } else if (event.key === "ArrowUp" && content && getCaretOffset(content) === 0) {
                const prev = this.blocks[this.indexOf(block.id) - 1];
                if (prev && prev.type !== "divider") { event.preventDefault(); this.focusBlock(prev.id, "end"); }
            } else if (event.key === "ArrowDown" && content && getCaretOffset(content) === content.textContent.length) {
                const next = this.blocks[this.indexOf(block.id) + 1];
                if (next && next.type !== "divider") { event.preventDefault(); this.focusBlock(next.id, 0); }
            }
        }

        _selectionCollapsed() {
            const selection = window.getSelection();
            return !selection || selection.isCollapsed;
        }

        _handleEnter(block, content) {
            const offset = content ? (getCaretOffset(content) ?? block.text.length) : 0;
            const before = (block.text || "").slice(0, offset);
            const after = (block.text || "").slice(offset);

            // Pressing Enter on an empty list/quote item exits back to a paragraph.
            if ((isListType(block.type) || block.type === "quote") && !block.text.trim()) {
                block.type = "paragraph";
                block.level = 0;
                this.renderAll();
                this.focusBlock(block.id, 0);
                this.scheduleSave();
                return;
            }

            block.text = before;
            let nextType = "paragraph";
            let nextLevel = 0;
            if (isListType(block.type) || block.type === "quote") {
                nextType = block.type;
                nextLevel = block.level || 0;
            }
            const next = { id: uid(), type: nextType, text: after, level: nextLevel, checked: false };
            this.blocks.splice(this.indexOf(block.id) + 1, 0, next);
            this.renderAll();
            this.focusBlock(next.id, 0);
            this.scheduleSave();
        }

        _handleBackspaceAtStart(block, content) {
            if (block.type !== "paragraph") {
                if (isListType(block.type) && (block.level || 0) > 0) {
                    block.level -= 1;
                } else {
                    block.type = "paragraph";
                    block.level = 0;
                }
                this.renderAll();
                this.focusBlock(block.id, 0);
                this.scheduleSave();
                return;
            }

            const index = this.indexOf(block.id);
            if (index <= 0) return;
            const prev = this.blocks[index - 1];
            if (prev.type === "divider") {
                this.blocks.splice(index - 1, 1);
                this.renderAll();
                this.focusBlock(block.id, 0);
                this.scheduleSave();
                return;
            }
            const caret = prev.text.length;
            prev.text += block.text;
            this.blocks.splice(index, 1);
            this.renderAll();
            this.focusBlock(prev.id, caret);
            this.scheduleSave();
        }

        _handleDeleteAtEnd(block) {
            const index = this.indexOf(block.id);
            const next = this.blocks[index + 1];
            if (!next) return false;
            if (next.type === "divider") {
                this.blocks.splice(index + 1, 1);
                this.renderAll();
                this.focusBlock(block.id, block.text.length);
                this.scheduleSave();
                return true;
            }
            if (next.type !== "paragraph" && block.text.length) return false;
            const caret = block.text.length;
            block.text += next.text;
            this.blocks.splice(index + 1, 1);
            this.renderAll();
            this.focusBlock(block.id, caret);
            this.scheduleSave();
            return true;
        }

        // --- slash menu ---

        _updateSlashMenu(ctx) {
            const { block, content, el } = ctx;
            const offset = getCaretOffset(content);
            if (offset == null) { this._closeSlash(); return false; }
            const before = block.text.slice(0, offset);
            const match = before.match(/(?:^|\s)\/([\w-]*)$/);
            if (!match) { this._closeSlash(); return false; }

            const query = match[1].toLowerCase();
            const slashStart = offset - match[1].length - 1;
            this.slash = { blockId: block.id, start: slashStart, query, index: 0 };
            this._renderSlashMenu(el);
            return true;
        }

        _filteredCommands() {
            const query = this.slash ? this.slash.query : "";
            if (!query) return SLASH_COMMANDS;
            return SLASH_COMMANDS.filter((cmd) => cmd.label.toLowerCase().includes(query) || cmd.key.includes(query));
        }

        _renderSlashMenu(blockEl) {
            const commands = this._filteredCommands();
            if (!commands.length) { this._closeSlash(); return; }
            if (this.slash.index >= commands.length) this.slash.index = 0;

            this.menu.innerHTML = commands.map((cmd, i) => `
                <button type="button" class="pbe-slash-item ${i === this.slash.index ? "is-active" : ""}" data-key="${cmd.key}">
                    <span class="pbe-slash-label">${cmd.label}</span>
                    <span class="pbe-slash-hint">${cmd.hint}</span>
                </button>
            `).join("");
            this.menu.classList.remove("d-none");

            const blockRect = blockEl.getBoundingClientRect();
            const rootRect = this.root.getBoundingClientRect();
            this.menu.style.top = `${blockRect.bottom - rootRect.top + 4}px`;
            this.menu.style.left = `${Math.max(blockRect.left - rootRect.left, 0)}px`;
        }

        _slashKeydown(event) {
            const commands = this._filteredCommands();
            if (!commands.length) return false;
            if (event.key === "ArrowDown") {
                event.preventDefault();
                this.slash.index = (this.slash.index + 1) % commands.length;
                this._renderSlashMenu(this.list.querySelector(`[data-id="${this.slash.blockId}"]`));
                return true;
            }
            if (event.key === "ArrowUp") {
                event.preventDefault();
                this.slash.index = (this.slash.index - 1 + commands.length) % commands.length;
                this._renderSlashMenu(this.list.querySelector(`[data-id="${this.slash.blockId}"]`));
                return true;
            }
            if (event.key === "Enter" || event.key === "Tab") {
                event.preventDefault();
                this._applySlashCommand(commands[this.slash.index]);
                return true;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                this._closeSlash();
                return true;
            }
            return false;
        }

        _applySlashCommand(command) {
            const slash = this.slash;
            const block = this.byId(slash.blockId);
            this._closeSlash();
            if (!block) return;

            const content = this.list.querySelector(`[data-id="${block.id}"] .pbe-content`);
            const offset = content ? (getCaretOffset(content) ?? block.text.length) : block.text.length;
            const remaining = block.text.slice(0, slash.start) + block.text.slice(offset);

            if (command.divider) {
                if (remaining.trim()) {
                    block.text = remaining;
                    const divider = { id: uid(), type: "divider", text: "", level: 0 };
                    const para = { id: uid(), type: "paragraph", text: "", level: 0 };
                    this.blocks.splice(this.indexOf(block.id) + 1, 0, divider, para);
                    this.renderAll();
                    this.focusBlock(para.id, 0);
                } else {
                    block.type = "divider";
                    block.text = "";
                    if (this.indexOf(block.id) === this.blocks.length - 1) {
                        const para = { id: uid(), type: "paragraph", text: "", level: 0 };
                        this.blocks.push(para);
                        this.renderAll();
                        this.focusBlock(para.id, 0);
                    } else {
                        this.renderAll();
                    }
                }
                this.scheduleSave();
                return;
            }

            block.text = remaining;
            command.apply(block);
            this.renderAll();
            this.focusBlock(block.id, Math.min(slash.start, block.text.length));
            this.scheduleSave();
        }

        _closeSlash() {
            this.slash = null;
            this.menu.classList.add("d-none");
            this.menu.innerHTML = "";
        }

        // --- clicks / checkboxes / focus ---

        _onClick(event) {
            const archiveBtn = event.target.closest(".project-section-archive-button");
            if (archiveBtn) {
                event.preventDefault();
                this.options.onArchiveSection?.(Number(archiveBtn.dataset.archiveSection));
                return;
            }

        }

        // --- block menu (change type / add / duplicate / delete) ---

        _openBlockMenu(blockId, anchorEl) {
            if (this.blockMenuFor === blockId && !this.blockMenu.classList.contains("d-none")) {
                this._closeBlockMenu();
                return;
            }
            const block = this.byId(blockId);
            if (!block) return;
            this.blockMenuFor = blockId;
            const currentKey = block.type === "paragraph" ? "text" : block.type;

            const turnItems = SLASH_COMMANDS.map((cmd) => `
                <button type="button" class="pbe-menu-item ${cmd.key === currentKey ? "is-current" : ""}" data-action="turn" data-key="${cmd.key}">
                    <span class="pbe-menu-label">${cmd.label}</span>
                    ${cmd.key === currentKey ? "<span class=\"pbe-menu-check\">✓</span>" : ""}
                </button>`).join("");

            this.blockMenu.innerHTML = `
                <div class="pbe-menu-heading">Turn into</div>
                ${turnItems}
                <div class="pbe-menu-sep"></div>
                <button type="button" class="pbe-menu-item" data-action="add-below"><span class="pbe-menu-label">Add block below</span></button>
                <button type="button" class="pbe-menu-item" data-action="duplicate"><span class="pbe-menu-label">Duplicate</span></button>
                <button type="button" class="pbe-menu-item pbe-menu-danger" data-action="delete"><span class="pbe-menu-label">Delete</span></button>
            `;
            this.blockMenu.classList.remove("d-none");
            anchorEl.closest(".pbe-block")?.classList.add("pbe-menu-open");

            const anchorRect = anchorEl.getBoundingClientRect();
            const rootRect = this.root.getBoundingClientRect();
            this.blockMenu.style.top = `${anchorRect.bottom - rootRect.top + 4}px`;
            this.blockMenu.style.left = `${Math.max(anchorRect.left - rootRect.left, 0)}px`;
        }

        _closeBlockMenu() {
            this.blockMenuFor = null;
            this.blockMenu.classList.add("d-none");
            this.blockMenu.innerHTML = "";
            this.list.querySelectorAll(".pbe-menu-open").forEach((el) => el.classList.remove("pbe-menu-open"));
        }

        _onBlockMenuClick(event) {
            const item = event.target.closest("[data-action]");
            if (!item) return;
            const action = item.dataset.action;
            const blockId = this.blockMenuFor;
            this._closeBlockMenu();
            if (!blockId || this.indexOf(blockId) < 0) return;

            if (action === "turn") {
                this._turnInto(blockId, item.dataset.key);
            } else if (action === "add-below") {
                const next = { id: uid(), type: "paragraph", text: "", level: 0 };
                this.blocks.splice(this.indexOf(blockId) + 1, 0, next);
                this.renderAll();
                this.focusBlock(next.id, 0);
                this.scheduleSave();
            } else if (action === "duplicate") {
                const index = this.indexOf(blockId);
                const copy = { ...this.blocks[index], id: uid() };
                this.blocks.splice(index + 1, 0, copy);
                this.renderAll();
                this.focusBlock(copy.id, "end");
                this.scheduleSave();
            } else if (action === "delete") {
                const index = this.indexOf(blockId);
                this.blocks.splice(index, 1);
                if (!this.blocks.length) {
                    this.blocks.push({ id: uid(), type: "paragraph", text: "", level: 0 });
                }
                this.renderAll();
                const focus = this.blocks[Math.min(Math.max(index - 1, 0), this.blocks.length - 1)];
                this.focusBlock(focus.id, "end");
                this.scheduleSave();
            }
        }

        _turnInto(blockId, key) {
            const command = SLASH_COMMANDS.find((cmd) => cmd.key === key);
            const block = this.byId(blockId);
            if (!command || !block) return;
            if (command.divider) {
                block.type = "divider";
                block.text = "";
            } else {
                command.apply(block);
            }
            if (!isListType(block.type)) block.level = 0;
            this.renderAll();
            this.focusBlock(blockId, "end");
            this.scheduleSave();
        }

        _onChange(event) {
            const checkbox = event.target.closest(".pbe-check input[type=checkbox]");
            if (!checkbox) return;
            const ctx = this.blockFromEvent(event);
            if (!ctx || ctx.block.type !== "todo") return;
            ctx.block.checked = checkbox.checked;
            ctx.content?.classList.toggle("is-checked", checkbox.checked);
            this.scheduleSave();
        }

        _onFocusIn(event) {
            const el = event.target.closest(".pbe-block");
            if (el) el.classList.add("is-focused");
        }

        _onFocusOut(event) {
            const el = event.target.closest(".pbe-block");
            if (el) el.classList.remove("is-focused");
            // Close the slash menu unless focus moved into the menu itself.
            if (this.slash && !this.root.contains(event.relatedTarget)) {
                this._closeSlash();
            }
        }

        _onPaste(event) {
            const text = event.clipboardData?.getData("text/plain");
            if (!text || !text.includes("\n")) return; // let single-line paste happen natively
            event.preventDefault();
            const ctx = this.blockFromEvent(event);
            if (!ctx) return;
            const { block, content } = ctx;
            const offset = getCaretOffset(content) ?? block.text.length;
            const before = block.text.slice(0, offset);
            const after = block.text.slice(offset);

            const pasted = parseMarkdown(text);
            const wasEmpty = !before && !after;
            block.text = before + (pasted[0].text || "");
            // Only adopt the pasted block's type when dropping onto an empty line;
            // pasting into existing text keeps that line's type and just merges text.
            if (wasEmpty && pasted[0].type !== "paragraph") {
                block.type = pasted[0].type;
                block.level = pasted[0].level || 0;
                block.checked = pasted[0].checked;
            }
            const rest = pasted.slice(1);
            if (after) rest.push({ id: uid(), type: "paragraph", text: after, level: 0 });
            const index = this.indexOf(block.id);
            this.blocks.splice(index + 1, 0, ...rest);
            this.renderAll();
            const last = rest.length ? rest[rest.length - 1].id : block.id;
            this.focusBlock(last, "end");
            this.scheduleSave();
        }

        // --- drag to reorder (pointer based, works with mouse and touch) ---

        _onPointerDown(event) {
            const handle = event.target.closest(".pbe-handle");
            if (!handle) {
                this._maybeStartBlockSelection(event);
                return;
            }
            const el = handle.closest(".pbe-block");
            if (!el) return;
            event.preventDefault();

            const blockId = el.dataset.id;
            // Grabbing the handle of a selected block drags the whole selection.
            const dragMultiple = this.selectedIds.includes(blockId) && this.selectedIds.length > 1;
            const dragIds = dragMultiple ? [...this.selectedIds] : [blockId];
            if (!dragMultiple) this._clearBlockSelection();
            const idSet = new Set(dragIds);

            const startX = event.clientX;
            const startY = event.clientY;
            let started = false;
            handle.setPointerCapture?.(event.pointerId);

            const move = (moveEvent) => {
                if (!started) {
                    if (Math.abs(moveEvent.clientX - startX) + Math.abs(moveEvent.clientY - startY) < 5) {
                        return; // below the drag threshold: still a potential click
                    }
                    started = true;
                    this.drag = { idSet, targetIndex: null };
                    this._blockEls().forEach((b) => { if (idSet.has(b.dataset.id)) b.classList.add("pbe-dragging"); });
                    this._closeBlockMenu();
                }
                this._dragMove(moveEvent);
            };
            const up = (upEvent) => {
                document.removeEventListener("pointermove", move);
                document.removeEventListener("pointerup", up);
                if (started) {
                    this._dragEnd(upEvent);
                } else {
                    // A click on the handle (no drag): open the block menu.
                    this._openBlockMenu(blockId, handle);
                }
            };
            document.addEventListener("pointermove", move);
            document.addEventListener("pointerup", up);
        }

        _dragMove(event) {
            if (!this.drag) return;
            const idSet = this.drag.idSet;
            const rows = this._blockEls();
            rows.forEach((row) => row.classList.remove("pbe-drop-before", "pbe-drop-after"));

            let targetRow = null;
            let placeAfter = false;
            for (const row of rows) {
                if (idSet.has(row.dataset.id)) continue; // don't target a block being dragged
                const rect = row.getBoundingClientRect();
                if (event.clientY >= rect.top) {
                    targetRow = row;
                    placeAfter = event.clientY > rect.top + rect.height / 2;
                }
            }

            if (!targetRow) {
                const first = rows.find((row) => !idSet.has(row.dataset.id));
                if (first) { first.classList.add("pbe-drop-before"); this.drag.targetIndex = this.indexOf(first.dataset.id); }
                return;
            }
            targetRow.classList.add(placeAfter ? "pbe-drop-after" : "pbe-drop-before");
            const targetIdx = this.indexOf(targetRow.dataset.id);
            this.drag.targetIndex = placeAfter ? targetIdx + 1 : targetIdx;
        }

        _dragEnd() {
            if (!this.drag) return;
            const { idSet, targetIndex } = this.drag;
            this._blockEls().forEach((row) => row.classList.remove("pbe-drop-before", "pbe-drop-after", "pbe-dragging"));
            this.drag = null;
            if (targetIndex == null) return;

            // Pull out the dragged block(s) in document order and re-insert them as a
            // contiguous run at the drop point (works for one block or a whole selection).
            const moved = this.blocks.filter((block) => idSet.has(block.id));
            if (!moved.length) return;
            const removedBefore = this.blocks.slice(0, targetIndex).filter((block) => idSet.has(block.id)).length;
            const remaining = this.blocks.filter((block) => !idSet.has(block.id));
            const insertAt = Math.max(0, Math.min(targetIndex - removedBefore, remaining.length));
            remaining.splice(insertAt, 0, ...moved);
            this.blocks = remaining;
            this.renderAll(); // repaints the (still-selected) moved blocks
            // Keep focus in the editor after a single-block move so Ctrl+Z reaches it.
            if (!this.selectedIds.length) this.focusBlock(moved[0].id, "end");
            this.scheduleSave();
        }

        // --- multi-block selection (drag across blocks to select a range) ---

        _maybeStartBlockSelection(event) {
            if (event.button !== 0) return;
            const content = event.target.closest(".pbe-content");
            if (!content) { this._clearBlockSelection(); return; }
            const startEl = content.closest(".pbe-block");
            if (!startEl) return;
            const startId = startEl.dataset.id;
            // A fresh press clears any existing block selection; single-block text
            // selection stays native until the drag crosses into another block.
            this._clearBlockSelection();

            let selecting = false;
            const onMove = (moveEvent) => {
                const overEl = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
                const overBlock = overEl && overEl.closest ? overEl.closest(".pbe-block") : null;
                if (!overBlock || !this.list.contains(overBlock)) return;
                if (overBlock.dataset.id === startId && !selecting) return; // still within one block

                if (!selecting) {
                    selecting = true;
                    this.list.classList.add("pbe-selecting");
                }
                window.getSelection()?.removeAllRanges();
                this._selectBlockRange(startId, overBlock.dataset.id);
                moveEvent.preventDefault();
            };
            const onUp = () => {
                document.removeEventListener("pointermove", onMove);
                document.removeEventListener("pointerup", onUp);
                this.list.classList.remove("pbe-selecting");
                if (selecting) {
                    // Drop the caret so the block selection is the only visible one.
                    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
                }
            };
            document.addEventListener("pointermove", onMove);
            document.addEventListener("pointerup", onUp);
        }

        _selectBlockRange(idA, idB) {
            const a = this.indexOf(idA);
            const b = this.indexOf(idB);
            if (a < 0 || b < 0) return;
            const lo = Math.min(a, b);
            const hi = Math.max(a, b);
            this.selectedIds = this.blocks.slice(lo, hi + 1).map((block) => block.id);
            this._paintSelection();
        }

        _paintSelection() {
            const selected = new Set(this.selectedIds);
            this._blockEls().forEach((el) => el.classList.toggle("pbe-selected", selected.has(el.dataset.id)));
        }

        _clearBlockSelection() {
            if (!this.selectedIds.length) return;
            this.selectedIds = [];
            this.list.querySelectorAll(".pbe-selected").forEach((el) => el.classList.remove("pbe-selected"));
        }

        _selectedMarkdown() {
            const selected = new Set(this.selectedIds);
            return serializeBlocks(this.blocks.filter((block) => selected.has(block.id)));
        }

        _deleteSelected() {
            if (!this.selectedIds.length) return;
            const selected = new Set(this.selectedIds);
            const firstIndex = this.blocks.findIndex((block) => selected.has(block.id));
            this.blocks = this.blocks.filter((block) => !selected.has(block.id));
            if (!this.blocks.length) {
                this.blocks.push({ id: uid(), type: "paragraph", text: "", level: 0 });
            }
            this.selectedIds = [];
            this.renderAll();
            const focus = this.blocks[Math.min(firstIndex, this.blocks.length - 1)] || this.blocks[0];
            this.focusBlock(focus.id, 0);
            this.scheduleSave();
        }

        // --- autosave ---

        getMarkdown() { return serializeBlocks(this.blocks); }

        setMarkdown(markdown) {
            this.blocks = parseMarkdown(markdown);
            this.selectedIds = [];
            this.renderAll();
            // A wholesale replacement (mode switch, archive/restore) starts a fresh history.
            this.undoStack = [this._snapshot()];
            this.redoStack = [];
            this._lastGroup = null;
        }

        // Called after every change. `group` coalesces rapid same-context edits (e.g.
        // typing in one block) into a single undo step; `commit` is false when the change
        // itself came from an undo/redo restore so it doesn't create new history.
        scheduleSave(group, commit = true) {
            if (commit) this._commit(group);
            this.dirty = true;
            try { this.onChange(this.getMarkdown()); } catch (error) { /* ignore */ }
            this.onStatus("unsaved");
            clearTimeout(this.saveTimer);
            this.saveTimer = setTimeout(() => this.flush(), this.saveDelay);
        }

        // --- undo / redo ---

        _snapshot() {
            let caret = null;
            const active = document.activeElement;
            const el = active && active.closest ? active.closest(".pbe-block") : null;
            if (el && this.list.contains(el)) {
                const content = el.querySelector(".pbe-content");
                caret = { id: el.dataset.id, offset: content ? (getCaretOffset(content) ?? 0) : 0 };
            }
            return {
                blocks: this.blocks.map((block) => ({ ...block })),
                selectedIds: [...this.selectedIds],
                caret,
            };
        }

        _commit(group) {
            const now = Date.now();
            const snap = this._snapshot();
            const coalesce = group && group === this._lastGroup
                && (now - this._lastCommitTime) < 700 && this.undoStack.length > 0;
            if (coalesce) {
                this.undoStack[this.undoStack.length - 1] = snap;
            } else {
                this.undoStack.push(snap);
                if (this.undoStack.length > 200) this.undoStack.shift();
            }
            this.redoStack.length = 0;
            this._lastGroup = group || null;
            this._lastCommitTime = now;
        }

        _restore(snap) {
            this._closeBlockMenu();
            this.blocks = snap.blocks.map((block) => ({ ...block }));
            this.selectedIds = [...(snap.selectedIds || [])];
            this.renderAll();
            if (snap.caret) {
                this.focusBlock(snap.caret.id, snap.caret.offset);
            }
            this.scheduleSave(null, false); // reflect + autosave, but don't add history
        }

        undo() {
            if (this.undoStack.length <= 1) return;
            const current = this.undoStack.pop();
            this.redoStack.push(current);
            this._lastGroup = null;
            this._restore(this.undoStack[this.undoStack.length - 1]);
        }

        redo() {
            if (!this.redoStack.length) return;
            const next = this.redoStack.pop();
            this.undoStack.push(next);
            this._lastGroup = null;
            this._restore(next);
        }

        async flush() {
            clearTimeout(this.saveTimer);
            if (!this.dirty || this.saving) return;
            this.saving = true;
            this.dirty = false;
            this.onStatus("saving");
            try {
                const ok = await this.onSaveMarkdown(this.getMarkdown());
                this.onStatus(ok ? "saved" : "error");
                if (!ok) this.dirty = true;
            } catch (error) {
                this.onStatus("error");
                this.dirty = true;
            } finally {
                this.saving = false;
                if (this.dirty) this.scheduleSave(null, false);
            }
        }

        hasUnsavedChanges() {
            return this.dirty || this.saving;
        }
    }

    window.PlanBlockEditor = {
        mount(container, options) { return new PlanBlockEditor(container, options); },
        parseMarkdown,
        serializeBlocks,
    };
})();
