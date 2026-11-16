// Follow imports: each webhook item's path through the queue, the scan, the scrape, the file jobs and each player's
// library update, as a row of steps. The window refreshes itself while it is open.

state.journeys = { items: [], activeOnly: false, timer: 0 };

const JOURNEY_STEPS = {
    received: "Webhook",
    waiting: "Waiting",
    scan: "Scan",
    scrape: "Scrape",
    files: "File jobs",
    library: "Library update",
};
const JOURNEY_PLAYERS = { kodi: "Kodi", jellyfin: "Jellyfin", emby: "Emby", plex: "Plex", navidrome: "Navidrome" };
const JOURNEY_STATES = { waiting: "Waiting", running: "Running", done: "Done", failed: "Failed", skipped: "Skipped", pending: "Not yet" };

async function openJourneys() {
    document.getElementById("journeys-modal").classList.remove("hidden");
    await loadJourneys(true);
    clearInterval(state.journeys.timer);
    state.journeys.timer = setInterval(() => {
        if (document.getElementById("journeys-modal").classList.contains("hidden")) {
            clearInterval(state.journeys.timer);
            return;
        }
        loadJourneys().catch(() => {});
    }, 3000);
}

// The refresh sends the stamp of the list on screen; an unchanged list comes back as one line instead of 100 rows.
// Switching Active only clears the stamp, so the other list is always fetched.
async function loadJourneys(force) {
    const filter = state.journeys.activeOnly ? "true" : "false";
    if (force || state.journeys.stampFilter !== filter) state.journeys.stamp = "";
    const stamp = state.journeys.stamp ? `&stamp=${encodeURIComponent(state.journeys.stamp)}` : "";
    const data = await api(`/api/v1/journeys?active=${filter}&limit=100${stamp}`);
    state.journeys.stamp = data.stamp || "";
    state.journeys.stampFilter = filter;
    // Unchanged: redraw what is held anyway, so the time a running step has taken keeps counting.
    if (!data.unchanged) state.journeys.items = data.journeys || [];
    renderJourneys();
}

// The steps to draw: the ones recorded, in order, plus the ones this item has not reached yet. Music has no scrape or
// file jobs. Before any player job is queued the library step shows once, as Not yet. A webhook that could not be
// placed in the library ends after its first step.
function journeyManual(item) {
    return item.source === "curator" && item.event_type !== "Restore";
}

function journeySteps(item) {
    const recorded = item.stages || [];
    if (recorded.length === 1 && recorded[0].status === "failed") return recorded;
    // A library update started in Curator goes straight to the players.
    const plan = journeyManual(item) ? ["received"] : ["received", "waiting", "scan"];
    if (!journeyManual(item) && item.media !== "music") plan.push("scrape", "files");
    const steps = plan.map((name) => recorded.find((stage) => stage.stage === name) || { stage: name, status: "pending" });
    const players = recorded.filter((stage) => String(stage.stage).startsWith("library"));
    steps.push(...(players.length ? players : [{ stage: "library", status: "pending" }]));
    return steps;
}

function journeyStepLabel(name, item) {
    const [base, player] = String(name || "").split(":");
    if (player) return JOURNEY_PLAYERS[player] || player;
    if (base === "received" && item && item.source === "curator") return item.event_type === "Restore" ? "Restored" : "Requested";
    return JOURNEY_STEPS[base] || base;
}

function journeySpan(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function journeySeconds(stage) {
    if (!stage || !stage.started) return null;
    const start = Date.parse(stage.started);
    const end = stage.ended ? Date.parse(stage.ended) : Date.now();
    if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
    return Math.max(0, Math.round((end - start) / 1000));
}

function journeyTime(stage) {
    if (stage.status === "pending") return "";
    const seconds = journeySeconds(stage);
    return seconds === null ? "" : journeySpan(seconds);
}

// From the webhook to the end of the last step (or now, while on its way), and the same without the quiet-period wait.
function journeyTotals(item) {
    const stages = (item.stages || []).filter((stage) => stage.started);
    if (!stages.length) return null;
    const first = Math.min(...stages.map((stage) => Date.parse(stage.started)));
    const last = item.status === "active" ? Date.now() : Math.max(...stages.map((stage) => Date.parse(stage.ended || stage.started)));
    if (!Number.isFinite(first) || !Number.isFinite(last)) return null;
    const total = Math.max(0, Math.round((last - first) / 1000));
    const waited = journeySeconds(stages.find((stage) => stage.stage === "waiting")) || 0;
    return { total, working: Math.max(0, total - waited), waited };
}

function journeyCard(item) {
    const steps = journeySteps(item);
    const totals = journeyTotals(item);
    const focus = steps.find((step) => step.status === "failed")
        || steps.find((step) => step.status === "running")
        || steps.find((step) => step.status === "waiting");
    const icon = typeof providerIcon === "function" ? providerIcon(item.source) : escapeHtml(item.source || "");
    const when = String(item.created_at || "").replace("T", " ").slice(0, 16);
    const events = Number(item.events) > 1 ? ` · ${Number(item.events)} webhooks` : "";
    const finished = item.status === "done" || item.status === "failed";
    const chips = steps.map((step) => {
        // A finished import never reaches a step it did not need: that step is skipped, not still to come.
        const status = finished && (step.status || "pending") === "pending" ? "skipped" : (step.status || "pending");
        const time = journeyTime(step);
        const tip = [JOURNEY_STATES[status] || status, step.detail || ""].filter(Boolean).join(": ");
        return `<li class="jr-step is-${escapeHtml(status)}" title="${escapeHtml(tip)}">
            <span class="jr-dot" aria-hidden="true"></span>
            <span class="jr-name">${escapeHtml(journeyStepLabel(step.stage, item))}</span>
            <span class="jr-time">${escapeHtml(time || JOURNEY_STATES[status] || "")}</span>
        </li>`;
    }).join("");
    // A finished import says why a step was skipped (no player set up, nothing to scrape), so a grey dot is explained.
    const reason = focus || (finished ? steps.find((step) => step.status === "skipped" && step.detail) : null);
    const detail = reason && reason.detail
        ? `<p class="jr-detail is-${escapeHtml(reason.status)}">${escapeHtml(journeyStepLabel(reason.stage, item))}: ${escapeHtml(reason.detail)}</p>` : "";
    return `<div class="jr-card is-${escapeHtml(item.status || "active")}">
        <div class="jr-head">
            <span class="jr-source">${icon}</span>
            <strong class="jr-title">${escapeHtml(item.title || item.path || "Import")}</strong>
            <span class="jr-meta muted">${escapeHtml(item.event_type || "")} · ${escapeHtml(item.media || "")} · ${escapeHtml(when)}${events}</span>
            <span class="jr-status">
                <span class="jr-state is-${escapeHtml(item.status || "active")}">${item.status === "done" ? "Done" : item.status === "failed" ? "Failed" : "On its way"}</span>
                ${totals ? `<span class="jr-totals" title="From the webhook to the last step${totals.waited ? `, of which ${escapeHtml(journeySpan(totals.waited))} waiting for more webhooks` : ""}">${escapeHtml(journeySpan(totals.total))} in all${totals.waited ? ` · ${escapeHtml(journeySpan(totals.working))} without waiting` : ""}</span>` : ""}
            </span>
        </div>
        <ol class="jr-steps">${chips}</ol>
        ${detail}
        <p class="jr-path mono muted">${escapeHtml(item.path || "")}</p>
    </div>`;
}

function renderJourneys() {
    const list = document.getElementById("journeys-list");
    if (!list) return;
    const items = state.journeys.items;
    const active = items.filter((item) => item.status === "active").length;
    document.getElementById("journeys-count").textContent = items.length
        ? `${active} on the way · ${items.length - active} finished`
        : "";
    list.innerHTML = items.length
        ? items.map(journeyCard).join("")
        : `<p class="muted">${state.journeys.activeOnly ? "Nothing is on its way right now." : "No webhooks yet. Each Radarr, Sonarr or Lidarr import shows here from the moment it arrives."}</p>`;
}

async function clearJourneys() {
    const data = await api("/api/v1/journeys/clear", { method: "POST", body: {} });
    notify(`${Number(data.removed) || 0} finished import${Number(data.removed) === 1 ? "" : "s"} cleared.`, "success");
    await loadJourneys(true);
}

function onJourneyAction(name, action) {
    if (name === "journeys-open") return runAction(openJourneys);
    if (name === "journeys-refresh") return runAction(loadJourneys);
    if (name === "journeys-clear") return runAction(clearJourneys);
    if (name === "journeys-active") {
        state.journeys.activeOnly = Boolean(action.checked);
        return runAction(loadJourneys);
    }
    return false;
}
