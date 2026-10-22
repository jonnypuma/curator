const SETTINGS_TABS = ["general", "music", "movies", "sets", "tv", "files", "automation", "notifications", "integrations", "sync", "backup", "about"];

state.settingsTab = SETTINGS_TABS.includes(sessionStorage.getItem("curator.settingsTab"))
    ? sessionStorage.getItem("curator.settingsTab")
    : "general";

function bindSettingsTabs() {
    const nav = document.getElementById("settings-tabs");
    if (!nav) return;
    nav.addEventListener("click", (event) => {
        const tab = event.target.closest("[data-settings-tab]");
        if (!tab) return;
        state.settingsTab = tab.dataset.settingsTab;
        sessionStorage.setItem("curator.settingsTab", state.settingsTab);
        applySettingsTab();
    });
}

function applySettingsTab(options) {
    const active = SETTINGS_TABS.includes(state.settingsTab) ? state.settingsTab : "general";
    document.querySelectorAll("#settings-tabs [data-settings-tab]").forEach((tab) => {
        tab.setAttribute("aria-selected", tab.dataset.settingsTab === active ? "true" : "false");
    });
    document.querySelectorAll("#settings-body .settings-section").forEach((section) => {
        section.classList.toggle("hidden", (section.dataset.tab || "general") !== active);
    });
    const body = document.getElementById("settings-body");
    if (body && !(options && options.keepScroll)) body.scrollTop = 0;
    if (active === "automation" || active === "notifications" || active === "integrations") loadAutomationInfo();
    if (active === "integrations") loadTrakt();
    if (active === "sync") loadTrakt();
    if (active === "backup") loadBackupFiles();
    if (active === "files" && typeof loadSubCacheInfo === "function") loadSubCacheInfo();
    if (active === "files" && typeof schedulePatternExamples === "function") schedulePatternExamples();
}

function videoSettingsSections() {
    return `
        ${videoSettingsHtml()}
        ${automationSettingsHtml()}
        ${outboundSettingsHtml()}
        ${radarrSettingsHtml()}
        ${sonarrBazarrSettingsHtml()}
        ${playerSettingsHtml()}
        ${traktSection()}
        ${traktSyncSection()}
        ${playerCleanScheduleSection()}
        ${aboutSettingsSection()}`;
}

function aboutSettingsSection() {
    const brandVer = (document.querySelector(".brand-version") || {}).textContent || "";
    const version = brandVer.trim() || "v2.4.0";
    return `<section class="settings-section" data-tab="about">
        <h3>Curator Media Manager</h3>
        <div class="facts">
            <div><span>Version</span><strong>${escapeHtml(version)}</strong></div>
            <div><span>Release date</span><strong>2026-10-20</strong></div>
            <div><span>Libraries</span><strong>Movies, Movie Sets, TV Shows, Music</strong></div>
            <div><span>NFO dialects</span><strong>Kodi 22, Emby / Jellyfin, Plex</strong></div>
        </div>
        <p class="muted">Unified media curation, NFO management, multi-source metadata &amp; artwork scraping, subtitle synchronization, and player library automation.</p>
        <h3>Keyboard Shortcuts</h3>
        <p class="muted">Press <kbd>?</kbd> anywhere outside a text input, or click the button below to view the full keyboard shortcuts reference.</p>
        <p><button type="button" data-action="open-shortcuts">Keyboard Shortcuts Cheat Sheet</button></p>
    </section>`;
}

// Kodi exposes VideoLibrary.Clean / AudioLibrary.Clean, and Plex has Empty Trash on a
// section. Emby and Jellyfin only remove missing items as part of an ordinary library scan,
// so they get Update alone and a Clean choice falls back to Update.
const PLAYER_CLEAN_SUPPORT = { kodi: true, plex: true, emby: false, jellyfin: false };
const PLAYER_LABELS = { kodi: "Kodi", emby: "Emby", jellyfin: "Jellyfin", plex: "Plex" };

function playerKindOptions(player, selected) {
    const canClean = !!PLAYER_CLEAN_SUPPORT[player];
    const kinds = canClean ? [["update", "Update"], ["clean", "Clean"]] : [["update", "Update"]];
    const want = canClean ? (selected || "update") : "update";
    return kinds.map(([v, l]) => `<option value="${v}"${v === want ? " selected" : ""}>${l}</option>`).join("");
}

function syncPlayerCleanKinds() {
    const playerEl = document.getElementById("player-clean-player");
    const kindEl = document.getElementById("player-clean-kind");
    const note = document.getElementById("player-clean-kind-note");
    if (!playerEl || !kindEl) return;
    const player = playerEl.value || "kodi";
    const canClean = !!PLAYER_CLEAN_SUPPORT[player];
    kindEl.innerHTML = playerKindOptions(player, canClean ? kindEl.value : "update");
    kindEl.disabled = !canClean;
    if (note) {
        note.textContent = canClean
            ? ""
            : `${PLAYER_LABELS[player] || player} has no separate clean, so it removes missing items during an update.`;
    }
}

function playerCleanScheduleSection() {
    const presets = Array.isArray((state.settings || {}).schedule_presets) ? (state.settings || {}).schedule_presets : [];
    const groups = [];
    presets.forEach((preset) => {
        const name = preset.group || "Presets";
        let bucket = groups.find((item) => item.name === name);
        if (!bucket) {
            bucket = { name, items: [] };
            groups.push(bucket);
        }
        bucket.items.push(preset);
    });
    const presetOptions = groups.map((bucket) => {
        const options = bucket.items.map((p) =>
            `<option value="${escapeHtml(p.cron || p.value || p.id || "")}">${escapeHtml(p.name || p.label || p.id || "")}</option>`
        ).join("");
        return `<optgroup label="${escapeHtml(bucket.name)}">${options}</optgroup>`;
    }).join("");
    const players = [
        ["kodi", "Kodi"],
        ["emby", "Emby"],
        ["jellyfin", "Jellyfin"],
        ["plex", "Plex"],
    ];
    const mediaOptions = [["video", "Video library"], ["music", "Music library"]]
        .map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
    return `<section class="settings-section" data-tab="sync">
        <h3>Player schedules</h3>
        <p class="muted">Run a library update or clean on a schedule for a specific player. An update makes the player pick up new and changed items; a clean removes entries whose files are gone. Each player can hold as many schedules as you like, and each one runs independently.</p>
        <div class="schedule-grid">
            <label>Player <select id="player-clean-player" onchange="syncPlayerCleanKinds()">${players.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
            <label>Schedule type <select id="player-clean-kind">${playerKindOptions("kodi", "update")}</select></label>
            <label>Library <select id="player-clean-media">${mediaOptions}</select></label>
        </div>
        <p class="muted" id="player-clean-kind-note"></p>
        <div class="schedule-mode-tabs">
            <label class="choice"><input type="radio" name="player-clean-mode" value="preset" checked> Preset</label>
            <label class="choice"><input type="radio" name="player-clean-mode" value="daily"> Daily</label>
            <label class="choice"><input type="radio" name="player-clean-mode" value="weekly"> Weekly</label>
            <label class="choice"><input type="radio" name="player-clean-mode" value="custom"> Custom</label>
        </div>
        <div class="schedule-panel" data-player-clean-panel="preset">
            <label>Preset <select id="player-clean-preset">${presetOptions}</select></label>
        </div>
        <div class="schedule-panel hidden" data-player-clean-panel="daily">
            <label>Time <input id="player-clean-time-daily" type="time" value="04:00"></label>
        </div>
        <div class="schedule-panel hidden" data-player-clean-panel="weekly">
            <div class="schedule-grid">
                <label>Day <select id="player-clean-weekday">${["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"].map((d,i) => `<option value="${i}">${d}</option>`).join("")}</select></label>
                <label>Time <input id="player-clean-time-weekly" type="time" value="04:00"></label>
            </div>
        </div>
        <div class="schedule-panel hidden" data-player-clean-panel="custom">
            <label>Cron <input id="player-clean-cron" value="0 4 * * 0" placeholder="0 4 * * 0" spellcheck="false"></label>
        </div>
        <p><button type="button" data-action="save-player-clean-schedule">Save schedule</button></p>
        <div id="player-clean-schedules-saved"></div>
    </section>`;
}

function paintPlayerCleanSchedules() {
    const box = document.getElementById("player-clean-schedules-saved");
    if (!box) return;
    const list = Array.isArray((state.settings || {}).player_clean_schedules) ? state.settings.player_clean_schedules : [];
    if (!list.length) {
        box.innerHTML = `<p class="muted">No player schedules saved.</p>`;
        return;
    }
    box.innerHTML = list.map((item, index) => {
        const playerLabel = PLAYER_LABELS[item.player] || item.player;
        const mediaLabel = { video: "Video library", music: "Music library" }[item.media] || item.media;
        const kindLabel = item.kind === "clean" ? "Clean" : "Update";
        return `<article class="schedule-saved-item">
            <div class="schedule-preview-header">
                <span><strong>${escapeHtml(playerLabel)}</strong> — ${escapeHtml(kindLabel)} — ${escapeHtml(mediaLabel)} — <code>${escapeHtml(item.cron)}</code></span>
                <button type="button" class="btn-ghost btn-remove" data-action="remove-player-clean-schedule" data-index="${index}">Remove</button>
            </div>
        </article>`;
    }).join("");
}
