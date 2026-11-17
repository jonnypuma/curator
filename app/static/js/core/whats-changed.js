// What changed: added items, deletes and renames, replaced artwork and failed jobs for a chosen period.

state.whatsChanged = { days: 7, data: null };

const CHANGE_PERIODS = { 1: "Last 24 hours", 7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days" };

async function openWhatsChanged() {
    document.getElementById("changes-modal").classList.remove("hidden");
    await loadWhatsChanged();
}

async function loadWhatsChanged() {
    const body = document.getElementById("changes-body");
    if (!state.whatsChanged.data) body.innerHTML = `<p class="muted">Loading…</p>`;
    state.whatsChanged.data = await api(`/api/v1/changes?days=${encodeURIComponent(state.whatsChanged.days)}`);
    renderWhatsChanged();
}

function changeWhen(value) {
    return String(value || "").replace("T", " ").slice(0, 16);
}

// One foldable block: a heading with its count, then the lines. Empty blocks are left out by the caller.
function changeBlock(title, count, lines, open) {
    return `<details class="changes-block"${open ? " open" : ""}>
        <summary><strong>${escapeHtml(title)}</strong> <span class="album-count">${Number(count) || 0}</span></summary>
        <ul class="changes-list">${lines.join("")}</ul></details>`;
}

function changeNames(names) {
    return (names || []).map((name) => `<li>${escapeHtml(name)}</li>`);
}

function whatsChangedBlocks(data) {
    const blocks = [];
    const added = data.added || {};
    const groups = [["Movies added", added.movies, (added.movies || []).length], ["TV episodes added", added.shows, added.episodes],
        ["Albums added", added.albums, (added.albums || []).length], ["Music videos added", added.musicvideos, (added.musicvideos || []).length]];
    for (const [title, names, count] of groups) {
        if ((names || []).length) blocks.push(changeBlock(title, count, changeNames(names), true));
    }
    const activity = data.activity || { counts: {}, items: [] };
    const labels = typeof HISTORY_ACTIONS === "object" ? HISTORY_ACTIONS : {};
    for (const action of Object.keys(activity.counts || {})) {
        const rows = (activity.items || []).filter((row) => row.action === action);
        const lines = rows.map((row) => `<li><span class="muted">${escapeHtml(changeWhen(row.at))}</span> ${escapeHtml(row.title || "")}${row.detail ? ` <small class="muted">${escapeHtml(row.detail)}</small>` : ""}${row.reason ? ` <small class="muted">· ${escapeHtml(row.reason)}</small>` : ""}</li>`);
        const more = activity.counts[action] - rows.length;
        if (more > 0) lines.push(`<li class="muted">and ${more} more, in Tools, Activity history</li>`);
        blocks.push(changeBlock(labels[action] || action, activity.counts[action], lines, false));
    }
    const art = data.artwork || { count: 0, items: [] };
    if (art.count) {
        const lines = (art.items || []).map((row) => `<li><span class="muted">${escapeHtml(changeWhen(row.at))}</span> ${escapeHtml(row.title || `A ${row.kind}`)} <small class="muted">${escapeHtml(row.art)}</small></li>`);
        if (art.count > lines.length) lines.push(`<li class="muted">and ${art.count - lines.length} more</li>`);
        blocks.push(changeBlock("Artwork replaced", art.count, lines, false));
    }
    const failed = (data.jobs || {}).failed || [];
    if (failed.length) {
        blocks.push(changeBlock("Failed jobs", failed.length, failed.map((row) => `<li><span class="muted">${escapeHtml(changeWhen(row.at))}</span> <strong>${escapeHtml(row.label)}</strong>${row.message ? ` <small class="settings-warning">${escapeHtml(row.message)}</small>` : ""}</li>`), true));
    }
    return blocks;
}

function renderWhatsChanged() {
    const data = state.whatsChanged.data || {};
    const pick = document.getElementById("changes-period");
    pick.innerHTML = (data.periods || [1, 7, 30, 90]).map((days) => `<option value="${days}" ${Number(days) === Number(data.days) ? "selected" : ""}>${escapeHtml(CHANGE_PERIODS[days] || `Last ${days} days`)}</option>`).join("");
    const blocks = whatsChangedBlocks(data);
    const finished = (data.jobs || {}).finished || 0;
    document.getElementById("changes-note").textContent = `${changeWhen(data.since)} to ${changeWhen(data.until)}. ${finished} job${finished === 1 ? "" : "s"} finished in this period.`;
    document.getElementById("changes-body").innerHTML = blocks.length ? blocks.join("") : `<p class="muted">Nothing changed in this period.</p>`;
}

document.addEventListener("change", (event) => {
    if (event.target && event.target.id === "changes-period") {
        state.whatsChanged.days = Number(event.target.value) || 7;
        runAction(loadWhatsChanged, "Loading…");
    }
});
