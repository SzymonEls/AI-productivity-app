/**
 * The "Last two weeks" chart under the System health rings on the home page: the
 * score as it stood on each of the last fifteen mornings, and the week's mood
 * average beside it as a second line, worked out only when asked for.
 *
 * The same shape as the Statistics card on a project page (project-statistics.js):
 * the section arrives empty, Show asks the server, a spinner stands in while it
 * counts, and the chart is drawn in place. The points read two weeks of bookings
 * to sum fifteen overlapping weeks, and the home page is opened far more often than
 * the line is wanted, so the page itself never pays for it.
 *
 * Asking again re-reads rather than redrawing what came back before: a session
 * ticked off in another tab should move the line.
 */
(function () {
    "use strict";

    const section = document.querySelector("[data-health-history]");
    if (!section) {
        return;
    }

    const endpoint = section.dataset.historyUrl || "";
    const button = section.querySelector("[data-health-history-load]");
    const loading = section.querySelector("[data-health-history-loading]");
    const chart = section.querySelector("[data-health-history-chart]");
    const note = section.querySelector("[data-health-history-note]");

    const SVG_NS = "http://www.w3.org/2000/svg";
    // The drawing's own units; the SVG scales to the sidebar's width.
    const WIDTH = 280;
    const HEIGHT = 150;
    // Room on the right for the mood scale's 1-5.
    const PAD = { top: 14, right: 22, bottom: 18, left: 24 };
    // Where the ring turns amber and red (HEALTH_*_PERCENT in slots.py), drawn
    // dashed; 0 and 100 are the frame.
    const THRESHOLDS = [50, 75];

    let pending = false;

    function show(element, visible) {
        element?.classList.toggle("d-none", !visible);
    }

    function setNote(message, tone) {
        if (!note) {
            return;
        }
        note.textContent = message || "";
        note.className = `statistics-note mb-0${tone ? ` statistics-note-${tone}` : ""}${message ? "" : " d-none"}`;
    }

    function setLoading(on) {
        pending = on;
        show(loading, on);
        if (button) {
            button.disabled = on;
        }
        if (on) {
            show(chart, false);
            setNote("", "");
        }
    }

    function svg(tag, attributes, text) {
        const element = document.createElementNS(SVG_NS, tag);
        Object.entries(attributes || {}).forEach(([name, value]) => element.setAttribute(name, value));
        if (text !== undefined) {
            element.textContent = text;
        }
        return element;
    }

    function describe(point) {
        const day = point.label === "Today" ? "Today" : point.label;
        const sessions = point.booked ? `${point.done} of ${point.booked} sessions done` : "nothing booked";
        let mood = "mood not rated that week";
        if (point.mood !== null && point.mood !== undefined) {
            const own = point.mood_score ? `, ${point.mood_score} that day` : "";
            mood = `mood ${point.mood.toFixed(1)} (7-day average${own})`;
        }
        return `${day}: ${point.percent} — ${sessions}; ${mood}`;
    }

    const hasMood = (point) => point.mood !== null && point.mood !== undefined;

    // The mood scale laid over the score's: 1 sits on 0 and 5 on 100, which
    // puts 3 and 4 exactly on the dashed 50 and 75, so the one set of lines
    // reads for both and the right-hand axis needs no grid of its own.
    const moodPercent = (mood) => ((mood - 1) / 4) * 100;
    const moodLabel = (percent) => String(1 + (percent / 100) * 4);

    // The key above the chart, which also carries where each line has got to
    // today: two lines' worth of numbers on the ends would sit on top of each
    // other in a chart this small, and every other point says its own on hover.
    function legend(history) {
        const box = document.createElement("div");
        box.className = "health-chart-legend";
        box.setAttribute("aria-hidden", "true");
        const last = history[history.length - 1];
        const entries = [["is-sessions", "Sessions done", String(last.percent), "/100"]];
        if (history.some(hasMood)) {
            entries.push(["is-mood", "Mood", hasMood(last) ? last.mood.toFixed(1) : "–", "/5"]);
        }
        entries.forEach(([kind, name, value, scale]) => {
            const entry = document.createElement("span");
            entry.className = `health-chart-legend-entry ${kind}`;
            const swatch = document.createElement("span");
            swatch.className = "health-chart-legend-swatch";
            const figure = document.createElement("span");
            figure.className = "health-chart-legend-value";
            figure.textContent = value;
            const scaleText = document.createElement("span");
            scaleText.className = "health-chart-legend-scale";
            scaleText.textContent = scale;
            figure.append(scaleText);
            entry.append(swatch, document.createTextNode(name), figure);
            box.append(entry);
        });
        return box;
    }

    function render(history) {
        const plotWidth = WIDTH - PAD.left - PAD.right;
        const plotHeight = HEIGHT - PAD.top - PAD.bottom;
        const x = (index) => PAD.left + (history.length > 1 ? (index * plotWidth) / (history.length - 1) : plotWidth / 2);
        const y = (percent) => PAD.top + ((100 - percent) / 100) * plotHeight;
        const moodY = (mood) => y(moodPercent(mood));
        const showMood = history.some(hasMood);

        const first = history[0];
        const last = history[history.length - 1];
        const root = svg("svg", {
            viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
            role: "img",
            "aria-label": `System health over the last two weeks: ${first.percent} two weeks ago, ${last.percent} today.${
                hasMood(last) ? ` Average mood today ${last.mood.toFixed(1)} out of 5.` : ""
            }`,
        });

        [0, ...THRESHOLDS, 100].forEach((value) => {
            const isThreshold = THRESHOLDS.includes(value);
            root.append(
                svg("line", {
                    class: isThreshold ? "health-chart-threshold" : "health-chart-grid",
                    x1: PAD.left,
                    x2: WIDTH - PAD.right,
                    y1: y(value),
                    y2: y(value),
                }),
                svg("text", { class: "health-chart-axis", x: PAD.left - 5, y: y(value) + 3, "text-anchor": "end" }, String(value))
            );
            if (showMood) {
                root.append(
                    svg(
                        "text",
                        { class: "health-chart-axis is-mood", x: WIDTH - PAD.right + 5, y: y(value) + 3, "text-anchor": "start" },
                        moodLabel(value)
                    )
                );
            }
        });

        history.forEach((point, index) => {
            // Every other day, counted back from today so "Today" always has
            // its label: fifteen would not fit side by side in the sidebar.
            // The day of the month is enough; the tooltip names the weekday.
            if ((history.length - 1 - index) % 2) {
                return;
            }
            const label = point.label === "Today" ? "Today" : String(Number(point.date.slice(8, 10)));
            root.append(
                svg(
                    "text",
                    {
                        class: "health-chart-axis",
                        x: x(index),
                        y: HEIGHT - 4,
                        "text-anchor": "middle",
                    },
                    label
                )
            );
        });

        root.append(
            svg("polyline", {
                class: "health-chart-line",
                points: history.map((point, index) => `${x(index)},${y(point.percent)}`).join(" "),
            })
        );

        // The mood line breaks over a week with nothing rated rather than
        // inventing a value to bridge it.
        let run = [];
        const flush = () => {
            if (run.length > 1) {
                root.append(svg("polyline", { class: "health-chart-mood-line", points: run.join(" ") }));
            }
            run = [];
        };
        history.forEach((point, index) => {
            if (hasMood(point)) {
                run.push(`${x(index)},${moodY(point.mood)}`);
            } else {
                flush();
            }
        });
        flush();

        history.forEach((point, index) => {
            // A hit area a whole column wide, so the hover does not need to
            // land on an 8px dot; it sits just before its points, which the
            // stylesheet outlines while it is hovered.
            const columnWidth = plotWidth / Math.max(history.length - 1, 1);
            const hit = svg("rect", {
                class: "health-chart-hit",
                x: x(index) - columnWidth / 2,
                y: PAD.top - 6,
                width: columnWidth,
                height: plotHeight + 12,
            });
            hit.append(svg("title", {}, describe(point)));
            const column = svg("g", { class: "health-chart-column", "pointer-events": "none" });
            if (hasMood(point)) {
                column.append(
                    svg("circle", {
                        class: "health-chart-mood-point",
                        cx: x(index),
                        cy: moodY(point.mood),
                        r: 3,
                    })
                );
            }
            column.append(
                svg("circle", {
                    class: `health-chart-point is-${point.level}`,
                    cx: x(index),
                    cy: y(point.percent),
                    r: 4,
                })
            );
            root.append(hit, column);
        });

        // The same figures as text, for whoever cannot see the lines.
        const list = document.createElement("ul");
        list.className = "visually-hidden";
        history.forEach((point) => {
            const item = document.createElement("li");
            item.textContent = describe(point);
            list.append(item);
        });

        chart.replaceChildren(legend(history), root, list);
        show(chart, true);

        const change = last.percent - first.percent;
        const direction = change > 0 ? `Sessions up ${change}` : change < 0 ? `Sessions down ${-change}` : "Sessions unchanged";
        let moodNote = "";
        if (hasMood(first) && hasMood(last)) {
            const moodChange = Math.round((last.mood - first.mood) * 10) / 10;
            moodNote =
                moodChange > 0 ? `, mood up ${moodChange.toFixed(1)}` : moodChange < 0 ? `, mood down ${(-moodChange).toFixed(1)}` : ", mood unchanged";
        }
        setNote(`${direction}${moodNote} since two weeks ago.`, "quiet");
    }

    function load() {
        if (pending || !endpoint) {
            return;
        }
        setLoading(true);

        fetch(endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not work out the history.");
                }
                return payload.history;
            })
            .then((history) => {
                setLoading(false);
                if (!history || !history.length) {
                    setNote("Nothing to draw yet.", "quiet");
                    return;
                }
                render(history);
                if (button) {
                    button.textContent = "Refresh";
                }
            })
            .catch((error) => {
                setLoading(false);
                setNote(error.message, "bad");
            });
    }

    button?.addEventListener("click", load);
})();
