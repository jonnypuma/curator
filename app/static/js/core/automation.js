const ARR_SOURCES = [["any", "Any app"], ["radarr", "Radarr"], ["sonarr", "Sonarr"], ["bazarr", "Bazarr"], ["lidarr", "Lidarr"]];
const QUEUE_RING = 2 * Math.PI * 52;

state.automationInfo = null;
state.queuePanel = { items: [], events: [], scans: [], arr: [], library: [], tab: "webhook", timer: 0, clock: 0, fetchedAt: 0 };

function autoCfg() {
    return ((state.settings || {}).automation) || {};
}

function notifyCfg() {
    return ((state.settings || {}).notify) || {};
}

function mappingRow(row) {
    const item = row || {};
    return `<div class="auto-row" data-auto-map>
        <select data-map-source aria-label="App">${ARR_SOURCES.map(([key, label]) => `<option value="${key}" ${key === (item.source || "any") ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select>
        <input data-map-remote value="${escapeHtml(item.remote || "")}" placeholder="Path in the app, e.g. /data/media/movies" spellcheck="false" aria-label="Remote path">
        <span aria-hidden="true">→</span>
        <span class="path-field"><input data-map-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator, e.g. /movies" spellcheck="false" aria-label="Local path"><button type="button" class="btn-ghost" data-action="browse-map-local">Browse</button></span>
        <button type="button" class="btn-ghost btn-remove" data-action="auto-row-remove">Remove</button>
    </div>`;
}

function playerPathRow(service, row) {
    const item = row || {};
    const label = service.charAt(0).toUpperCase() + service.slice(1);
    return `<div class="auto-row" data-player-path="${service}">
        <input data-player-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator, e.g. /movies" spellcheck="false" aria-label="Curator path">
        <span aria-hidden="true">→</span>
        <input data-player-remote value="${escapeHtml(item.remote || "")}" placeholder="Path in ${escapeHtml(label)}, e.g. /data/movies" spellcheck="false" aria-label="${escapeHtml(label)} path">
        <button type="button" class="btn-ghost btn-remove" data-action="auto-row-remove">Remove</button>
    </div>`;
}

function playerPathFields(service, rows) {
    const label = service.charAt(0).toUpperCase() + service.slice(1);
    const lines = (rows || []).map((row) => playerPathRow(service, row)).join("");
    return `<h3>${escapeHtml(label)} paths</h3>
        <p class="muted">No path rows means a full library scan. Emby and Jellyfin refresh the whole server once. Plex scans the media type that changed. Path rows scan only the changed folders, using the path this server shows. The webhook queue hands the folders over and does not wait. This player's job is removed when this server reports the scan finished. A stuck scan on another player does not hold this one.</p>
        <div id="notify-${service}-paths" class="auto-rows player-paths">
            <div class="kodi-path-head" aria-hidden="true"><span>Curator path</span><span></span><span>${escapeHtml(label)} path</span><span></span></div>
            ${lines}
        </div>
        <p><button type="button" class="btn-ghost" data-action="auto-add-player-path" data-player="${service}">Add ${escapeHtml(label)} path</button></p>`;
}

function kodiPathRow(row) {
    const item = row || {};
    return `<div class="auto-row" data-kodi-path>
        <input data-kodi-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator, e.g. /movies" spellcheck="false" aria-label="Curator path">
        <span aria-hidden="true">→</span>
        <input data-kodi-remote value="${escapeHtml(item.kodi || "")}" placeholder="Path in Kodi, e.g. smb://nas/movies" spellcheck="false" aria-label="Kodi path">
        <button type="button" class="btn-ghost btn-remove" data-action="auto-row-remove">Remove</button>
    </div>`;
}

function autoField(id, label, value, placeholder, type) {
    const kind = type || "text";
    const extra = kind === "number" ? ` min="0" max="86400"` : ` spellcheck="false"`;
    return `<label class="field">${escapeHtml(label)} <input id="${id}" type="${kind}"${extra} value="${escapeHtml(value === undefined || value === null ? "" : String(value))}" placeholder="${escapeHtml(placeholder || "")}"></label>`;
}

function arrWebhookLine() {
    const origin = `${location.protocol}//${location.host}`;
    return `<p>Webhook address: <span class="mono">${escapeHtml(origin)}/api/v1/webhooks/arr?apikey=YOUR_KEY</span></p>
        <p class="muted">Radarr, Sonarr and Lidarr paste this address into a Webhook connection. Bazarr has no webhook; its Apprise address is on the Bazarr section. Replace YOUR_KEY with CMM_API_KEY.</p>`;
}

function arrSwitches(name, scanLabel) {
    const cfg = state.settings || {};
    const key = `${name}_enabled`;
    const on = Object.prototype.hasOwnProperty.call(cfg, key) ? cfg[key] !== false : name !== "lidarr";
    const scan = cfg[`${name}_import_scan`] !== false;
    return `${videoCheck(`${name}-enabled`, on, `Enable ${name.charAt(0).toUpperCase()}${name.slice(1)}`)}
        ${videoCheck(`${name}-import-scan`, scan, scanLabel)}`;
}

function integrationOn(source) {
    const cfg = state.settings || {};
    const key = `${source}_enabled`;
    if (!Object.prototype.hasOwnProperty.call(cfg, key)) return source !== "lidarr";
    return cfg[key] !== false;
}

function arrSearchBlocked(source) {
    if (integrationOn(source)) return false;
    const label = { lidarr: "Lidarr", radarr: "Radarr", sonarr: "Sonarr" }[source] || source;
    notify(`${label} is turned off under Settings, Integrations.`, "info");
    return true;
}

function arrTest(action) {
    return `<div class="arr-test"><button type="button" class="btn-ghost" data-action="${action}">Test connection</button>
        <p class="muted" data-arr-test></p></div>`;
}

function isPlaceholderProfile(name) {
    const text = String(name || "").trim();
    return /^Profile \d+$/.test(text) || /first (quality|metadata) profile/i.test(text);
}

function savedProfileOptions(list, id, name) {
    const rows = (Array.isArray(list) ? list : []).filter((item) => item && item.id && item.name && !isPlaceholderProfile(item.name));
    if (Number(id) && !rows.some((item) => Number(item.id) === Number(id))) {
        rows.push({ id, name: name && !isPlaceholderProfile(name) ? name : `Profile ${id}` });
    }
    return rows;
}

function chosenProfiles(id) {
    const select = document.getElementById(id);
    if (!select) return { id: 0, name: "", list: [] };
    const list = [...select.options].map((option) => ({ id: Number(option.value) || 0, name: option.textContent.trim() }))
        .filter((item) => item.id && item.name && !isPlaceholderProfile(item.name));
    const current = Number(select.value) || 0;
    const picked = list.find((item) => item.id === current);
    return { id: current, name: picked ? picked.name : "", list };
}

function radarrSettingsHtml() {
    const cfg = state.settings || {};
    const r = cfg.radarr || {};
    const roots = r.root_folder ? [r.root_folder] : [];
    const profiles = savedProfileOptions(r.quality_profiles, r.quality_profile, r.quality_profile_name);
    return `<section class="settings-section" data-tab="integrations">${integrationHeading("radarr", "Radarr")}
            <p class="muted">Used by Search in Radarr on the Movie sets tab: a missing movie is added to Radarr (monitored) and searched, and a movie Radarr already has is searched again. RADARR_URL and RADARR_API_KEY in docker-compose are used when these fields are empty.</p>
            ${arrSwitches("radarr", "Scan a movie when Radarr reports it imported")}
            ${arrWebhookLine()}
            ${autoField("radarr-url", "Radarr address", cfg.radarr_url, "http://radarr:7878")}
            ${videoKeyField("radarr_api_key", "radarr-api-key", "Radarr API key", "RADARR_API_KEY", "")}
            ${arrTest("auto-radarr-test")}
            <p><button type="button" class="btn-ghost" data-action="auto-radarr-load">Load folders and profiles</button></p>
            <label class="field">Root folder <select id="radarr-root">
                <option value="">Radarr's first root folder</option>
                ${roots.map((path) => `<option value="${escapeHtml(path)}" selected>${escapeHtml(path)}</option>`).join("")}
            </select></label>
            <label class="field">Quality profile <select id="radarr-profile">
                <option value="0">Radarr's first quality profile</option>
                ${profiles.map((item) => `<option value="${item.id}" ${Number(item.id) === Number(r.quality_profile) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
            </select></label>
            <label class="field">Minimum availability ${videoSelect("radarr-availability", r.minimum_availability || "released", [["announced", "Announced"], ["inCinemas", "In cinemas"], ["released", "Released"]])}</label>
            ${videoCheck("radarr-search", r.search !== false, "Start a search right away")}
        </section>`;
}

function sonarrBazarrSettingsHtml() {
    const cfg = state.settings || {};
    const s = cfg.sonarr || {};
    const roots = s.root_folder ? [s.root_folder] : [];
    const profiles = savedProfileOptions(s.quality_profiles, s.quality_profile, s.quality_profile_name);
    const monitors = [
        ["all", "All episodes"],
        ["future", "Future episodes"],
        ["missing", "Missing episodes"],
        ["existing", "Existing episodes"],
        ["firstSeason", "First season"],
        ["latestSeason", "Latest season"],
        ["pilot", "Pilot"],
        ["none", "None"],
    ];
    return `<section class="settings-section" data-tab="integrations">${integrationHeading("sonarr", "Sonarr")}
            <p class="muted">Used by Search missing episodes on a show or a season. A show Sonarr already has is searched again. A show it does not have is added with the folder and profile below, then searched. SONARR_URL and SONARR_API_KEY in docker-compose are used when these fields are empty.</p>
            ${arrSwitches("sonarr", "Scan a show when Sonarr reports an episode imported")}
            ${arrWebhookLine()}
            ${autoField("sonarr-url", "Sonarr address", cfg.sonarr_url, "http://sonarr:8989")}
            ${videoKeyField("sonarr_api_key", "sonarr-api-key", "Sonarr API key", "SONARR_API_KEY", "")}
            ${arrTest("auto-sonarr-test")}
            <p><button type="button" class="btn-ghost" data-action="auto-sonarr-load">Load folders and profiles</button></p>
            <label class="field">Root folder <select id="sonarr-root">
                <option value="">Sonarr's first root folder</option>
                ${roots.map((path) => `<option value="${escapeHtml(path)}" selected>${escapeHtml(path)}</option>`).join("")}
            </select></label>
            <label class="field">Quality profile <select id="sonarr-profile">
                <option value="0">Sonarr's first quality profile</option>
                ${profiles.map((item) => `<option value="${item.id}" ${Number(item.id) === Number(s.quality_profile) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
            </select></label>
            <label class="field">Monitor ${videoSelect("sonarr-monitor", s.monitor || "all", monitors)}</label>
            ${videoCheck("sonarr-search", s.search !== false, "Start a search right away")}
        </section>
        <section class="settings-section" data-tab="integrations">${integrationHeading("bazarr", "Bazarr")}
            <p class="muted">Used by Search missing subtitles on a movie, a show, or an episode. Bazarr searches the subtitles it already lists as missing. It only knows titles that Radarr or Sonarr have, and Curator does not add any. BAZARR_URL and BAZARR_API_KEY in docker-compose are used when these fields are empty.</p>
            <p>Apprise address: <span class="mono">${location.protocol === "https:" ? "jsons" : "json"}://${escapeHtml(location.host)}/api/v1/webhooks/arr?apikey=YOUR_KEY</span></p>
            <p class="muted">Bazarr does not send webhooks. In Bazarr open Settings, Notifications, and add that Apprise URL. Use jsons:// when Curator is served over HTTPS. Replace YOUR_KEY with CMM_API_KEY. Curator matches the movie or show from the title in the message.</p>
            ${arrSwitches("bazarr", "Scan the folder when Bazarr reports a subtitle imported")}
            ${autoField("bazarr-url", "Bazarr address", cfg.bazarr_url, "http://bazarr:6767")}
            ${videoKeyField("bazarr_api_key", "bazarr-api-key", "Bazarr API key", "BAZARR_API_KEY", "")}
            ${arrTest("auto-bazarr-test")}
        </section>`;
}

function readArrSwitch(name) {
    const enabled = document.getElementById(`${name}-enabled`);
    const scan = document.getElementById(`${name}-import-scan`);
    if (enabled) state.settings[`${name}_enabled`] = enabled.checked;
    if (scan) state.settings[`${name}_import_scan`] = scan.checked;
}

function readSonarrBazarrSettings() {
    const sonarr = document.getElementById("sonarr-url");
    const bazarr = document.getElementById("bazarr-url");
    if (sonarr) state.settings.sonarr_url = sonarr.value.trim();
    if (bazarr) state.settings.bazarr_url = bazarr.value.trim();
    readArrSwitch("sonarr");
    readArrSwitch("bazarr");
    const root = document.getElementById("sonarr-root");
    if (root) {
        const profiles = chosenProfiles("sonarr-profile");
        const previous = state.settings.sonarr || {};
        state.settings.sonarr = {
            root_folder: root.value,
            quality_profile: profiles.id,
            quality_profile_name: profiles.name || previous.quality_profile_name || "",
            quality_profiles: profiles.list.length ? profiles.list : (previous.quality_profiles || []),
            monitor: document.getElementById("sonarr-monitor").value,
            search: document.getElementById("sonarr-search").checked,
        };
    }
}

function readRadarrSettings() {
    if (!document.getElementById("radarr-url")) return;
    readArrSwitch("radarr");
    state.settings.radarr_url = document.getElementById("radarr-url").value.trim();
    const profiles = chosenProfiles("radarr-profile");
    const previous = state.settings.radarr || {};
    state.settings.radarr = {
        root_folder: document.getElementById("radarr-root").value,
        quality_profile: profiles.id,
        quality_profile_name: profiles.name || previous.quality_profile_name || "",
        quality_profiles: profiles.list.length ? profiles.list : (previous.quality_profiles || []),
        minimum_availability: document.getElementById("radarr-availability").value,
        search: document.getElementById("radarr-search").checked,
    };
}

function radarrConnection() {
    return {
        url: (document.getElementById("radarr-url") || {}).value || "",
        key: (document.getElementById("radarr-api-key") || {}).value || "",
    };
}

async function loadRadarrOptions(quiet) {
    const data = await api("/api/v1/radarr/options", { method: "POST", body: radarrConnection() });
    const root = document.getElementById("radarr-root");
    const profile = document.getElementById("radarr-profile");
    if (!root || !profile) return data;
    const keepRoot = root.value;
    const keepProfile = profile.value;
    root.innerHTML = `<option value="">Radarr's first root folder</option>${(data.root_folders || []).map((item) =>
        `<option value="${escapeHtml(item.path)}" ${item.path === keepRoot ? "selected" : ""}>${escapeHtml(item.path)}</option>`).join("")}`;
    profile.innerHTML = `<option value="0">Radarr's first quality profile</option>${(data.quality_profiles || []).map((item) =>
        `<option value="${item.id}" ${String(item.id) === keepProfile ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}`;
    state.settings.radarr = { ...(state.settings.radarr || {}), quality_profiles: data.quality_profiles || [] };
    if (!quiet) notify(`Radarr has ${(data.root_folders || []).length} root folders and ${(data.quality_profiles || []).length} quality profiles.`, "success");
    return data;
}

function sonarrConnection() {
    return {
        url: (document.getElementById("sonarr-url") || {}).value || "",
        key: (document.getElementById("sonarr-api-key") || {}).value || "",
    };
}

async function loadSonarrOptions(quiet) {
    const data = await api("/api/v1/sonarr/options", { method: "POST", body: sonarrConnection() });
    const root = document.getElementById("sonarr-root");
    const profile = document.getElementById("sonarr-profile");
    if (!root || !profile) return data;
    const keepRoot = root.value;
    const keepProfile = profile.value;
    root.innerHTML = `<option value="">Sonarr's first root folder</option>${(data.root_folders || []).map((item) =>
        `<option value="${escapeHtml(item.path)}" ${item.path === keepRoot ? "selected" : ""}>${escapeHtml(item.path)}</option>`).join("")}`;
    profile.innerHTML = `<option value="0">Sonarr's first quality profile</option>${(data.quality_profiles || []).map((item) =>
        `<option value="${item.id}" ${String(item.id) === keepProfile ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}`;
    state.settings.sonarr = { ...(state.settings.sonarr || {}), quality_profiles: data.quality_profiles || [] };
    if (!quiet) notify(`Sonarr has ${(data.root_folders || []).length} root folders and ${(data.quality_profiles || []).length} quality profiles.`, "success");
    return data;
}

function lidarrConnection() {
    return {
        url: (document.getElementById("lidarr-api-url") || {}).value || "",
        key: (document.getElementById("lidarr-api-key") || {}).value || "",
    };
}

function fillLidarrSelect(id, blank, rows, selected) {
    const select = document.getElementById(id);
    const keep = selected || select.value;
    select.innerHTML = blank + rows.map((item) =>
        `<option value="${escapeHtml(item.value)}" ${String(item.value) === String(keep) ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("");
}

async function loadLidarrOptions(quiet) {
    const data = await api("/api/v1/lidarr/options", { method: "POST", body: lidarrConnection() });
    if (!document.getElementById("lidarr-profile")) return data;
    fillLidarrSelect("lidarr-root", `<option value="">Lidarr's first root folder</option>`,
        (data.root_folders || []).map((item) => ({ value: item.path, label: item.path })));
    fillLidarrSelect("lidarr-profile", `<option value="0">Lidarr's first quality profile</option>`,
        (data.quality_profiles || []).map((item) => ({ value: item.id, label: item.name })));
    fillLidarrSelect("lidarr-metadata", `<option value="0">Lidarr's first metadata profile</option>`,
        (data.metadata_profiles || []).map((item) => ({ value: item.id, label: item.name })));
    state.settings.lidarr = {
        ...(state.settings.lidarr || {}),
        quality_profiles: data.quality_profiles || [],
        metadata_profiles: data.metadata_profiles || [],
    };
    if (!quiet) notify(`Lidarr has ${(data.root_folders || []).length} root folders, ${(data.quality_profiles || []).length} quality profiles and ${(data.metadata_profiles || []).length} metadata profiles.`, "success");
    return data;
}

function refreshSavedArrOptions() {
    const jobs = [];
    if (document.getElementById("radarr-profile")) jobs.push(loadRadarrOptions(true));
    if (document.getElementById("sonarr-profile")) jobs.push(loadSonarrOptions(true));
    if (document.getElementById("lidarr-profile")) jobs.push(loadLidarrOptions(true));
    Promise.all(jobs.map((job) => Promise.resolve(job).catch(() => null)));
}

function autoTest(target, label) {
    return `<button type="button" class="btn-ghost" data-action="auto-test" data-target="${target}">${escapeHtml(label || "Test connection")}</button>`;
}

function noticeChecks(prefix, cfg) {
    return [
        ["video", "New or replaced video"],
        ["removed", "Removed video"],
        ["music", "Music files changed"],
        ["failed", "A player update failed"],
    ].map(([kind, label]) => videoCheck(`notify-${prefix}-${kind}`, cfg[`${prefix}_notify_${kind}`] !== false, label)).join("");
}

function pathMappingsSection() {
    const maps = (autoCfg().path_mappings || []).map(mappingRow).join("");
    return `<section class="settings-section" data-tab="general"><h3>Remote path mappings</h3>
        <p class="muted">Use these when an app sees the library under a different path than Curator. Example: Radarr reports <span class="mono">/data/media/movies</span> and Curator mounts it at <span class="mono">/movies</span>. The longest matching path wins; rows for one app win over "Any app".</p>
        <div id="auto-maps" class="auto-rows">
            <div class="auto-map-head" aria-hidden="true"><span></span><span>Remote path</span><span></span><span>Local path</span><span></span></div>
            ${maps}
        </div>
        <p><button type="button" class="btn-ghost" data-action="auto-add-map">Add mapping</button></p>
    </section>`;
}

function libraryOn(cfg, key, legacy) {
    if (Object.prototype.hasOwnProperty.call(cfg || {}, key)) return cfg[key] !== false;
    return (cfg || {})[legacy] !== false;
}

function musicNotifySection(source, title, placeholder) {
    const cfg = state.settings || {};
    const on = cfg[`webhook_${source}_enabled`] !== false;
    return `<section class="settings-section" data-tab="integrations">${integrationHeading(source, title)}
        <p class="muted">Navidrome has no API key. A music change asks it to scan with the Subsonic user name and password. Each request sends md5(password + salt). Movie and episode changes do not use this address.</p>
        ${videoCheck("navidrome-enabled", (notifyCfg().navidrome_on !== false), "Enable Navidrome")}
        ${videoCheck(`webhook-${source}-enabled`, on, `Update the Navidrome music library after changes`)}
        ${autoField(`webhook-${source}-url`, "Address", cfg[`webhook_${source}`] || "", placeholder)}
        ${autoField(`webhook-${source}-user`, "User name", cfg[`webhook_${source}_user`] || "", "Navidrome user name")}
        ${videoKeyField(`webhook_${source}_key`, `webhook-${source}-key`, "Password", "WEBHOOK_NAVIDROME_PASSWORD", "The Navidrome account password. WEBHOOK_NAVIDROME_API_KEY in docker-compose is still read as this password.")}
        <p>${autoTest("navidrome", "Test scan")}</p>
        <p class="muted">The test uses the address, user name, and password on this form. A blank password keeps the one already saved. A saved scan token is not a password, so type the account password if a scan is refused.</p>
    </section>`;
}

function automationSettingsHtml() {
    const origin = `${location.protocol}//${location.host}`;
    const a = autoCfg();
    const n = notifyCfg();
    return `
        <section class="settings-section" data-tab="automation"><h3>Webhook queue</h3>
            ${videoCheck("auto-enabled", a.enabled !== false, "Accept webhooks from Radarr, Sonarr, Bazarr and Lidarr")}
            <p>Webhook address: <span class="mono">${escapeHtml(origin)}/api/v1/webhooks/arr?apikey=YOUR_KEY</span></p>
            <p id="auto-key-status" class="muted">Checking the webhook key…</p>
            <details class="auto-help"><summary>How to connect each app</summary>
                <p><strong>Radarr, Sonarr and Lidarr:</strong> Settings, Connect, add a Webhook. Paste the address above and set the method to POST. Turn on On Import, On Upgrade, On Rename and the file and item delete triggers. Replace <span class="mono">YOUR_KEY</span> with the value of <span class="mono">CMM_API_KEY</span>.</p>
                <p><strong>Bazarr:</strong> Settings, Notifications, add the Apprise address <span class="mono">json://${escapeHtml(location.host)}/api/v1/webhooks/arr?apikey=YOUR_KEY</span> (use <span class="mono">jsons://</span> behind HTTPS). Replace <span class="mono">YOUR_KEY</span> with <span class="mono">CMM_API_KEY</span>. Curator finds the movie or show from the message title.</p>
                <p>Lidarr's older webhook address on the Music tab keeps working.</p>
            </details>
            ${autoField("auto-debounce", "Debounce timer (minutes)", a.debounce_minutes, "20", "number")}
            ${autoField("auto-postpone", "Maximum postpone (minutes)", a.max_postpone_minutes, "120", "number")}
            <p class="muted">Each webhook for a new or changed folder restarts the timer. The maximum postpone counts from the oldest waiting webhook, so a long download queue still gets processed. Docker-compose (CMM_DEBOUNCE_MINUTES, CMM_MAX_POSTPONE_MINUTES) sets the starting values.</p>
            ${videoCheck("auto-scrape-movies", a.scrape_movies !== false, "Scrape movies found by a webhook scan")}
            ${videoCheck("auto-scrape-tv", a.scrape_tv !== false, "Scrape shows found by a webhook scan")}
            ${videoCheck("auto-music", a.music !== false, "Scrape music found by a webhook scan")}
            <p class="muted">Off leaves Lidarr import webhooks out of the music scan. The same switch is on the Music tab, and the Movies and TV Shows tabs hold the other two. Only the folders named in the webhooks are scanned. A deleted movie or show folder is removed from the library when the queue runs.</p>
            <p><button type="button" class="btn-ghost" data-action="queue-open">Open the queue</button></p>
        </section>
        <section class="settings-section" data-tab="notifications">${integrationHeading("kodi", "Kodi notifications")}
            ${autoField("notify-kodi-notify-host", "Kodi address", n.kodi_notify_host, "KODI_HOST or 192.168.1.20:8080")}
            ${autoField("notify-kodi-notify-user", "User name", n.kodi_notify_user, "KODI_USERNAME")}
            ${videoKeyField("kodi_password", "kodi-password", "Password", "KODI_PASSWORD")}
            <p>${autoTest("kodi_notify", "Test notification")}</p>
            <p class="muted">Shows a message on Kodi. Library updates stay on Integrations. A test uses the address on this form, and a blank password keeps the saved one. Empty addresses fall back to docker-compose.</p>
            ${noticeChecks("kodi", n)}
        </section>
        <section class="settings-section" data-tab="notifications">${integrationHeading("emby", "Emby notifications")}
            <p class="muted">Shows a message on Emby sessions. Uses the Emby server and API key from Integrations. Library updates stay there too.</p>
            <p>${autoTest("emby_notify", "Test notification")}</p>
            ${noticeChecks("emby", n)}
        </section>
        <section class="settings-section" data-tab="notifications">${integrationHeading("jellyfin", "Jellyfin notifications")}
            <p class="muted">Shows a message on Jellyfin sessions. Uses the Jellyfin server and API key from Integrations. Library updates stay there too.</p>
            <p>${autoTest("jellyfin_notify", "Test notification")}</p>
            ${noticeChecks("jellyfin", n)}
        </section>
        <section class="settings-section" data-tab="notifications">${integrationHeading("plex", "Plex notifications")}
            <p class="muted">Plex cannot show a message on its clients. Library updates stay on Integrations.</p>
        </section>`;
}

function kodiLibrarySettingsHtml() {
    const n = notifyCfg();
    const kodiPaths = (n.kodi_paths || []).map((row) => kodiPathRow(row)).join("");
    return `
        <section class="settings-section" data-tab="integrations">${integrationHeading("kodi", "Kodi library updates")}
            ${videoCheck("kodi-update-video", libraryOn(n, "kodi_video_enabled", "kodi_library_enabled"), "Update the Kodi video library after changes")}
            ${videoCheck("kodi-update-music", libraryOn(n, "kodi_music_enabled", "kodi_library_enabled"), "Update the Kodi music library after changes")}
            ${autoField("notify-kodi-library-host", "Kodi address", n.kodi_library_host, "KODI_LIBRARY_HOST or 192.168.1.20:8080")}
            ${autoField("notify-kodi-library-user", "User name", n.kodi_library_user, "KODI_LIBRARY_USERNAME")}
            ${videoKeyField("kodi_library_password", "kodi-library-password", "Password", "KODI_LIBRARY_PASSWORD", "Leave empty to use the notification password.")}
            ${autoField("notify-kodi-video-delay", "Wait before a video update (seconds)", n.kodi_video_delay, "60", "number")}
            ${autoField("notify-kodi-music-delay", "Wait before a music update (seconds)", n.kodi_music_delay, "300", "number")}
            <p class="muted">Music and video wait separately, and each change restarts its wait, so a burst of imports or tag writes becomes one Kodi scan. Webhook scans of movies and TV use the video wait; Lidarr imports and music tag writes use the music wait.</p>
            ${videoCheck("notify-kodi-clean", n.kodi_clean !== false, "Clean the Kodi video library once, after the whole update queue has finished")}
            <h3>Kodi paths</h3>
            <p class="muted">No path rows means one full video scan for movies and TV together, and one full music scan. Path rows scan only the changed folders, using the path Kodi shows. The webhook queue hands the folders over and does not wait. This job is removed when Kodi reports the scan finished. A stuck scan on Emby, Jellyfin, or Plex does not hold Kodi.</p>
            <div id="notify-kodi-paths" class="auto-rows">
                <div class="kodi-path-head" aria-hidden="true"><span>Curator path</span><span></span><span>Kodi path</span><span></span></div>
                ${kodiPaths}
            </div>
            <p><button type="button" class="btn-ghost" data-action="auto-add-kodi-path">Add Kodi path</button>
                <button type="button" class="btn-ghost" data-action="kodi-sources-upload">Upload sources.xml</button>
                ${autoTest("kodi_library")}</p>
            <input id="kodi-sources-file" class="kodi-upload-file" type="file" accept=".xml,text/xml" tabindex="-1" aria-hidden="true">
        </section>`;
}

function playerSettingsHtml() {
    const n = notifyCfg();
    const note = "A library update is queued for this player after Curator finishes a change, for each library switch that is on. It runs on its own and does not wait for the other players.";
    return `
        ${kodiLibrarySettingsHtml()}
        <section class="settings-section" data-tab="integrations">${integrationHeading("emby", "Emby")}
            ${videoCheck("emby-enabled", n.emby_on !== false, "Enable Emby")}
            <p class="muted">${note} EMBY_URL and EMBY_API_KEY in docker-compose are used when these fields are empty. Turning Emby off keeps the library switches and stops updates and on-screen messages.</p>
            ${videoCheck("emby-update-video", libraryOn(n, "emby_video_enabled", "emby_enabled"), "Update the Emby video library after changes")}
            ${videoCheck("emby-update-music", libraryOn(n, "emby_music_enabled", "emby_enabled"), "Update the Emby music library after changes")}
            ${autoField("notify-emby-url", "Emby address", n.emby_url, "EMBY_URL or http://192.168.1.30:8096")}
            ${videoKeyField("emby_token", "emby-token", "API key", "EMBY_API_KEY", "Emby Dashboard, Advanced, API Keys.")}
            ${playerPathFields("emby", n.emby_paths)}
            <p>${autoTest("emby")}</p>
        </section>
        <section class="settings-section" data-tab="integrations">${integrationHeading("jellyfin", "Jellyfin")}
            <p class="muted">${note} JELLYFIN_URL and JELLYFIN_API_KEY in docker-compose are used when these fields are empty.</p>
            ${videoCheck("jellyfin-update-video", libraryOn(n, "jellyfin_video_enabled", "jellyfin_enabled"), "Update the Jellyfin video library after changes")}
            ${videoCheck("jellyfin-update-music", libraryOn(n, "jellyfin_music_enabled", "jellyfin_enabled"), "Update the Jellyfin music library after changes")}
            ${autoField("notify-jellyfin-url", "Jellyfin address", n.jellyfin_url, "JELLYFIN_URL or http://192.168.1.30:8096")}
            ${videoKeyField("jellyfin_token", "jellyfin-token", "API key", "JELLYFIN_API_KEY", "Jellyfin Dashboard, API Keys.")}
            ${playerPathFields("jellyfin", n.jellyfin_paths)}
            <p>${autoTest("jellyfin")}</p>
        </section>
        <section class="settings-section" data-tab="integrations">${integrationHeading("plex", "Plex")}
            ${videoCheck("plex-enabled", n.plex_on !== false, "Enable Plex")}
            <p class="muted">${note} PLEX_URL and PLEX_TOKEN in docker-compose are used when these fields are empty. Turning Plex off keeps the library switches and stops updates.</p>
            ${videoCheck("notify-plex-video", libraryOn(n, "plex_video_enabled", "plex_enabled"), "Update the Plex video library after changes")}
            ${videoCheck("notify-plex-music", libraryOn(n, "plex_music_enabled", "plex_enabled"), "Update the Plex music library after changes")}
            ${autoField("notify-plex-url", "Plex address", n.plex_url, "PLEX_URL or http://192.168.1.30:32400")}
            ${videoKeyField("plex_token", "plex-token", "Plex token", "PLEX_TOKEN")}
            ${playerPathFields("plex", n.plex_paths)}
            <p>${autoTest("plex")}</p>
        </section>
        ${musicNotifySection("navidrome", "Navidrome", "http://navidrome:4533")}`;
}

function paintConnectionTest(button, ok) {
    if (!button) return;
    const original = button.dataset.testLabel || "Test connection";
    button.disabled = false;
    button.classList.add("conn-test");
    button.classList.toggle("is-ok", !!ok);
    button.classList.toggle("is-bad", !ok);
    button.setAttribute("aria-label", ok ? "Connected" : "Failed");
    button.textContent = ok ? "✓" : "✕";
    window.setTimeout(() => {
        if (!button.isConnected) return;
        button.classList.remove("is-ok", "is-bad");
        button.removeAttribute("aria-label");
        button.textContent = original;
        button.disabled = false;
    }, 3000);
}

function beginConnectionTest(button) {
    if (!button) return;
    const current = button.textContent || "";
    if (current && current !== "Testing…" && current !== "✓" && current !== "✕") button.dataset.testLabel = current;
    if (!button.dataset.testLabel) button.dataset.testLabel = "Test";
    button.disabled = true;
    button.classList.remove("is-ok", "is-bad");
    button.textContent = "Testing…";
}

async function testArrConnection(path, body, button) {
    const note = button && button.parentElement ? button.parentElement.querySelector("[data-arr-test]") : null;
    beginConnectionTest(button);
    try {
        const data = await api(path, { method: "POST", body });
        const message = data.message || "Connected.";
        if (note) {
            note.textContent = message;
            note.className = "key-set";
        }
        paintConnectionTest(button, true);
        notify(message, "success");
    } catch (error) {
        const message = (error && error.message) || "The connection test failed.";
        if (note) {
            note.textContent = message;
            note.className = "muted";
        }
        paintConnectionTest(button, false);
        notify(message, "error");
    }
}

function readAutomationSettings(root) {
    readRadarrSettings();
    readSonarrBazarrSettings();
    if (!root.querySelector("#auto-debounce")) return;
    const value = (id) => ((document.getElementById(id) || {}).value || "").trim();
    const checked = (id) => !!(document.getElementById(id) || {}).checked;
    const number = (id, fallback) => {
        const parsed = parseInt(value(id), 10);
        return Number.isFinite(parsed) ? parsed : fallback;
    };
    state.settings.automation = {
        ...autoCfg(),
        enabled: checked("auto-enabled"),
        debounce_minutes: number("auto-debounce", 20),
        max_postpone_minutes: number("auto-postpone", 120),
        scrape_movies: checked("auto-scrape-movies"),
        scrape_tv: checked("auto-scrape-tv"),
        music: checked("auto-music"),
        path_mappings: [...root.querySelectorAll("[data-auto-map]")].map((row) => ({
            source: row.querySelector("[data-map-source]").value,
            remote: row.querySelector("[data-map-remote]").value.trim(),
            local: row.querySelector("[data-map-local]").value.trim(),
        })).filter((row) => row.remote && row.local),
    };
    state.settings.notify = {
        ...notifyCfg(),
        kodi_video_enabled: checked("kodi-update-video"),
        kodi_music_enabled: checked("kodi-update-music"),
        kodi_library_enabled: checked("kodi-update-video") || checked("kodi-update-music"),
        kodi_library_host: value("notify-kodi-library-host"),
        kodi_library_user: value("notify-kodi-library-user"),
        kodi_video_delay: number("notify-kodi-video-delay", 60),
        kodi_music_delay: number("notify-kodi-music-delay", 300),
        kodi_clean: checked("notify-kodi-clean"),
        kodi_paths: [...root.querySelectorAll("[data-kodi-path]")].map((row) => ({
            local: row.querySelector("[data-kodi-local]").value.trim(),
            kodi: row.querySelector("[data-kodi-remote]").value.trim(),
        })).filter((row) => row.local && row.kodi),
        kodi_notify_enabled: ["video", "removed", "music", "failed"].some((kind) => checked(`notify-kodi-${kind}`)),
        kodi_notify_host: value("notify-kodi-notify-host"),
        kodi_notify_user: value("notify-kodi-notify-user"),
        kodi_notify_video: checked("notify-kodi-video"),
        kodi_notify_removed: checked("notify-kodi-removed"),
        kodi_notify_music: checked("notify-kodi-music"),
        kodi_notify_failed: checked("notify-kodi-failed"),
        emby_notify_video: checked("notify-emby-video"),
        emby_notify_removed: checked("notify-emby-removed"),
        emby_notify_music: checked("notify-emby-music"),
        emby_notify_failed: checked("notify-emby-failed"),
        jellyfin_notify_video: checked("notify-jellyfin-video"),
        jellyfin_notify_removed: checked("notify-jellyfin-removed"),
        jellyfin_notify_music: checked("notify-jellyfin-music"),
        jellyfin_notify_failed: checked("notify-jellyfin-failed"),
        jellyfin_video_enabled: checked("jellyfin-update-video"),
        jellyfin_music_enabled: checked("jellyfin-update-music"),
        jellyfin_enabled: checked("jellyfin-update-video") || checked("jellyfin-update-music"),
        jellyfin_url: value("notify-jellyfin-url"),
        emby_on: checked("emby-enabled"),
        plex_on: checked("plex-enabled"),
        navidrome_on: checked("navidrome-enabled"),
        plex_video_enabled: checked("notify-plex-video"),
        plex_music_enabled: checked("notify-plex-music"),
        plex_enabled: checked("notify-plex-video") || checked("notify-plex-music"),
        plex_url: value("notify-plex-url"),
        emby_video_enabled: checked("emby-update-video"),
        emby_music_enabled: checked("emby-update-music"),
        emby_enabled: checked("emby-update-video") || checked("emby-update-music"),
        emby_url: value("notify-emby-url"),
        emby_paths: playerPaths(root, "emby"),
        jellyfin_paths: playerPaths(root, "jellyfin"),
        plex_paths: playerPaths(root, "plex"),
    };
    readMusicNotify();
}

function readMusicNotify() {
    ["navidrome"].forEach((name) => {
        const enabled = document.getElementById(`webhook-${name}-enabled`);
        const url = document.getElementById(`webhook-${name}-url`);
        if (enabled) state.settings[`webhook_${name}_enabled`] = enabled.checked;
        if (url) state.settings[`webhook_${name}`] = url.value.trim();
        const user = document.getElementById(`webhook-${name}-user`);
        if (user) state.settings[`webhook_${name}_user`] = user.value.trim();
    });
}

function playerPaths(root, service) {
    return [...root.querySelectorAll(`[data-player-path="${service}"]`)].map((row) => ({
        local: row.querySelector("[data-player-local]").value.trim(),
        remote: row.querySelector("[data-player-remote]").value.trim(),
    })).filter((row) => row.local && row.remote);
}

async function loadAutomationInfo() {
    try {
        state.automationInfo = await api("/api/v1/automation/info");
    } catch (error) {
        state.automationInfo = null;
    }
    paintAutomationInfo();
}

function paintAutomationInfo() {
    const info = state.automationInfo;
    const status = document.getElementById("auto-key-status");
    if (status) {
        status.className = info && info.webhook_key_set ? "key-set" : "muted";
        status.textContent = !info
            ? "The webhook key status could not be read."
            : info.webhook_key_set
                ? "CMM_API_KEY is set. Put that value in the address where it says YOUR_KEY. Webhooks without it are refused."
                : "CMM_API_KEY is not set in docker-compose, so webhooks are refused until you add one.";
    }
    const env = (info && info.env) || {};
    const hints = {
        "notify-kodi-library-host": env.kodi_library_host, "notify-kodi-library-user": env.kodi_library_user,
        "notify-kodi-notify-host": env.kodi_notify_host, "notify-kodi-notify-user": env.kodi_notify_user,
        "notify-jellyfin-url": env.jellyfin_url, "notify-plex-url": env.plex_url,
        "notify-emby-url": env.emby_url,
    };
    Object.entries(hints).forEach(([id, hint]) => {
        const input = document.getElementById(id);
        if (input && hint) input.placeholder = `${hint} (from docker-compose)`;
    });
}

function connectionDraft(target) {
    const value = (id) => (id ? ((document.getElementById(id) || {}).value || "").trim() : "");
    const fields = {
        navidrome: ["webhook-navidrome-url", "webhook-navidrome-user", "webhook-navidrome-key"],
        kodi_library: ["notify-kodi-library-host", "notify-kodi-library-user", "kodi-library-password"],
        kodi_notify: ["notify-kodi-notify-host", "notify-kodi-notify-user", "kodi-password"],
        jellyfin: ["notify-jellyfin-url", "", "jellyfin-token"],
        jellyfin_notify: ["notify-jellyfin-url", "", "jellyfin-token"],
        emby: ["notify-emby-url", "", "emby-token"],
        emby_notify: ["notify-emby-url", "", "emby-token"],
        plex: ["notify-plex-url", "", "plex-token"],
    }[target] || [];
    return { url: value(fields[0]), user: value(fields[1]), secret: value(fields[2]) };
}

async function testAutomationConnection(button) {
    beginConnectionTest(button);
    const draft = connectionDraft(button.dataset.target);
    try {
        const data = await api("/api/v1/notify/test", {
            method: "POST",
            body: { target: button.dataset.target, url: draft.url, user: draft.user, secret: draft.secret },
        });
        paintConnectionTest(button, true);
        notify(data.message || "Connected.", "success");
    } catch (error) {
        paintConnectionTest(button, false);
        notify(error.message || "The connection test failed.", "error");
    }
}

// Queue panel.

function queueClock(seconds) {
    const total = Math.max(0, Number(seconds) || 0);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function queueRunLength(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
    return `${secs}s`;
}

function queueRunSeconds(item) {
    if (!item || item.running_seconds == null || item.running_seconds === "") return null;
    const base = Number(item.running_seconds);
    if (!Number.isFinite(base)) return null;
    const fetched = Number(state.queuePanel.fetchedAt) || Date.now();
    return Math.max(0, Math.floor(base + (Date.now() - fetched) / 1000));
}

function runningMark(item, label) {
    const seconds = queueRunSeconds(item);
    const text = seconds == null ? label : `${label} · ${queueRunLength(seconds)}`;
    return `<span class="muted queue-elapsed" data-label="${escapeHtml(label)}" data-base="${seconds == null ? "" : String(Math.floor(Number(item.running_seconds)))}">${escapeHtml(text)}</span>`;
}

function tickQueueElapsed() {
    const fetched = Number(state.queuePanel.fetchedAt) || Date.now();
    document.querySelectorAll("#queue-items .queue-elapsed").forEach((node) => {
        if (node.dataset.base === "") return;
        const base = Number(node.dataset.base);
        if (!Number.isFinite(base)) return;
        const seconds = Math.max(0, Math.floor(base + (Date.now() - fetched) / 1000));
        node.textContent = `${node.dataset.label || "Running"} · ${queueRunLength(seconds)}`;
    });
}

function armQueueClock() {
    if (state.queuePanel.clock) return;
    state.queuePanel.clock = setInterval(() => {
        if (!queuePanelOpen()) {
            clearInterval(state.queuePanel.clock);
            state.queuePanel.clock = 0;
            return;
        }
        tickQueueElapsed();
        if (Date.now() - (state.queuePanel.fetchedAt || 0) > 8000) {
            refreshQueuePanelSoon();
        }
    }, 1000);
}

async function openQueuePanel(tab) {
    if (tab) state.queuePanel.tab = tab;
    document.getElementById("queue-modal").classList.remove("hidden");
    paintQueueRing(live.queue || {});
    await refreshQueuePanel();
}

function queuePanelOpen() {
    const modal = document.getElementById("queue-modal");
    return !!modal && !modal.classList.contains("hidden");
}

function refreshQueuePanelSoon() {
    if (!queuePanelOpen()) return;
    clearTimeout(state.queuePanel.timer);
    state.queuePanel.timer = setTimeout(() => refreshQueuePanel().catch(() => {}), 250);
}

async function refreshQueuePanel() {
    if (!queuePanelOpen()) return;
    const [status, history] = await Promise.all([
        api("/api/v1/queue/status"),
        api("/api/v1/queue/events?limit=60"),
    ]);
    state.queuePanel.items = status.items || [];
    state.queuePanel.scans = status.scans || [];
    state.queuePanel.arr = status.arr || [];
    state.queuePanel.library = status.library || [];
    state.queuePanel.events = history.events || [];
    state.queuePanel.scanEvents = history.scans || [];
    state.queuePanel.arrEvents = history.arr || [];
    state.queuePanel.libraryEvents = history.library || [];
    state.queuePanel.fetchedAt = Date.now();
    paintQueueTabs();
    paintQueueRing(status);
    paintQueueLists();
    if (typeof paintQueuePill === "function") {
        live.queue = Object.assign({}, live.queue || {}, status);
        paintQueuePill();
    }
}

function queueTab() {
    return state.queuePanel.tab || "webhook";
}

function queueLaneCount(name) {
    const queue = live.queue || {};
    if (name === "webhook") return (Number(queue.queued_items_count) || 0) + (queue.running ? 1 : 0);
    if (name === "scan") return (state.queuePanel.scans || []).length;
    if (name === "arr") return (state.queuePanel.arr || queue.arr || []).length;
    if (name === "library") return (state.queuePanel.library || queue.library || []).length;
    return 0;
}

function paintQueueTabs() {
    const tab = queueTab();
    const labels = { webhook: "Webhook Queue", scan: "Scan Queue", arr: "ARR Queue", library: "Library updates", manual: "Manual library update" };
    document.querySelectorAll("[data-action='queue-tab']").forEach((button) => {
        const name = button.dataset.tab;
        const on = name === tab;
        const count = queueLaneCount(name);
        button.textContent = count ? `${labels[name] || name} (${count})` : (labels[name] || name);
        button.classList.toggle("is-active", on);
        button.setAttribute("aria-selected", on ? "true" : "false");
    });
    const webhook = tab === "webhook";
    const manual = tab === "manual";
    document.getElementById("queue-ring").classList.toggle("hidden", !webhook);
    document.getElementById("queue-flush").classList.toggle("hidden", !webhook);
    const manualHost = document.getElementById("queue-manual");
    if (manualHost) {
        if (manual && !manualHost.innerHTML) manualHost.innerHTML = manualLibraryHtml();
        manualHost.classList.toggle("hidden", !manual);
    }
    ["queue-top", "queue-list-title", "queue-items", "queue-events-wrap"].forEach((id) => {
        const node = document.getElementById(id);
        if (node) node.classList.toggle("hidden", manual);
    });
}

function selectQueueTab(tab) {
    state.queuePanel.tab = tab || "webhook";
    paintQueueTabs();
    paintQueueRing(live.queue || {});
    paintQueueLists();
    refreshQueuePanelSoon();
}

function paintQueueRing(queue) {
    if (!queuePanelOpen()) return;
    const tab = queueTab();
    const imports = Number(queue.queued_items_count) || 0;
    const scans = state.queuePanel.scans || queue.scans || [];
    const arr = state.queuePanel.arr || queue.arr || [];
    const library = state.queuePanel.library || queue.library || [];
    const waitingScans = scans.filter((item) => item.status !== "running");
    const waitingArr = arr.filter((item) => item.status !== "running");
    const waitingLibrary = library.filter((item) => item.status !== "running");
    const runningScan = scans.find((item) => item.status === "running");
    const runningArr = arr.find((item) => item.status === "running");
    const runningLibrary = library.filter((item) => item.status === "running");
    const remaining = Math.max(0, Number(queue.remaining_seconds) || 0);
    const total = Math.max(1, Number(queue.total_debounce_seconds) || 1);
    const bar = document.getElementById("queue-ring-bar");
    if (bar && tab === "webhook") {
        bar.style.strokeDasharray = `${QUEUE_RING}`;
        bar.style.strokeDashoffset = `${imports ? QUEUE_RING * (1 - Math.min(1, remaining / total)) : QUEUE_RING}`;
        bar.classList.toggle("is-running", !!queue.running);
    }
    const clock = document.getElementById("queue-clock");
    const count = document.getElementById("queue-count");
    if (clock) clock.textContent = queue.running ? "…" : imports ? queueClock(remaining) : "–";
    if (count) count.textContent = queue.running ? "Running" : imports ? "Starts in" : "Empty";
    const status = document.getElementById("queue-status");
    const rules = document.getElementById("queue-rules");
    const title = document.getElementById("queue-list-title");
    let text = "The queue is empty.";
    let rule = "";
    let heading = "Waiting";
    let busy = false;
    let clearable = false;
    if (tab === "scan") {
        heading = "Scans";
        clearable = waitingScans.length > 0;
        busy = !!runningScan;
        text = runningScan
            ? `${runningScan.label} is running.`
            : waitingScans.length
                ? `${waitingScans.length} scan${waitingScans.length === 1 ? "" : "s"} waiting.`
                : "No scans are waiting.";
        rule = "One library scan, scrape, or move runs at a time. Clear drops waiting scans. A scan that is already running stays until it finishes.";
    } else if (tab === "arr") {
        heading = "ARR";
        clearable = waitingArr.length > 0;
        busy = !!runningArr;
        text = runningArr
            ? `${runningArr.title} is running in ${runningArr.where}.`
            : waitingArr.length
                ? `${waitingArr.length} item${waitingArr.length === 1 ? "" : "s"} waiting.`
                : "Nothing is waiting for Radarr, Sonarr, or Lidarr.";
        rule = "One item at a time. Clear drops waiting items. The item already running stays until it finishes.";
    } else if (tab === "library") {
        heading = "Library updates";
        clearable = waitingLibrary.length > 0;
        busy = runningLibrary.length > 0;
        text = runningLibrary.length
            ? runningLibrary.map((item) => item.title).join(", ") + (runningLibrary.length === 1 ? " is scanning." : " are scanning.")
            : waitingLibrary.length
                ? `${waitingLibrary.length} update${waitingLibrary.length === 1 ? "" : "s"} waiting.`
                : "No library updates are waiting.";
        rule = "Each player runs on its own. A full library scan is one job per media type. Kodi uses one video scan for movies and TV when no path is set. Clear drops waiting updates. Cancel stops a scan Curator is still waiting on, including one that was already finished when Curator restarted.";
    } else {
        heading = "Waiting";
        clearable = imports > 0;
        busy = !!queue.running;
        const debounce = Math.round((Number(queue.total_debounce_seconds) || 0) / 60);
        const postpone = Math.round((Number(queue.max_postpone_seconds) || 0) / 60);
        text = queue.running
            ? (queue.message || "Processing the queue")
            : imports
                ? (queue.message || `Imports run in ${queueClock(remaining)} unless more arrive.`)
                : "The webhook queue is empty.";
        rule = `Timer ${debounce} min after the last import, never more than ${postpone} min after the first. After a folder is scanned, the library update is handed to each player. This queue does not send that update and does not wait for it.`;
    }
    if (title) keepText(title, heading);
    status.className = `scan-status ${busy ? "is-running" : clearable ? "is-stopped" : ""}`;
    keepText(status, text);
    keepText(rules, rule);
    const scanBusy = !!(queue.library_busy || (state.scan && state.scan.status === "running") || (state.videoScan && state.videoScan.status === "running"));
    const flush = document.getElementById("queue-flush");
    if (flush) {
        flush.disabled = !imports || !!queue.running || scanBusy;
        flush.title = scanBusy ? "Available when the running scan finishes." : "Run the waiting imports now.";
    }
    document.getElementById("queue-clear").disabled = !clearable;
}

const QUEUE_OUTCOMES = { queued: "Queued", ignored: "Ignored", unmapped: "Not in a library", test: "Test", noted: "Noted", done: "Finished", error: "Failed", cleared: "Cleared", started: "Started" };
const PROVIDER_ICONS = {
    radarr: "radarr.png", sonarr: "sonarr.png", lidarr: "lidarr.png", bazarr: "bazarr.png",
    trakt: "trakt.png", tvmaze: "tvmaze.png", kodi: "kodi.png", allmusic: "allmusic.png", "last.fm": "last.fm.png",
    emby: "emby.png", plex: "plex.png", jellyfin: "jellyfin.png", navidrome: "navidrome.png",
    curator: "/static/logo.svg",
};

function providerIcon(source) {
    const key = String(source || "").trim().toLowerCase();
    const label = key ? key.charAt(0).toUpperCase() + key.slice(1) : "";
    const file = PROVIDER_ICONS[key];
    if (!file) return escapeHtml(label);
    const src = file.startsWith("/") ? file : `/media/providers/${file}`;
    return `<img class="provider-icon" src="${src}" alt="${escapeHtml(label)}" title="${escapeHtml(label)}">`;
}

const MEDIA_GLYPHS = {
    music: { label: "Music", svg: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>` },
    movies: { label: "Movies", svg: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M7 4v16M17 4v16M2 9h5M2 15h5M17 9h5M17 15h5"/></svg>` },
    tv: { label: "TV shows", svg: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="m8 2 4 5 4-5"/></svg>` },
    sets: { label: "Movie sets", svg: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="12" height="14" rx="1.5"/><path d="M7 7V4.5A1.5 1.5 0 0 1 8.5 3h11A1.5 1.5 0 0 1 21 4.5v12a1.5 1.5 0 0 1-1.5 1.5H15"/></svg>` },
};

function mediaKind(value) {
    const key = String(value || "").trim().toLowerCase();
    if (key === "movie" || key === "movies") return "movies";
    if (key === "tv" || key === "show" || key === "shows") return "tv";
    if (key === "music") return "music";
    if (key === "set" || key === "sets") return "sets";
    if (key === "video") return "video";
    return "";
}

function mediaGlyph(kind, label) {
    const spec = MEDIA_GLYPHS[kind];
    if (!spec) return "";
    const name = label || spec.label;
    return `<span class="media-glyph" title="${escapeHtml(name)}" aria-label="${escapeHtml(name)}">${spec.svg}</span>`;
}

function mediaLabelHtml(value) {
    const kind = mediaKind(value);
    if (kind === "video") {
        return `<span class="media-glyphs" title="Movies and TV" aria-label="Movies and TV">${mediaGlyph("movies")}${mediaGlyph("tv")}</span>`;
    }
    const icon = mediaGlyph(kind);
    return icon || escapeHtml(value || "");
}

function pathFromUpdateMessage(message) {
    const match = String(message || "").match(/\b((?:[a-z][a-z0-9+.-]*:\/\/|[\\/])\S+)/i);
    return match ? match[1].replace(/[.)]+$/, "") : "";
}

function queueItemCell(item) {
    let title = String((item && item.title) || "").trim();
    let path = String((item && item.path) || "").trim();
    if (!title && !path) path = pathFromUpdateMessage(item && item.message);
    if (!title && path) title = path.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
    if (!title && !path) return "";
    const extra = path && path !== title ? `<br><small class="mono muted">${escapeHtml(path)}</small>` : "";
    return `${escapeHtml(title)}${extra}`;
}

function lookUpIn(source) {
    return `Look up in ${providerIcon(source)}`;
}

function integrationHeading(source, title) {
    const key = String(source || "").trim().toLowerCase();
    const icon = PROVIDER_ICONS[key] ? providerIcon(source) : "";
    return `<h3 class="integration-heading">${icon}<span>${escapeHtml(title)}</span></h3>${connectionErrorHtml(key)}`;
}

function connectionErrorHtml(name) {
    return `<p class="vscrape-error hidden" data-connection="${escapeHtml(name)}"></p>`;
}

function queueScanRow(scan) {
    const named = scan.titles || [];
    const paths = named.length ? named : ((scan.targets && scan.targets.length ? scan.targets : scan.roots) || []);
    const where = paths.length ? escapeHtml(paths.join(", ")) : "";
    const mode = scan.kind === "scrape" ? (scan.scope || scan.mode || "selected") : (scan.mode || scan.kind || "");
    const running = scan.status === "running";
    return `<tr>
        <td><strong>${escapeHtml(scan.label || "Library scan")}</strong></td>
        <td>${mediaLabelHtml(scan.media)}</td>
        <td>${escapeHtml(mode)}</td>
        <td class="mono">${where}</td>
        <td>${running ? `${runningMark(scan, "Running")} <button type="button" class="btn-ghost btn-remove" data-action="queue-cancel-scan" data-id="${escapeHtml(scan.id)}">Cancel</button>` : `<button type="button" class="btn-ghost btn-remove" data-action="queue-drop-scan" data-id="${escapeHtml(scan.id)}">Remove</button>`}</td>
    </tr>`;
}

function queueLibraryRow(item) {
    const running = item.status === "running";
    const names = (item.items || []).filter(Boolean);
    const what = names.length
        ? `${escapeHtml(names.join(", "))}<br><small class="muted">${escapeHtml(item.scope || "")}</small>`
        : escapeHtml(item.scope || "");
    const button = running ? "Cancel" : "Remove";
    const stateLabel = running ? runningMark(item, "Scanning") : "Queued";
    return `<tr>
        <td>${providerIcon(item.player || item.source)}</td>
        <td>${mediaLabelHtml(item.media)}</td>
        <td>${what}</td>
        <td>${stateLabel} <button type="button" class="btn-ghost btn-remove" data-action="queue-drop-library" data-id="${escapeHtml(item.id)}">${button}</button></td>
    </tr>`;
}

function queueArrRow(item) {
    const running = item.status === "running";
    const front = item.front ? `<br><small class="muted">Front of line</small>` : "";
    return `<tr>
        <td><strong>${escapeHtml(item.title || "Queued")}</strong>${front}</td>
        <td>${providerIcon(item.source || item.where)}</td>
        <td>${running ? runningMark(item, "Running") : `<button type="button" class="btn-ghost btn-remove" data-action="queue-drop-arr" data-id="${escapeHtml(item.id)}">Remove</button>`}</td>
    </tr>`;
}

function queueGrouped(rows, head, rowHtml) {
    const running = rows.filter((item) => item.status === "running");
    const waiting = rows.filter((item) => item.status !== "running");
    const block = (title, list) => {
        if (!list.length) return "";
        return `<h3 class="queue-group">${title}</h3><table class="queue-table"><thead><tr>${head}</tr></thead><tbody>${list.map(rowHtml).join("")}</tbody></table>`;
    };
    return block("Running", running) + block("Waiting", waiting);
}

function paintQueueLists() {
    const tab = queueTab();
    const host = document.getElementById("queue-items");
    let html = "";
    if (tab === "scan") {
        html = queueGrouped(state.queuePanel.scans || [], "<th>Item</th><th>Media</th><th>Mode</th><th>Where</th><th></th>", queueScanRow);
    } else if (tab === "arr") {
        html = queueGrouped(state.queuePanel.arr || [], "<th>Item</th><th>Where</th><th></th>", queueArrRow);
    } else if (tab === "library") {
        html = queueGrouped(state.queuePanel.library || [], "<th>Player</th><th>Media</th><th>Items</th><th>Status</th>", queueLibraryRow);
    } else {
        const items = state.queuePanel.items || [];
        html = queueGrouped(items, "<th>Item</th><th>From</th><th>Event</th><th>Webhooks</th><th></th>", (item) => `<tr>
            <td><strong>${escapeHtml(item.title || item.path)}</strong><br><small class="mono muted">${escapeHtml(item.path)}</small></td>
            <td>${providerIcon(item.source)}</td>
            <td>${mediaLabelHtml(item.event_type)}${item.removed ? " (delete)" : ""}</td>
            <td>${Number(item.events) || 1}</td>
            <td>${item.status === "running" ? `${runningMark(item, "Running")} <button type="button" class="btn-ghost btn-remove" data-action="queue-cancel-import" data-id="${escapeHtml(item.id)}">Cancel</button>` : `<button type="button" class="btn-ghost btn-remove" data-action="queue-drop" data-id="${escapeHtml(item.id)}">Remove</button>`}</td>
        </tr>`);
    }
    replaceHtml(host, html || `<p class="muted">Nothing queued.</p>`);
    armQueueClock();
    paintQueueHistory();
}

function libraryRetryButton(item) {
    if (!item || item.outcome !== "error" || item.event_type !== "Update" || !item.id) return "";
    const text = String(item.message || "");
    if (!item.path && !/library scan failed for |did not report a scan for |library refresh failed|library update failed/i.test(text)) return "";
    return ` <button type="button" class="btn-ghost" data-action="queue-library-retry" data-id="${escapeHtml(item.id)}">Retry</button>`;
}

function queueHistoryTable(rows, empty) {
    if (!rows.length) return `<p class="muted">${empty}</p>`;
    return `<table class="queue-table"><thead><tr><th>Time</th><th>Where</th><th>Event</th><th>Item</th><th>Result</th></tr></thead><tbody>${rows.map((item) => `<tr class="queue-${escapeHtml(item.outcome)}">
        <td class="mono queue-fit">${escapeHtml(String(item.received_at || "").replace("T", " ").slice(0, 19))}</td>
        <td class="queue-fit">${item.whereHtml || mediaLabelHtml(item.where || item.source || "")}</td>
        <td class="queue-fit">${mediaLabelHtml(item.event_type || "")}</td>
        <td>${queueItemCell(item)}</td>
        <td class="queue-fit">${escapeHtml(QUEUE_OUTCOMES[item.outcome] || item.outcome)}${item.message && (item.outcome === "error" || item.showMessage) ? `<br><small class="muted">${escapeHtml(item.message)}</small>` : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function paintQueueHistory() {
    const tab = queueTab();
    const title = document.getElementById("queue-events-title");
    const host = document.getElementById("queue-events");
    if (tab === "scan") {
        if (title) title.textContent = "Recent scans";
        const rows = (state.queuePanel.scanEvents || []).map((item) => ({ ...item, where: item.message || item.source || "" }));
        replaceHtml(host, queueHistoryTable(rows, "No scans yet."));
        return;
    }
    if (tab === "arr") {
        if (title) title.textContent = "Recent ARR";
        const rows = (state.queuePanel.arrEvents || []).map((item) => ({
            ...item,
            whereHtml: providerIcon(item.source),
        }));
        replaceHtml(host, queueHistoryTable(rows, "Nothing has finished yet."));
        return;
    }
    if (tab === "library") {
        if (title) title.textContent = "Recent library updates";
        const rows = (state.queuePanel.libraryEvents || []).map((item) => ({
            ...item,
            whereHtml: providerIcon(item.source),
            showMessage: true,
        }));
        replaceHtml(host, queueHistoryTable(rows, "No library updates yet."));
        return;
    }
    if (title) title.textContent = "Recent webhooks";
    const events = state.queuePanel.events || [];
    replaceHtml(host, events.length
        ? `<table class="queue-table"><thead><tr><th>Time</th><th>From</th><th>Event</th><th>Item</th><th>Result</th></tr></thead><tbody>${events.map((item) => `<tr class="queue-${escapeHtml(item.outcome)}">
            <td class="mono queue-fit">${escapeHtml(String(item.received_at || "").replace("T", " ").slice(0, 19))}</td>
            <td class="queue-fit">${providerIcon(item.source)}</td>
            <td class="queue-fit">${mediaLabelHtml(item.event_type)}</td>
            <td>${queueItemCell(item)}</td>
            <td class="queue-fit">${escapeHtml(QUEUE_OUTCOMES[item.outcome] || item.outcome)}${libraryRetryButton(item)}${item.message ? `<br><small class="muted">${escapeHtml(item.message)}</small>` : ""}</td>
        </tr>`).join("")}</tbody></table>`
        : `<p class="muted">No webhooks yet.</p>`);
}

async function retryLibraryUpdate(id) {
    const data = await api("/api/v1/queue/library/retry", { method: "POST", body: { id } });
    notify(data.message || "Library update queued.", "info");
    if (state.queuePanel) state.queuePanel.tab = "library";
    refreshQueuePanelSoon();
}

async function queueManualLibrary(action) {
    const body = {
        player: action.dataset.player,
        media: action.dataset.media,
        action: action.dataset.clean === "true" ? "clean" : "scan",
    };
    const data = await api("/api/v1/queue/library/manual", { method: "POST", body });
    notify(data.message || "Library update queued.", "info");
    if (state.queuePanel) state.queuePanel.tab = "library";
    paintQueueTabs();
    refreshQueuePanelSoon();
}

function manualLibraryHtml() {
    const scan = (player, media, label) =>
        `<button type="button" data-action="queue-library-manual" data-player="${player}" data-media="${media}">${label}</button>`;
    const buttons = [
        scan("player", "movies", "Update movies"),
        scan("player", "tv", "Update TV shows"),
        scan("player", "music", "Update music"),
    ].join("");
    const players = [
        ["kodi", "Kodi", `${scan("kodi", "movies", "Scan movies")}${scan("kodi", "tv", "Scan TV shows")}${scan("kodi", "music", "Scan music")}<button type="button" class="btn-ghost" data-action="queue-library-manual" data-player="kodi" data-media="video" data-clean="true">Clean video library</button><button type="button" class="btn-ghost" data-action="queue-library-manual" data-player="kodi" data-media="music" data-clean="true">Clean music library</button>`],
        ["emby", "Emby", buttons.replaceAll("player", "emby")],
        ["jellyfin", "Jellyfin", buttons.replaceAll("player", "jellyfin")],
        ["plex", "Plex", buttons.replaceAll("player", "plex")],
        ["navidrome", "Navidrome", scan("navidrome", "music", "Scan music")],
    ];
    return players.map(([player, title, actions]) => `<section class="manual-player">${integrationHeading(player, title)}<div class="job-actions">${actions}</div></section>`).join("");
}

async function queueKodiLibrary(media) {
    const data = await api("/api/v1/queue/kodi", { method: "POST", body: { media } });
    notify(data.message || "Kodi library update queued.", "info");
    if (state.queuePanel) state.queuePanel.tab = "library";
    refreshQueuePanelSoon();
}

async function flushQueue() {
    await api("/api/v1/queue/flush", { method: "POST", body: {} });
    notify("The queue runs now.", "info");
    refreshQueuePanelSoon();
}

function clearQueueAsk() {
    const tab = queueTab();
    if (tab === "scan") {
        askDanger(
            "Clear the scan queue?",
            "Waiting scans are dropped. A scan that is already running stays until it finishes.",
            "Clear",
            async () => {
                const data = await api("/api/v1/queue/scans/clear", { method: "POST", body: {} });
                const scans = Number(data.cleared) || 0;
                notify(`Cleared ${scans} waiting scan${scans === 1 ? "" : "s"}.`, "info");
                refreshQueuePanelSoon();
            },
            true,
        );
        return;
    }
    if (tab === "arr") {
        askDanger(
            "Clear the ARR queue?",
            "Waiting Radarr, Sonarr, and Lidarr items are dropped. The item already running stays until it finishes.",
            "Clear",
            async () => {
                const data = await api("/api/v1/queue/arr/clear", { method: "POST", body: {} });
                const count = Number(data.cleared) || 0;
                notify(`Cleared ${count} waiting item${count === 1 ? "" : "s"}.`, "info");
                refreshQueuePanelSoon();
            },
            true,
        );
        return;
    }
    if (tab === "library") {
        askDanger(
            "Clear library updates?",
            "Waiting updates are dropped. A scan that is already running stays until that player reports it finished.",
            "Clear",
            async () => {
                const data = await api("/api/v1/queue/library/clear", { method: "POST", body: {} });
                const count = Number(data.cleared) || 0;
                notify(`Cleared ${count} waiting update${count === 1 ? "" : "s"}.`, "info");
                refreshQueuePanelSoon();
            },
            true,
        );
        return;
    }
    askDanger(
        "Clear the webhook queue?",
        "Waiting imports are dropped. An import that is already running stays until that folder is scanned.",
        "Clear",
        async () => {
            const data = await api("/api/v1/queue/clear", { method: "POST", body: {} });
            const imports = Number(data.cleared) || 0;
            notify(`Cleared ${imports} import${imports === 1 ? "" : "s"}.`, "info");
            refreshQueuePanelSoon();
        },
        true,
    );
}

async function dropQueueItem(id) {
    await api(`/api/v1/queue/items/${encodeURIComponent(id)}`, { method: "DELETE", body: {} });
    refreshQueuePanelSoon();
}

async function dropQueuedScan(id) {
    await api(`/api/v1/queue/scans/${encodeURIComponent(id)}`, { method: "DELETE", body: {} });
    refreshQueuePanelSoon();
}

async function cancelQueuedScan(id) {
    await api(`/api/v1/queue/scans/${encodeURIComponent(id)}/cancel`, { method: "POST", body: {} });
    notify("Stopping the scan. Items already read stay in the library.", "info");
    refreshQueuePanelSoon();
}

async function cancelQueueImport(id) {
    await api(`/api/v1/queue/items/${encodeURIComponent(id)}/cancel`, { method: "POST", body: {} });
    notify("Stopping that import.", "info");
    refreshQueuePanelSoon();
}

async function dropQueuedArr(id) {
    await api(`/api/v1/queue/arr/${encodeURIComponent(id)}`, { method: "DELETE", body: {} });
    refreshQueuePanelSoon();
}

async function dropQueuedLibrary(id) {
    await api(`/api/v1/queue/library/${encodeURIComponent(id)}`, { method: "DELETE", body: {} });
    refreshQueuePanelSoon();
}

function savedKodiPaths() {
    return [...document.querySelectorAll("#notify-kodi-paths [data-kodi-path]")].map((node) => ({
        local: (node.querySelector("[data-kodi-local]").value || "").trim().replace(/\/+$/, ""),
        kodi: (node.querySelector("[data-kodi-remote]").value || "").trim().replace(/\/+$/, ""),
    })).filter((row) => row.local && row.kodi);
}

function kodiPathKey(value) {
    return String(value || "").trim().replace(/\/+$/, "");
}

function kodiSourceRow(row, saved) {
    const item = row || {};
    const mapped = (saved || []).some((known) => known.local === kodiPathKey(item.local) && known.kodi === kodiPathKey(item.kodi));
    const tone = mapped ? " is-mapped" : (item.sure ? "" : " kodi-source-guess");
    const lock = mapped ? " disabled" : "";
    return `<div class="kodi-source-row${tone}" data-kodi-source ${mapped ? "data-mapped" : ""} data-media="${escapeHtml(item.media || "video")}">
        <input type="checkbox" data-kodi-keep ${mapped ? "disabled" : (item.local && item.sure !== false ? "checked" : "")} aria-label="Use this mapping">
        <input type="text" data-kodi-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator" spellcheck="false" aria-label="Curator path"${lock}>
        <span aria-hidden="true">→</span>
        <input type="text" data-kodi-remote value="${escapeHtml(item.kodi || "")}" placeholder="Path in Kodi" spellcheck="false" aria-label="Kodi path"${lock}>
        <button type="button" class="btn-ghost" data-action="kodi-sources-remove">Remove</button>
        <p class="muted kodi-source-note">${mapped ? `<span class="kodi-mapped-label">Already mapped</span>` : ""}${escapeHtml(item.name ? `${item.name}: ` : "")}${escapeHtml(item.reason || "")}</p>
        <p class="kodi-source-result" data-kodi-result></p>
    </div>`;
}

async function readKodiSources(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const xml = await file.text();
    input.value = "";
    const data = await api("/api/v1/kodi/sources", { method: "POST", body: { xml } });
    const saved = savedKodiPaths();
    const rows = [...(data.rows || []), ...(data.unmatched || []).map((item) => ({ ...item, kodi: item.url || item.kodi || "", local: "" }))];
    const list = document.getElementById("kodi-sources-list");
    const note = document.getElementById("kodi-sources-note");
    list.innerHTML = rows.length ? rows.map((row) => kodiSourceRow(row, saved)).join("") : `<p class="muted">That file has no NFS or SMB sources.</p>`;
    const guessed = (data.rows || []).filter((item) => !item.sure).length;
    note.textContent = rows.length
        ? `Accept copies the checked rows into Kodi paths. Save settings afterwards to keep them. ${guessed ? "A row that only shares a folder name starts unchecked. " : ""}Test asks the saved Kodi library host to open one checked path at a time and compares a few items with the Curator folder.`
        : "That file has no NFS or SMB sources.";
    document.getElementById("kodi-sources-modal").classList.remove("hidden");
}

function kodiSourceDraft() {
    return [...document.querySelectorAll("#kodi-sources-list [data-kodi-source]")].filter((row) => {
        if (row.dataset.mapped) return false;
        const keep = row.querySelector("[data-kodi-keep]");
        return keep && keep.checked;
    }).map((row) => ({
        local: row.querySelector("[data-kodi-local]").value.trim(),
        kodi: row.querySelector("[data-kodi-remote]").value.trim(),
        media: row.dataset.media || "video",
        node: row,
    }));
}

async function testKodiSources() {
    const rows = kodiSourceDraft();
    if (!rows.length) {
        notify("Check at least one mapping to test.", "warning");
        return;
    }
    rows.forEach((row) => paintKodiProbe(row.node, { pending: true, message: "Waiting…" }));
    for (const row of rows) {
        paintKodiProbe(row.node, { pending: true, active: true });
        try {
            const data = await api("/api/v1/kodi/sources/test", {
                method: "POST",
                body: { rows: [{ local: row.local, kodi: row.kodi, media: row.media }] },
            });
            paintKodiProbe(row.node, (data.results || [])[0] || { ok: false, message: "Kodi did not return a result" });
        } catch (error) {
            paintKodiProbe(row.node, { ok: false, message: error.message || "The test failed" });
        }
    }
}

function paintKodiProbe(row, result) {
    if (!row) return;
    const node = row.querySelector("[data-kodi-result]");
    if (!node) return;
    row.classList.remove("is-match", "is-fail", "is-testing");
    if (result && result.pending) {
        const active = !!result.active;
        row.classList.toggle("is-testing", active);
        node.className = "kodi-source-result";
        node.innerHTML = active
            ? `<span class="kodi-testing">Testing…</span>`
            : escapeHtml(result.message || "Waiting…");
        if (active) row.scrollIntoView({ block: "nearest" });
        return;
    }
    const ok = !!(result && result.ok);
    row.classList.add(ok ? "is-match" : "is-fail");
    node.className = `kodi-source-result ${ok ? "is-ok" : "is-bad"}`;
    node.innerHTML = `<span class="kodi-mark" aria-hidden="true">${ok ? "✓" : "✕"}</span><span>${escapeHtml((result && result.message) || "")}</span>`;
}

function acceptKodiSources() {
    const box = document.getElementById("notify-kodi-paths");
    if (!box) return;
    const picked = kodiSourceDraft().filter((row) => row.local && row.kodi);
    if (!picked.length) {
        notify("Check a mapping that has both paths.", "warning");
        return;
    }
    picked.forEach((row) => {
        const existing = [...box.querySelectorAll("[data-kodi-path]")].find((node) => node.querySelector("[data-kodi-local]").value.trim() === row.local);
        if (existing) existing.querySelector("[data-kodi-remote]").value = row.kodi;
        else box.insertAdjacentHTML("beforeend", kodiPathRow(row));
    });
    document.getElementById("kodi-sources-modal").classList.add("hidden");
    notify(`Added ${picked.length} Kodi path${picked.length === 1 ? "" : "s"}. Save settings to keep them.`, "success");
}

const AUTOMATION_ACTIONS = {
    "queue-open": (action) => {
        // The taskbar buttons toggle the queue; the "Open the queue" link in Settings only opens it.
        if (queuePanelOpen() && action && action.closest && action.closest("#dock-queue, #queue-pill, #jobs-queue-btn")) {
            document.getElementById("queue-modal").classList.add("hidden");
            return;
        }
        runAction(openQueuePanel);
    },
    "queue-flush": () => runAction(flushQueue),
    "queue-kodi": (action) => runAction(() => queueKodiLibrary(action.dataset.media)),
    "queue-library-manual": (action) => runAction(() => queueManualLibrary(action), "Queuing…"),
    "queue-library-retry": (action) => runAction(() => retryLibraryUpdate(action.dataset.id), "Queuing…"),
    "queue-clear": () => clearQueueAsk(),
    "queue-tab": (action) => selectQueueTab(action.dataset.tab),
    "queue-drop": (action) => runAction(() => dropQueueItem(action.dataset.id)),
    "queue-drop-scan": (action) => runAction(() => dropQueuedScan(action.dataset.id)),
    "queue-cancel-scan": (action) => runAction(() => cancelQueuedScan(action.dataset.id)),
    "queue-cancel-import": (action) => runAction(() => cancelQueueImport(action.dataset.id)),
    "queue-drop-arr": (action) => runAction(() => dropQueuedArr(action.dataset.id)),
    "queue-drop-library": (action) => runAction(() => dropQueuedLibrary(action.dataset.id)),
    "auto-add-map": () => document.getElementById("auto-maps").insertAdjacentHTML("beforeend", mappingRow()),
    "auto-add-kodi-path": () => document.getElementById("notify-kodi-paths").insertAdjacentHTML("beforeend", kodiPathRow()),
    "auto-add-player-path": (action) => {
        const box = document.getElementById(`notify-${action.dataset.player}-paths`);
        if (box) box.insertAdjacentHTML("beforeend", playerPathRow(action.dataset.player));
    },
    "kodi-sources-upload": () => {
        const input = document.getElementById("kodi-sources-file");
        if (input) input.click();
    },
    "kodi-sources-remove": (action) => {
        const row = action.closest("[data-kodi-source]");
        if (row) row.remove();
    },
    "kodi-sources-test": () => runAction(testKodiSources, "Asking Kodi…"),
    "kodi-sources-accept": () => acceptKodiSources(),
    "auto-ob-add": () => obAdd(),
    "auto-ob-remove": (action) => obRemove(action.dataset.id),
    "auto-ob-test": (action) => obTest(action.dataset.id),
    "auto-row-remove": (action) => { const row = action.closest(".auto-row"); if (row) row.remove(); },
    "auto-test": (action) => testAutomationConnection(action),
    "auto-radarr-test": (action) => testArrConnection("/api/v1/radarr/test", radarrConnection(), action),
    "auto-radarr-load": () => runAction(loadRadarrOptions, "Asking Radarr…"),
    "auto-sonarr-test": (action) => testArrConnection("/api/v1/sonarr/test", sonarrConnection(), action),
    "auto-sonarr-load": () => runAction(loadSonarrOptions, "Asking Sonarr…"),
    "auto-bazarr-test": (action) => testArrConnection("/api/v1/bazarr/test", {
        url: (document.getElementById("bazarr-url") || {}).value || "",
        key: (document.getElementById("bazarr-api-key") || {}).value || "",
    }, action),
    "auto-lidarr-test": (action) => testArrConnection("/api/v1/lidarr/test", lidarrConnection(), action),
    "auto-lidarr-load": () => runAction(loadLidarrOptions, "Asking Lidarr…"),
};

function onAutomationAction(name, action) {
    const run = AUTOMATION_ACTIONS[name];
    if (!run) return false;
    run(action);
    return true;
}
