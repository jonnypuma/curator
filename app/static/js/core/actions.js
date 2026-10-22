function toggleArtist(id) {
    if (state.expanded.has(id)) state.expanded.delete(id);
    else state.expanded.add(id);
    persistExpanded();
    renderTree();
}

function persistExpanded() {
    sessionStorage.setItem("resonance.expanded", JSON.stringify([...state.expanded]));
}

function findAlbum(id) {
    return visibleAlbums().some((row) => row.album.id === id);
}

const actionQueue = [];
let actionPump = false;
let actionDepth = 0;
let actionButton = null;

function busyButton(node) {
    const button = node && node.closest ? node.closest("button") : null;
    if (!button) return null;
    const skip = ["link", "icon-btn", "art-pick", "art-download-btn", "art-zoom-btn", "art-swap-bar", "vposter-swap", "album-art-trigger", "artist-thumb", "art-delete", "upgrade-delete"];
    if (skip.some((name) => button.classList.contains(name))) return null;
    return button;
}

function markActionBusy(button, label) {
    if (!button || !button.isConnected || button.classList.contains("is-busy")) return;
    button._idleHtml = button.innerHTML;
    button._idleDisabled = button.disabled;
    button.disabled = true;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    const text = String(label || "Working").replace(/…\s*$/, "");
    button.innerHTML = `<span class="activity-spin" aria-hidden="true"></span><span>${escapeHtml(text)}</span>`;
}

function clearActionBusy(button) {
    if (!button) return;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    if (button._idleHtml != null) {
        button.innerHTML = button._idleHtml;
        button.disabled = !!button._idleDisabled;
        delete button._idleHtml;
        delete button._idleDisabled;
    }
}

function runAction(fn, label) {
    if (actionDepth > 0) {
        return Promise.resolve().then(fn).catch((error) => {
            notify((error && error.message) || "That action failed.", "error");
        });
    }
    const button = actionButton;
    actionButton = null;
    let resolve;
    const done = new Promise((finish) => { resolve = finish; });
    actionQueue.push({ fn, label: label || "Working…", resolve, button });
    if (actionPump && actionQueue.length > 1) {
        const current = actionQueue[0];
        state.activityLabel = `${current.label} · ${actionQueue.length - 1} queued`;
        syncActivity();
    }
    pumpActions();
    return done;
}

async function pumpActions() {
    if (actionPump) return;
    actionPump = true;
    while (actionQueue.length) {
        const job = actionQueue[0];
        const waiting = actionQueue.length - 1;
        state.busy = true;
        state.activityLabel = waiting ? `${job.label} · ${waiting} queued` : job.label;
        syncActivity();
        markActionBusy(job.button, job.label);
        actionDepth += 1;
        try {
            await job.fn();
        } catch (error) {
            notify((error && error.message) || "That action failed.", "error");
        } finally {
            actionDepth -= 1;
            clearActionBusy(job.button);
            actionQueue.shift();
            job.resolve();
            if (!actionQueue.length) {
                state.busy = false;
                state.activityLabel = "";
            }
            syncLibraryTools();
            if (state.center === "album" && state.album) renderAlbum();
        }
    }
    state.busy = false;
    state.activityLabel = "";
    actionPump = false;
    syncActivity();
    syncLibraryTools();
}

let noticeTimer = 0;
const alerts = [];
let unreadAlerts = 0;

function dismissToast() {
    const pop = document.getElementById("toast-pop");
    if (pop) pop.classList.add("hidden");
    clearTimeout(noticeTimer);
}

function notify(message, kind, extra) {
    const text = String(message || "").trim();
    if (!text) return;
    const item = {
        message: text,
        kind: kind || "info",
        time: new Date(),
        action: extra && extra.action ? extra.action : "",
        label: extra && extra.label ? extra.label : "",
        undo: extra && typeof extra.undo === "function" ? extra.undo : null,
        undone: false,
    };
    alerts.unshift(item);
    if (alerts.length > 40) alerts.length = 40;
    const pop = document.getElementById("toast-pop");
    if (pop) {
        pop.className = `toast-pop ${item.kind}`;
        pop.innerHTML = `<p>${escapeHtml(text)}</p>`;
        clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => {
            if (!pop.matches(":hover")) pop.classList.add("hidden");
        }, 12000);
    }
    const log = document.getElementById("toast-log");
    const selected = window.getSelection ? String(window.getSelection()) : "";
    // Leave the list alone while text in it is selected, so a new alert does not wipe the selection.
    if (log && !log.classList.contains("hidden") && !(selected && log.contains(window.getSelection().anchorNode))) renderAlertLog();
    renderAlertBell();
}

function renderAlertBell() {
    const badge = document.getElementById("alert-count");
    const bell = document.getElementById("alert-bell");
    if (!badge) return;
    const count = alerts.length;
    if (count > 0) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.classList.remove("hidden");
        if (bell) bell.setAttribute("aria-label", `Alerts, ${count}`);
    } else {
        badge.classList.add("hidden");
        if (bell) bell.setAttribute("aria-label", "Alerts");
    }
}

function renderAlertLog() {
    const list = document.getElementById("toast-log-list");
    if (!list) return;
    list.innerHTML = alerts.length
        ? alerts.map((item, index) => {
            const stamp = item.time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            const action = item.action
                ? `<button type="button" class="btn-ghost" data-action="${escapeHtml(item.action)}">${escapeHtml(item.label || "Open")}</button>`
                : "";
            const undo = item.undo
                ? (item.undone ? `<span class="muted">Undone</span>` : `<button type="button" class="btn-ghost" data-undo="${index}">Undo</button>`)
                : "";
            return `<div class="toast-row ${escapeHtml(item.kind)}"><div><p>${escapeHtml(item.message)}</p>${action}${undo}</div><span class="toast-time">${escapeHtml(stamp)}</span></div>`;
        }).join("")
        : `<p class="muted">No alerts yet.</p>`;
}

function toggleAlerts() {
    const log = document.getElementById("toast-log");
    if (!log) return;
    const opening = log.classList.contains("hidden");
    log.classList.toggle("hidden");
    if (opening) renderAlertLog();
}

function clearAlerts() {
    alerts.length = 0;
    unreadAlerts = 0;
    renderAlertBell();
    renderAlertLog();
}

function closeModals() {
    closeArtZoom();
    const artwork = document.getElementById("artwork-modal");
    const artworkWasOpen = artwork && !artwork.classList.contains("hidden") && !artwork.classList.contains("is-prompt");
    document.querySelectorAll(".modal").forEach((modal) => {
        if (!modal.classList.contains("is-prompt")) modal.classList.add("hidden");
    });
    if (artworkWasOpen) advanceArtworkQueue();
    const albumMenu = document.getElementById("album-menu");
    if (albumMenu) albumMenu.classList.add("hidden");
    const trackMenu = document.getElementById("track-menu");
    if (trackMenu) trackMenu.classList.add("hidden");
}

function formatDuration(seconds) {
    const total = Math.max(0, Math.round(seconds || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remain = total % 60;
    if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
    return `${minutes}:${String(remain).padStart(2, "0")}`;
}

function formatRate(rate) {
    if (!rate) return "—";
    const khz = rate / 1000;
    return `${Number.isInteger(khz) ? khz : khz.toFixed(1)} kHz`;
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function titleCase(value) {
    return String(value || "").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function assetLabel(key) {
    for (const [, items] of ASSET_GROUPS) {
        const found = items.find((item) => item[0] === key);
        if (found) return found[1].split(" — ")[0];
    }
    return key;
}

function assetHeading(key) {
    const label = assetLabel(key);
    const spec = ARTWORK_SPECS[key];
    if (!spec) return { text: label, title: label };
    return { text: `${label} · ${spec[0]}`, title: `${label}. ${spec[0]}, ${spec[1]}.` };
}

function sourceLabel(key) {
    return { "fanart.tv": "Fanart.tv", caa: "Cover Art Archive", lastfm: "Last.fm", deezer: "Deezer", theaudiodb: "TheAudioDB" }[key] || key;
}

// Undo buttons in the alert history: each alert may carry the function that reverses what it reports.
document.addEventListener("click", async (event) => {
    const button = event.target && event.target.closest ? event.target.closest("[data-undo]") : null;
    if (!button) return;
    const item = alerts[Number(button.dataset.undo)];
    if (!item || !item.undo || item.undone) return;
    item.undone = true;
    const undo = item.undo;
    renderAlertLog();
    try {
        await undo();
    } catch (error) {
        item.undone = false;
        notify((error && error.message) || "Could not undo that", "error");
        renderAlertLog();
    }
});
