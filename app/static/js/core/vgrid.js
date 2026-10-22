// Poster grid: card size (Small / Medium / Large) and windowing. Only the cards in view, plus a few rows either
// side, are in the page, so a library of thousands costs the same as a library of dozens.

const VGRID_MIN = { small: 96, medium: 136, large: 190 };
const VGRID_META = { small: 36, medium: 56, large: 92 };   // first guess for the text under a poster; measured after painting
const VGRID_GAP = 12;
const VGRID_PAD = 12;
const VGRID_OVERSCAN = 2;

function vgridSize() {
    let size = "medium";
    try { size = localStorage.getItem("curator.gridSize") || "medium"; } catch (error) { /* private window */ }
    return VGRID_MIN[size] ? size : "medium";
}

function setGridSize(size) {
    if (!VGRID_MIN[size]) return;
    try { localStorage.setItem("curator.gridSize", size); } catch (error) { /* private window */ }
    syncGridSizeButtons();
    if (typeof state !== "undefined" && state.media === "music") {
        if (state.musicViewMode === "grid" && typeof renderTree === "function") renderTree();
    } else if (typeof videoViewMode === "function" && videoViewMode() === "grid" && typeof renderVideoList === "function") {
        renderVideoList();
    }
}

function syncGridSizeButtons() {
    const size = vgridSize();
    document.querySelectorAll("[data-grid-size]").forEach((button) => {
        button.setAttribute("aria-pressed", button.dataset.gridSize === size ? "true" : "false");
    });
}

function vgridMount(host, options) {
    if (!host) return;
    const previous = host._vg;
    const keep = previous && previous.kind === options.kind ? host.scrollTop : 0;
    const size = vgridSize();
    const g = host._vg = {
        kind: options.kind || "",
        items: options.items || [],
        render: options.render,
        key: options.key,
        after: options.after,
        ratio: options.ratio || 1.5,
        size,
        cols: 1,
        rowH: 0,
        meta: VGRID_META[size],
        first: -1,
        last: -1,
        measured: 0,
    };
    if (!g.items.length) {
        host.innerHTML = options.empty || "";
        return;
    }
    host.innerHTML = `<div class="vposter-grid is-windowed" data-grid-size-now="${size}"></div>`;
    g.grid = host.firstElementChild;
    vgridLayout(host);
    host.scrollTop = keep;
    vgridPaint(host, true);
    if (!host._vgBound) {
        host._vgBound = true;
        let queued = false;
        host.addEventListener("scroll", () => {
            if (queued) return;
            queued = true;
            requestAnimationFrame(() => { queued = false; vgridPaint(host, false); });
        }, { passive: true });
        if (typeof ResizeObserver === "function") {
            new ResizeObserver(() => {
                const now = host._vg;
                if (!now || !now.grid || !host.contains(now.grid)) return;
                const before = now.cols;
                const anchor = now.first >= 0 ? now.first * before : 0;
                vgridLayout(host);
                if (now.cols !== before) host.scrollTop = Math.floor(anchor / now.cols) * now.rowH;
                vgridPaint(host, true);
            }).observe(host);
        }
    }
}

function vgridLayout(host) {
    const g = host._vg;
    const width = Math.max(0, g.grid.clientWidth - VGRID_PAD * 2);
    const min = VGRID_MIN[g.size];
    g.cols = Math.max(1, Math.floor((width + VGRID_GAP) / (min + VGRID_GAP)));
    const cardW = (width - VGRID_GAP * (g.cols - 1)) / g.cols;
    g.poster = Math.max(40, cardW * g.ratio);
    g.rowH = Math.round(g.poster + g.meta + 2 + VGRID_GAP);
    g.rows = Math.ceil(g.items.length / g.cols);
    g.grid.style.gridTemplateColumns = `repeat(${g.cols}, minmax(0, 1fr))`;
}

function vgridPaint(host, force) {
    const g = host._vg;
    if (!g || !g.grid || !g.items.length || !host.contains(g.grid)) return;
    const top = Math.max(0, host.scrollTop);
    const view = host.clientHeight || 600;
    const first = Math.max(0, Math.floor((top - VGRID_PAD) / g.rowH) - VGRID_OVERSCAN);
    const last = Math.min(g.rows - 1, Math.ceil((top + view) / g.rowH) + VGRID_OVERSCAN);
    if (!force && first === g.first && last === g.last) return;
    g.first = first;
    g.last = last;
    const from = first * g.cols;
    const to = Math.min(g.items.length, (last + 1) * g.cols);
    let html = "";
    for (let i = from; i < to; i += 1) html += g.render(g.items[i], g.size);
    g.grid.style.paddingTop = `${VGRID_PAD + first * g.rowH}px`;
    g.grid.style.paddingBottom = `${VGRID_PAD + Math.max(0, g.rows - 1 - last) * g.rowH}px`;
    g.grid.innerHTML = html;
    if (typeof g.after === "function") g.after(host);
    // Replace the guess for the text under the poster with the real height, once or twice.
    const card = g.grid.querySelector(".vgrid-card");
    if (card && g.measured < 3) {
        const real = card.offsetHeight;
        const expected = g.rowH - VGRID_GAP;
        if (real && Math.abs(real - expected) > 1) {
            g.measured += 1;
            g.meta = Math.max(20, g.meta + (real - expected));
            const anchor = first * g.cols;
            vgridLayout(host);
            host.scrollTop = Math.floor(anchor / g.cols) * g.rowH;
            vgridPaint(host, true);
        }
    }
}

// Scroll so the item with this key is in view, and paint it, so a caller can then find its card.
function vgridReveal(host, key) {
    const g = host && host._vg;
    if (!g || !g.items.length) return false;
    const index = g.items.findIndex((item) => g.key(item) === key);
    if (index < 0) return false;
    const rowTop = VGRID_PAD + Math.floor(index / g.cols) * g.rowH;
    const rowBottom = rowTop + g.rowH - VGRID_GAP;
    if (rowTop < host.scrollTop) host.scrollTop = Math.max(0, rowTop - VGRID_PAD);
    else if (rowBottom > host.scrollTop + host.clientHeight) host.scrollTop = rowBottom - host.clientHeight + VGRID_PAD;
    vgridPaint(host, true);
    return true;
}

document.addEventListener("DOMContentLoaded", syncGridSizeButtons);
