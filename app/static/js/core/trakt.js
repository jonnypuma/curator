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
        : `<p class="scan-status">Not connected.</p>
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
