state.trakt = null;

function traktSection() {
    return `<section class="settings-section" data-tab="integrations">${integrationHeading("trakt", "Trakt")}
        <p class="muted">Trakt signs this app in with PKCE, so it has a client ID and no client secret. Press Connect, enter the code at <a href="https://trakt.tv/activate" target="_blank" rel="noopener">trakt.tv/activate</a>, and approve Curator. Curator then collects the token from Trakt, so your router does not need to let Trakt in.</p>
        <div id="trakt-box"><p class="muted">Loading…</p></div>
    </section>`;
}

function traktSyncSection() {
    return `<section class="settings-section" data-tab="sync">
        <h3>Trakt watched sync</h3>
        <p class="muted">Copies play counts and last-watched times between the library and your Trakt history. The higher play count and the later time win, so nothing is ever marked unwatched. Changed movies and episodes get their .nfo rewritten (playcount, lastplayed) unless they are locked, and Kodi is asked to rescan. Connect Trakt on the Integrations tab first.</p>
        <label class="field">Direction ${videoSelect("trakt-sync-mode", videoCfg().trakt_sync_mode || "both", [["both", "Both ways"], ["pull", "Trakt to Curator only"], ["push", "Curator to Trakt only"]])}</label>
        <label class="field">Sync every <input id="trakt-sync-hours" type="number" min="0" max="168" value="${Number(videoCfg().trakt_sync_hours) || 0}"> hours (0 = only when you press Sync now)</label>
        <p><button type="button" id="trakt-sync-now" data-action="trakt-sync">Sync now</button></p>
        <div id="trakt-sync-box"></div>
    </section>`;
}

function playerSyncSection() {
    const cfg = videoCfg();
    const chosen = new Set(cfg.watch_sync_players || []);
    const box = (name, label) => `<label class="choice"><input type="checkbox" data-watch-player="${name}" ${chosen.has(name) ? "checked" : ""}> ${label}</label>`;
    setTimeout(() => pollPlayerSync(), 0);   // fills the ready players and the last run once the section is on screen
    return `<section class="settings-section" data-tab="sync">
        <h3>Player watched sync</h3>
        <p class="muted">Copies play counts, last-played times and resume points between the library and Kodi, Jellyfin, Emby and Plex. Items are matched by file path through each player's path rows under Integrations. The higher play count and the later time win, so nothing is marked unwatched. A resume point one side lacks is copied over. Plex can only be marked watched (it has no play count to set) and given a resume point. Changed movies and episodes get their .nfo rewritten unless they are locked. Spreading unwatching needs the last sync to compare with: Curator remembers what both sides agreed on, and a count that fell on one side while the other stayed put is an unwatch. If both sides changed, the higher count still wins.</p>
        <div class="choice-row">${box("kodi", "Kodi")}${box("jellyfin", "Jellyfin")}${box("emby", "Emby")}${box("plex", "Plex")}</div>
        <label class="field">Direction ${videoSelect("watch-sync-mode", cfg.watch_sync_mode || "both", [["both", "Both ways"], ["pull", "Players to Curator only"], ["push", "Curator to players only"]])}</label>
        <label class="field">Sync every <input id="watch-sync-hours" type="number" min="0" max="168" value="${Number(cfg.watch_sync_hours) || 0}"> hours (0 = only when you press Sync now)</label>
        <label class="field">Jellyfin users <input id="watch-sync-user-jellyfin" type="text" value="${escapeHtml(cfg.watch_sync_user_jellyfin || "")}" placeholder="First administrator"></label>
        <label class="field">Emby users <input id="watch-sync-user-emby" type="text" value="${escapeHtml(cfg.watch_sync_user_emby || "")}" placeholder="First administrator"></label>
        <p class="muted">Name one user, several with a comma between, or * for everyone. Several users share one watched state, like a household: what one of them watched counts for all.</p>
        ${videoCheck("watch-sync-music", !!cfg.watch_sync_music, "Include music play counts (Kodi, Jellyfin, Emby and Plex; not Navidrome)")}
        ${videoCheck("watch-sync-unwatch", !!cfg.watch_sync_unwatch, "Spread unwatching: marking something unwatched in a player or in Curator reaches the other side (Kodi, Jellyfin, Emby and Plex)")}
        ${videoCheck("kodi-keep-watched", cfg.kodi_keep_watched !== false, "Put the watched state back after Curator refreshes an item in Kodi")}
        <p><button type="button" data-action="trakt-players-sync">Sync now</button> <button type="button" class="btn-ghost" data-action="trakt-players-test">Test players</button></p>
        <div id="player-test-box"></div>
        <div id="player-sync-box"></div>
    </section>`;
}

function collectionsSection() {
    const cfg = videoCfg();
    const chosen = new Set(cfg.collections_players || []);
    const box = (name, label) => `<label class="choice"><input type="checkbox" data-collection-player="${name}" ${chosen.has(name) ? "checked" : ""}> ${label}</label>`;
    return `<section class="settings-section" data-tab="sync">
        <h3>Collections in Jellyfin, Emby and Plex</h3>
        <p class="muted">Kodi reads movie sets from the .nfo files. These players get collections pushed: each movie set with two or more movies, and each saved movie or TV filter that has a tag (the tag is the collection name). Items are matched by file path through each player's path rows. Curator keeps the members of the collections it made, or took over by name, in step with the library; other collections are left alone.</p>
        <div class="choice-row">${box("jellyfin", "Jellyfin")}${box("emby", "Emby")}${box("plex", "Plex")}</div>
        ${videoCheck("collections-sets", cfg.collections_sets !== false, "Movie sets")}
        ${videoCheck("collections-tags", cfg.collections_tags !== false, "Saved filters with a tag")}
        ${videoCheck("collections-after-scan", !!cfg.collections_after_scan, "Push after every movie or TV scan")}
        <p><button type="button" data-action="trakt-collections-push">Push now</button></p>
        <div id="collections-box"></div>
    </section>`;
}

async function pushCollections() {
    state.collectionsPush = await api("/api/v1/trakt/collections", { method: "POST", body: {} });
    pollCollections();
}

async function pollCollections() {
    clearTimeout(state.collectionsTimer);
    const data = await api("/api/v1/trakt/collections");
    const host = document.getElementById("collections-box");
    if (host) host.innerHTML = `<p class="muted">${escapeHtml(data.message || "")}</p>${data.log ? `<pre class="log-box">${escapeHtml(data.log)}</pre>` : ""}`;
    if (data.status === "running") state.collectionsTimer = setTimeout(() => pollCollections().catch(() => {}), 1500);
    else if (data.status !== "idle") notify(data.message || "Collections pushed.", data.status === "failed" ? "error" : "info");
}

async function testPlayers() {
    const host = document.getElementById("player-test-box");
    if (host) host.innerHTML = `<p class="muted">Reading each player…</p>`;
    const data = await api("/api/v1/trakt/players/test");
    if (host) host.innerHTML = connectionLines(data.results, "player");
}

// One line per app from a connection test: worked, failed, or not set up.
function connectionLines(results, nameKey) {
    return (results || []).map((row) => {
        const tone = row.ok === true ? "is-done" : row.ok === false ? "is-failed" : "";
        return `<p class="scan-status ${tone}">${row.ok === true ? "✓ " : row.ok === false ? "✕ " : ""}${escapeHtml(nameKey === "app" ? `${row.app}: ` : "")}${escapeHtml(row.message || "")}</p>`;
    }).join("");
}

async function startPlayerSync() {
    const mode = (document.getElementById("watch-sync-mode") || {}).value || "both";
    state.playerSync = await api("/api/v1/trakt/players/sync", { method: "POST", body: { mode } });
    state.playerSyncWasRunning = true;
    paintPlayerSync();
    pollPlayerSync();
}

async function pollPlayerSync() {
    clearTimeout(state.playerSyncTimer);
    try {
        state.playerSync = await api("/api/v1/trakt/players/sync");
    } catch (error) {
        return;
    }
    paintPlayerSync();
    if (state.playerSync.status === "running") {
        state.playerSyncTimer = setTimeout(pollPlayerSync, 1500);
    } else if (state.playerSyncWasRunning) {
        state.playerSyncWasRunning = false;
        notify(state.playerSync.message || "Player sync finished.", state.playerSync.status === "failed" ? "error" : "info");
    }
}

function paintPlayerSync() {
    const host = document.getElementById("player-sync-box");
    const data = state.playerSync;
    if (!host || !data) return;
    const ready = (data.ready || []).join(", ") || "none";
    host.innerHTML = `<p class="muted">Ready players: ${escapeHtml(ready)}. ${escapeHtml(data.message || "")}</p>${data.log ? `<pre class="log-box">${escapeHtml(data.log)}</pre>` : ""}`;
}

async function startTraktSync() {
    const mode = (document.getElementById("trakt-sync-mode") || {}).value || "both";
    state.traktSync = await api("/api/v1/trakt/sync", { method: "POST", body: { mode } });
    paintTraktSync();
    pollTraktSync();
}

async function pollTraktSync() {
    clearTimeout(state.traktSyncTimer);
    try {
        state.traktSync = await api("/api/v1/trakt/sync");
    } catch (error) {
        return;
    }
    paintTraktSync();
    if (state.traktSync.status === "running") {
        state.traktSyncTimer = setTimeout(pollTraktSync, 1500);
    } else if (state.traktSyncWasRunning) {
        notify(state.traktSync.message || "Trakt sync finished.", state.traktSync.status === "failed" ? "error" : "info");
        loadTrakt();
    }
    state.traktSyncWasRunning = state.traktSync.status === "running";
}

function paintTraktSync() {
    const box = document.getElementById("trakt-sync-box");
    if (!box) return;
    const job = state.traktSync || {};
    const running = job.status === "running";
    const button = document.getElementById("trakt-sync-now");
    if (button) button.disabled = running || !(state.trakt || {}).connected;
    const tones = { running: "is-running", done: "is-done", failed: "is-failed" };
    box.innerHTML = job.status && job.status !== "idle"
        ? `<p class="scan-status ${tones[job.status] || ""}">${escapeHtml(job.message || job.status)}</p>${job.log ? `<pre class="console">${escapeHtml(job.log)}</pre>` : ""}`
        : "";
}

async function loadTrakt() {
    try {
        state.trakt = await api("/api/v1/trakt/status");
    } catch (error) {
        state.trakt = { error: error.message };
    }
    paintTrakt();
}

function paintTrakt() {
    const box = document.getElementById("trakt-box");
    if (!box) return;
    const data = state.trakt || {};
    if (data.error) {
        box.innerHTML = `<p class="muted">${escapeHtml(data.error)}</p>`;
        return;
    }
    if (!document.getElementById("trakt-code-slot") || !document.getElementById("trakt-rest")) {
        box.innerHTML = `<div id="trakt-code-slot"></div><div id="trakt-rest"></div>`;
    }
    const source = data.client_source === "environment" ? "From TRAKT_CLIENT_ID in docker-compose. Save a value here to replace it." : "";
    const connected = data.connected
        ? `<p class="scan-status is-done">Connected${data.username ? ` as ${escapeHtml(data.username)}` : ""}.</p>
           <p class="trakt-actions">
               <button type="button" class="btn-ghost" data-action="trakt-disconnect">Disconnect</button>
           </p>
           <p class="muted">${data.last_sync ? `Last watched sync: ${escapeHtml(new Date(data.last_sync * 1000).toLocaleString())}.` : "Watched state has not been synced yet."}</p>`
        : `<p class="scan-status${data.needs_reconnect ? " is-error" : ""}">${data.needs_reconnect ? "Trakt sign-in expired. Connect again to resume syncing." : "Not connected."}</p>
           <p class="trakt-actions">
               <button type="button" data-action="trakt-connect" ${data.client_id ? "" : "disabled"}>Connect with Trakt</button>
           </p>`;
    document.getElementById("trakt-rest").innerHTML = `
        <label>Client ID <input type="text" id="trakt-client-id" class="mono" autocomplete="off" spellcheck="false" value="${escapeHtml(data.client_id || "")}"></label>
        ${source ? `<p class="muted">${escapeHtml(source)}</p>` : ""}
        <p><button type="button" class="btn-ghost" data-action="trakt-save-client">Save Trakt app</button></p>
        ${connected}`;
    syncTraktCode(data);
    paintTraktSync();
    if (data.connected) pollTraktSync();
}


function clipboardIcon() {
    return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="3" width="8" height="4" rx="1"></rect><path d="M8 5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path></svg>`;
}

function currentTraktCode(data) {
    if (state.traktCode) return state.traktCode;
    if (state.traktDevice && state.traktDevice.user_code) return state.traktDevice.user_code;
    if (data && data.user_code && data.device_status === "waiting") return data.user_code;
    return "";
}

function syncTraktCode(data) {
    const slot = document.getElementById("trakt-code-slot");
    if (!slot) return;
    const code = currentTraktCode(data || state.trakt);
    const message = (state.traktDevice && state.traktDevice.message) || (data && data.device_message) || "Enter this code on the Trakt page.";
    if (!code) {
        if (slot.dataset.code) {
            slot.innerHTML = "";
            delete slot.dataset.code;
        }
        return;
    }
    if (slot.dataset.code !== code) {
        slot.dataset.code = code;
        slot.innerHTML = `<div class="trakt-code-block">
            <div class="trakt-code-line">
                <input id="trakt-code-value" class="mono trakt-code" readonly spellcheck="false" value="${escapeHtml(code)}" aria-label="Trakt code">
                <button type="button" class="icon-btn" data-action="trakt-copy-code" title="Copy code" aria-label="Copy code">${clipboardIcon()}</button>
            </div>
            <p id="trakt-device-status">${escapeHtml(message)}</p>
            <p><button type="button" class="btn-ghost" data-action="trakt-device-cancel">Cancel</button></p>
        </div>`;
        return;
    }
    const status = document.getElementById("trakt-device-status");
    if (status) status.textContent = message;
}

async function saveTraktClient() {
    const input = document.getElementById("trakt-client-id");
    const data = await api("/api/v1/trakt/client", {
        method: "PUT",
        body: { client_id: input ? input.value.trim() : "" },
    });
    state.trakt = data;
    paintTrakt();
    notify(data.client_id ? "Trakt app saved." : "Trakt app removed.", "info");
}

async function connectTrakt(action, tab) {
    let data;
    try {
        data = await api("/api/v1/trakt/device", { method: "POST", body: {} });
    } catch (error) {
        if (tab && !tab.closed) tab.close();
        throw error;
    }
    if (!data.user_code) {
        if (tab && !tab.closed) tab.close();
        throw new Error("Trakt did not send a code to show.");
    }
    state.traktCode = data.user_code;
    state.traktDevice = data;
    paintTrakt();
    notify(`Trakt code: ${data.user_code}`, "info");
    const page = data.verification_url || "https://trakt.tv/activate";
    if (tab && !tab.closed) tab.location.href = page;
    else window.open(page, "_blank", "noopener");
    pollTraktDevice();
}

async function pollTraktDevice() {
    clearTimeout(state.traktDeviceTimer);
    let data;
    try {
        data = await api("/api/v1/trakt/device");
    } catch (error) {
        notify(error.message || "Trakt sign-in failed.", "error");
        return;
    }
    if (data.user_code) state.traktCode = data.user_code;
    if (data.status === "connected" || data.status === "expired" || data.status === "denied") {
        state.traktCode = "";
        state.traktDevice = null;
        if (data.status === "connected") notify("Trakt is connected.", "info");
        else notify(data.message || "Trakt sign-in stopped.", "warning");
        loadTrakt();
        return;
    }
    state.traktDevice = data.status ? data : state.traktDevice;
    syncTraktCode(state.trakt);
    if (state.traktCode) {
        state.traktDeviceTimer = setTimeout(pollTraktDevice, Math.max(5, Number(data.interval) || 5) * 1000);
    }
}

function copyTraktPlainText(text) {
    const field = document.getElementById("trakt-code-value");
    if (field) {
        field.focus();
        field.select();
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    let copied = false;
    try {
        copied = document.execCommand("copy");
    } catch (error) {
        copied = false;
    }
    area.remove();
    if (field) field.focus();
    return copied;
}

async function copyTraktCode(code) {
    const text = String(code || state.traktCode || (state.traktDevice && state.traktDevice.user_code) || "");
    if (!text) return;
    const copied = copyTraktPlainText(text);
    if (!copied && navigator.clipboard) {
        try {
            await navigator.clipboard.writeText(text);
            notify("Trakt code copied.", "info");
            return;
        } catch (error) {
            notify(`Trakt code: ${text}`, "info");
            return;
        }
    }
    notify(copied ? "Trakt code copied." : `Trakt code: ${text}`, "info");
}

async function cancelTraktDevice() {
    clearTimeout(state.traktDeviceTimer);
    state.traktCode = "";
    state.traktDevice = null;
    await api("/api/v1/trakt/device", { method: "DELETE" });
    paintTrakt();
}

async function disconnectTrakt() {
    state.trakt = await api("/api/v1/trakt/disconnect", { method: "POST", body: {} });
    paintTrakt();
    notify("Disconnected from Trakt.", "info");
}

function noteTraktReturn() {
    const params = new URLSearchParams(location.search);
    const result = params.get("trakt");
    if (!result) return;
    params.delete("trakt");
    const query = params.toString();
    history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
    if (result === "connected") notify("Trakt is connected.", "info");
    else if (result === "denied") notify("Trakt sign-in was cancelled.", "warning");
    else notify("Trakt sign-in failed. Check the client ID and the redirect URI of your Trakt app, then try again.", "error");
    if (result === "connected") loadTrakt();
    if (window.opener && window.opener !== window && !window.opener.closed) {
        window.opener.postMessage({ type: "trakt-return", result }, location.origin);
    }
}

window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || !event.data || event.data.type !== "trakt-return") return;
    const result = event.data.result;
    if (result === "connected") {
        notify("Trakt is connected.", "info");
        loadTrakt();
    } else if (result === "denied") notify("Trakt sign-in was cancelled.", "warning");
    else notify("Trakt sign-in failed. Check the client ID and the redirect URI of your Trakt app, then try again.", "error");
});
