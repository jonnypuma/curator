// Activity history: what Curator deleted, restored, renamed, moved or changed, and why.

state.activityHistory = { items: [], actions: [], search: "", action: "", timer: 0 };

const HISTORY_ACTIONS = {
    deleted: "Deleted", restored: "Restored", purged: "Deleted for good", removed: "Removed from library", renamed: "Renamed",
    moved: "Moved", changed: "Changed", cleanup: "Bulk cleanup", corrupt: "Found corrupt", synced: "Watched sync", alert: "Alert",
};

async function openActivityHistory() {
    document.getElementById("history-modal").classList.remove("hidden");
    await loadActivityHistory();
}

async function loadActivityHistory() {
    const { search, action } = state.activityHistory;
    const data = await api(`/api/v1/history?search=${encodeURIComponent(search)}&action=${encodeURIComponent(action)}&limit=500`);
    state.activityHistory.items = data.items || [];
    state.activityHistory.actions = data.actions || [];
    renderActivityHistory();
}

function renderActivityHistory() {
    const pick = document.getElementById("history-action");
    const chosen = state.activityHistory.action;
    pick.innerHTML = `<option value="">All actions</option>${state.activityHistory.actions.map((name) => `<option value="${escapeHtml(name)}" ${name === chosen ? "selected" : ""}>${escapeHtml(HISTORY_ACTIONS[name] || name)}</option>`).join("")}`;
    const rows = state.activityHistory.items;
    document.getElementById("history-list").innerHTML = rows.length
        ? `<table class="queue-table"><thead><tr><th>When</th><th>What</th><th>Item</th><th>Why</th></tr></thead><tbody>${rows.map((row) => `<tr>
                <td class="queue-fit">${escapeHtml(String(row.at || "").replace("T", " "))}</td>
                <td class="queue-fit">${escapeHtml(HISTORY_ACTIONS[row.action] || row.action)}</td>
                <td><strong>${escapeHtml(row.title || "")}</strong>${row.detail ? ` <small class="muted">${escapeHtml(row.detail)}</small>` : ""}${row.path ? `<br><small class="mono muted">${escapeHtml(row.path)}</small>` : ""}</td>
                <td>${escapeHtml(row.reason || "")}</td>
            </tr>`).join("")}</tbody></table>`
        : `<p class="muted">Nothing listed.</p>`;
}

function onHistoryAction(name) {
    if (name === "history-open") return runAction(openActivityHistory);
    return false;
}

document.addEventListener("input", (event) => {
    if (event.target && event.target.id === "history-search") {
        state.activityHistory.search = event.target.value || "";
        clearTimeout(state.activityHistory.timer);
        state.activityHistory.timer = setTimeout(() => loadActivityHistory().catch(() => {}), 300);
    }
});

document.addEventListener("change", (event) => {
    if (event.target && event.target.id === "history-action") {
        state.activityHistory.action = event.target.value || "";
        loadActivityHistory().catch(() => {});
    }
});
