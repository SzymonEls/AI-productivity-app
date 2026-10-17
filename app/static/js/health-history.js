/**
 * The "Last week" line under the System health ring on the home page: the score
 * as it stood on each of the last eight mornings, worked out only when asked for.
 *
 * The same shape as the Statistics card on a project page (project-statistics.js):
 * the section arrives empty, Show asks the server, a spinner stands in while it
 * counts, and the chart is drawn in place. The points read two weeks of bookings
 * to sum eight overlapping weeks, and the home page is opened far more often than
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
    const HEIGHT = 130;
    const PAD = { top: 14, right: 16, bottom: 18, left: 24 };
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
        return `${day}: ${point.percent} — ${sessions}`;
    }

    function render(history) {
        const plotWidth = WIDTH - PAD.left - PAD.right;
        const plotHeight = HEIGHT - PAD.top - PAD.bottom;
        const x = (index) => PAD.left + (history.length > 1 ? (index * plotWidth) / (history.length - 1) : plotWidth / 2);
        const y = (percent) => PAD.top + ((100 - percent) / 100) * plotHeight;

        const first = history[0];
        const last = history[history.length - 1];
        const root = svg("svg", {
            viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
            role: "img",
            "aria-label": `System health over the last week: ${first.percent} a week ago, ${last.percent} today.`,
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
        });

        history.forEach((point, index) => {
            // The day of the month is enough under a week of points; the
            // tooltip names the weekday.
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

        history.forEach((point, index) => {
            // A hit area a whole column wide, so the hover does not need to
            // land on an 8px dot; it sits just before its point, which the
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
            root.append(
                hit,
                svg("circle", {
                    class: `health-chart-point is-${point.level}`,
                    cx: x(index),
                    cy: y(point.percent),
                    r: 4,
                    "pointer-events": "none",
                })
            );
        });

        // Only the two ends carry their number: where the week started and
        // where it has got to. Every other point says it on hover.
        [
            [0, "start"],
            [history.length - 1, "end"],
        ].forEach(([index, anchor]) => {
            const point = history[index];
            const above = point.percent < 85;
            root.append(
                svg(
                    "text",
                    {
                        class: "health-chart-value",
                        x: x(index) + (anchor === "start" ? -2 : 2),
                        y: y(point.percent) + (above ? -8 : 14),
                        "text-anchor": anchor,
                        "pointer-events": "none",
                    },
                    String(point.percent)
                )
            );
        });

        // The same figures as text, for whoever cannot see the line.
        const list = document.createElement("ul");
        list.className = "visually-hidden";
        history.forEach((point) => {
            const item = document.createElement("li");
            item.textContent = describe(point);
            list.append(item);
        });

        chart.replaceChildren(root, list);
        show(chart, true);

        const change = last.percent - first.percent;
        const direction = change > 0 ? `Up ${change}` : change < 0 ? `Down ${-change}` : "Unchanged";
        setNote(`${direction} since a week ago.`, "quiet");
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
