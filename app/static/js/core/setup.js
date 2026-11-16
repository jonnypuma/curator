// Setup wizard: library folders, metadata sources, download apps, players, then the first scans.
// Every step saves through PUT /api/settings (settingsPutBody, the same body the Settings window sends) and every
// Test button calls the endpoint the Settings window uses, so the server applies the same rules both ways.

const SETUP_STEPS = [
    { id: "welcome", title: "Welcome", short: "Start" },
    { id: "folders", title: "Library folders", short: "Folders" },
    { id: "sources", title: "Metadata and artwork", short: "Sources" },
    { id: "arr", title: "Download apps", short: "Download apps" },
    { id: "players", title: "Players", short: "Players" },
    { id: "finish", title: "Finish", short: "Finish" },
];
const SETUP_MEDIA = [
    ["music", "Music", "music_paths", "Albums in artist folders, for example /music."],
    ["movies", "Movies", "movie_paths", "One folder per movie, for example /movies."],
    ["tv", "TV shows", "tv_paths", "One folder per show with season folders, for example /tv."],
    ["musicvideos", "Music videos", "musicvideo_paths", "Video files of songs, for example /musicvideos."],
];
const SETUP_MEDIA_GLYPH = {
    musicvideos: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/></svg>`,
};
const SETUP_KEYS = {
    tmdb: { field: "tmdb_key", label: "TMDB", env: "TMDB_API_KEY", link: "https://www.themoviedb.org/settings/api",
        what: "API key or read access token", badge: "Recommended",
        note: "The main source for movies, movie sets and TV: titles, plots, cast, posters and fanart. Free with a TMDB account." },
    tvdb: { field: "tvdb_key", label: "TheTVDB", env: "TVDB_API_KEY", link: "https://thetvdb.com/api-information",
        what: "v4 API key", badge: "Optional",
        note: "TV works with TMDB alone. A TheTVDB key adds it as a TV source and as a fallback for DVD and absolute episode order." },
    fanart: { field: "fanart_key", label: "Fanart.tv", env: "FANART_API_KEY", link: "https://fanart.tv/get-an-api-key/",
        what: "personal API key", badge: "Recommended",
        note: "Clear logos, clear art, disc art, banners and extra fanart for music, movies, sets and TV." },
    omdb: { field: "omdb_key", label: "OMDb", env: "OMDB_API_KEY", link: "https://www.omdbapi.com/apikey.aspx",
        what: "API key", badge: "Optional",
        note: "IMDb, Rotten Tomatoes and Metacritic ratings. A free key allows 1,000 lookups a day." },
    lastfm: { field: "lastfm_key", label: "Last.fm", env: "LASTFM_API_KEY", link: "https://www.last.fm/api/account/create",
        what: "API key", badge: "Optional", icon: "last.fm",
        note: "Artist biographies, album reviews and tags." },
    acoustid: { field: "acoustid_key", label: "AcoustID", env: "ACOUSTID_API_KEY", link: "https://acoustid.org/new-application",
        what: "application API key", badge: "Optional",
        note: "Identifies albums by their sound when the tags are not enough." },
};
const SETUP_ARR = {
    radarr: { label: "Radarr", port: "7878", media: "movies", where: "Radarr, Settings, General, API Key" },
    sonarr: { label: "Sonarr", port: "8989", media: "TV shows", where: "Sonarr, Settings, General, API Key" },
    lidarr: { label: "Lidarr", port: "8686", media: "music", where: "Lidarr, Settings, General, API Key" },
    bazarr: { label: "Bazarr", port: "6767", media: "subtitles", where: "Bazarr, Settings, General, API Key" },
};
const SETUP_PLAYERS = {
    kodi: { label: "Kodi", target: "kodi_library", host: "kodi_library_host", user: "kodi_library_user", secret: "kodi_library_password",
        placeholder: "192.168.1.20:8080", secretLabel: "Password", env: "KODI_LIBRARY_PASSWORD", paths: "kodi_paths", remoteKey: "kodi",
        where: "In Kodi: Settings, Services, Control, allow remote control via HTTP. The port is 8080 unless you changed it." },
    plex: { label: "Plex", target: "plex", host: "plex_url", secret: "plex_token", placeholder: "http://192.168.1.30:32400",
        secretLabel: "Plex token", env: "PLEX_TOKEN", paths: "plex_paths", remoteKey: "remote", on: "plex_on",
        where: "The token is in any item's Get Info, View XML address (X-Plex-Token=…)." },
    emby: { label: "Emby", target: "emby", host: "emby_url", secret: "emby_token", placeholder: "http://192.168.1.30:8096",
        secretLabel: "API key", env: "EMBY_API_KEY", paths: "emby_paths", remoteKey: "remote", on: "emby_on",
        where: "Emby Dashboard, Advanced, API Keys." },
    jellyfin: { label: "Jellyfin", target: "jellyfin", host: "jellyfin_url", secret: "jellyfin_token", placeholder: "http://192.168.1.30:8096",
        secretLabel: "API key", env: "JELLYFIN_API_KEY", paths: "jellyfin_paths", remoteKey: "remote",
        where: "Jellyfin Dashboard, API Keys." },
};

state.setup = null;

function setupBlank() {
    return { step: 0, visited: new Set([0]), saved: new Set(), dirty: new Set(), folders: {}, kinds: {}, checks: {}, mounts: [], cmmKey: "", busy: false };
}

async function maybeOpenSetupWizard() {
    try {
        const status = await api("/api/v1/setup/status");
        if (status && status.first_run) await openSetupWizard({ auto: true });
    } catch (error) { /* the wizard is a convenience; a failed check leaves the app as it is */ }
}

async function openSetupWizard(options) {
    const modal = document.getElementById("setup-modal");
    if (!modal) return;
    // The Settings window and the wizard share element ids (the Trakt box), so the hidden Settings form is emptied;
    // it is drawn again from the server the next time Settings opens.
    const settingsModal = document.getElementById("settings-modal");
    if (settingsModal) settingsModal.classList.add("hidden");
    const settingsBody = document.getElementById("settings-body");
    if (settingsBody) settingsBody.innerHTML = "";
    state.clearKeys = state.clearKeys || {};
    state.setup = setupBlank();
    state.setup.auto = !!(options && options.auto);
    document.getElementById("setup-body").innerHTML = `<p class="muted setup-loading">Loading settings…</p>`;
    modal.classList.remove("hidden");
    try {
        const [cfg, system] = await Promise.all([api("/api/settings"), api("/api/system")]);
        state.ownFolders = system.own_folders || [];
        state.settings = cfg;
        state.mounts = system.mounts || [];
        state.setup.mounts = state.mounts;
        state.setup.cmmKey = system.cmm_api_key || "";
        SETUP_MEDIA.forEach(([media, , key]) => { state.setup.folders[media] = [...(cfg[key] || [])]; });
        state.setup.kinds = { ...(cfg.music_path_kinds || {}) };
        renderSetupWizard();
    } catch (error) {
        document.getElementById("setup-body").innerHTML = `<p class="settings-warning">${escapeHtml(error.message || "Settings could not be loaded.")}</p>`;
    }
}

function closeSetupWizard() {
    const modal = document.getElementById("setup-modal");
    if (modal) modal.classList.add("hidden");
    const body = document.getElementById("setup-body");
    if (body) body.innerHTML = "";
    state.setup = null;
    api("/api/v1/setup/done", { method: "POST", body: {} }).catch(() => {});
    if (typeof pollSystem === "function") pollSystem();
}

function renderSetupWizard() {
    const body = document.getElementById("setup-body");
    body.innerHTML = SETUP_STEPS.map((step, index) => `<section class="setup-panel hidden" data-setup-panel="${step.id}" data-setup-index="${index}" aria-labelledby="setup-head-${step.id}"></section>`).join("");
    SETUP_STEPS.forEach((step) => paintSetupPanel(step.id));
    showSetupStep(state.setup.step);
}

function paintSetupPanel(id) {
    const panel = document.querySelector(`[data-setup-panel="${id}"]`);
    if (!panel) return;
    const html = {
        welcome: setupWelcomeHtml, folders: setupFoldersHtml, sources: setupSourcesHtml,
        arr: setupArrHtml, players: setupPlayersHtml, finish: () => `<p class="muted">Loading the summary…</p>`,
    }[id]();
    panel.innerHTML = html;
    if (id === "folders") checkSetupFolders();
    if (id === "sources" && typeof loadTrakt === "function") loadTrakt();
}

function showSetupStep(index) {
    const setup = state.setup;
    if (!setup) return;
    const at = Math.max(0, Math.min(SETUP_STEPS.length - 1, Number(index) || 0));
    setup.step = at;
    setup.visited.add(at);
    document.querySelectorAll("[data-setup-panel]").forEach((panel) => {
        panel.classList.toggle("hidden", Number(panel.dataset.setupIndex) !== at);
    });
    paintSetupProgress();
    const id = SETUP_STEPS[at].id;
    if (id === "finish") paintSetupFinish();
    const back = document.getElementById("setup-back");
    const skip = document.getElementById("setup-skip");
    const next = document.getElementById("setup-next");
    if (back) back.disabled = at === 0;
    if (skip) skip.classList.toggle("hidden", at === 0 || id === "finish");
    if (next) next.textContent = id === "welcome" ? "Start" : id === "finish" ? "Finish" : "Save and continue";
    setSetupStatus("");
    const body = document.getElementById("setup-body");
    if (body) body.scrollTop = 0;
}

function paintSetupProgress() {
    const bar = document.getElementById("setup-progress");
    if (!bar || !state.setup) return;
    const at = state.setup.step;
    const fill = Math.round((at / (SETUP_STEPS.length - 1)) * 100);
    bar.innerHTML = `<div class="setup-track" aria-hidden="true"><span style="width:${fill}%"></span></div>
        <ol class="setup-steps">${SETUP_STEPS.map((step, index) => {
            // A tick means the step was saved; a step that was only looked at or skipped keeps its number.
            const saved = state.setup.saved.has(index);
            const stateClass = index === at ? "is-current" : saved ? "is-done" : state.setup.visited.has(index) ? "is-seen" : "";
            return `<li class="${stateClass}"><button type="button" class="setup-dot" data-action="setup-goto" data-step="${index}" ${index === at ? `aria-current="step"` : ""} title="${escapeHtml(step.title)}">
                <span class="setup-dot-number">${saved && index !== at ? "✓" : index + 1}</span><span class="setup-dot-label">${escapeHtml(step.short)}</span></button></li>`;
        }).join("")}</ol>
        <p class="setup-step-count">Step ${at + 1} of ${SETUP_STEPS.length}: ${escapeHtml(SETUP_STEPS[at].title)}</p>`;
}

function setSetupStatus(message, kind) {
    const line = document.getElementById("setup-status");
    if (!line) return;
    line.textContent = message || "";
    line.className = `settings-status ${kind || ""}`.trim();
}

function setupStepHead(id, title, text) {
    return `<div class="setup-head"><h3 id="setup-head-${id}">${escapeHtml(title)}</h3><p class="muted">${text}</p></div>`;
}

// Welcome

function setupWelcomeHtml() {
    const items = [
        ["Library folders", "Tell Curator where your music, movies, TV shows and music videos are, and check that it can read them."],
        ["Metadata and artwork", "Add the free keys for TMDB, Fanart.tv and the other sources, and test each one."],
        ["Download apps", "Connect Radarr, Sonarr, Lidarr and Bazarr, map their paths, and copy the webhook address."],
        ["Players", "Connect Kodi, Plex, Emby, Jellyfin and Navidrome so they update after Curator changes something."],
        ["First scans", "See what is set up and choose which libraries to scan."],
    ];
    return `<div class="setup-hero">
            <img class="setup-hero-logo" src="/static/logo.svg" alt="">
            <div>
                <h3 id="setup-head-welcome">Let's set up Curator</h3>
                <p class="muted">${state.setup && state.setup.auto ? "This looks like a new install. " : ""}A few short steps take you from an empty library to your first scan.</p>
            </div>
        </div>
        <ol class="setup-overview">${items.map(([title, text]) => `<li><strong>${escapeHtml(title)}</strong><span class="muted">${escapeHtml(text)}</span></li>`).join("")}</ol>
        <div class="setup-callout">
            <p><strong>Save and continue</strong> saves a step. <strong>Skip</strong> leaves it as it is. Every step is optional, and everything here is also under Settings.</p>
            <p class="muted">Keys and passwords are stored like the Settings window stores them: a saved one shows as ••••••••, and a blank box keeps it. Run this wizard again any time from Settings, About.</p>
        </div>`;
}

// Step 1: library folders

function setupGlyph(media) {
    if (SETUP_MEDIA_GLYPH[media]) return `<span class="media-glyph">${SETUP_MEDIA_GLYPH[media]}</span>`;
    return typeof mediaGlyph === "function" ? mediaGlyph(media) : "";
}

function setupFolderOwner(path) {
    const value = normalizeClientPath(path);
    for (const [media] of SETUP_MEDIA) {
        for (const other of state.setup.folders[media] || []) {
            const known = normalizeClientPath(other);
            if (known === value || value.startsWith(`${known}/`) || known.startsWith(`${value}/`)) return [media, known];
        }
    }
    return null;
}

function setupFoldersHtml() {
    const setup = state.setup;
    const used = SETUP_MEDIA.flatMap(([media]) => setup.folders[media] || []).map(normalizeClientPath);
    const offers = libraryMounts(state.settings || {}, setup.mounts || [])
        .filter((mount) => !used.some((path) => path === normalizeClientPath(mount.path) || path.startsWith(`${normalizeClientPath(mount.path)}/`)));
    const labels = Object.fromEntries(SETUP_MEDIA.map(([media, label]) => [media, label]));
    const suggestions = offers.length
        ? `<div class="setup-mounts"><span class="muted">Volumes mounted in the container:</span>${offers.map((mount) => {
            const media = guessFolderType(mount.path);
            return `<button type="button" class="btn-ghost setup-chip" data-action="setup-folder-add" data-path="${escapeHtml(mount.path)}" data-media="${media}" title="Add ${escapeHtml(mount.path)} as a ${escapeHtml(labels[media].toLowerCase())} folder">+ <span class="mono">${escapeHtml(mount.path)}</span> as ${escapeHtml(labels[media])}</button>`;
        }).join("")}</div>`
        : (setup.mounts || []).length ? "" : `<p class="settings-warning">No volumes were found in the container. Add your media folders as volumes in docker-compose, recreate the container, then come back here.</p>`;
    const cards = SETUP_MEDIA.map(([media, label, , hint]) => {
        const list = setup.folders[media] || [];
        const rows = list.length
            ? list.map((path) => setupFolderRow(media, path)).join("")
            : `<p class="muted setup-empty">No ${escapeHtml(label.toLowerCase())} folder yet.</p>`;
        return `<div class="setup-card" data-setup-media="${media}">
            <div class="setup-card-head">${setupGlyph(media)}<h4>${escapeHtml(label)}</h4><span class="setup-count">${list.length || ""}</span></div>
            <p class="muted setup-hint">${escapeHtml(hint)}</p>
            <div class="setup-folder-list">${rows}</div>
            <div class="setup-folder-add path-field">
                <input type="text" class="mono" data-setup-folder-input="${media}" placeholder="/${media === "tv" ? "tv" : media}" spellcheck="false" aria-label="${escapeHtml(label)} folder inside the container">
                <button type="button" class="btn-ghost" data-action="setup-folder-browse" data-media="${media}">Browse</button>
                <button type="button" class="btn-ghost" data-action="setup-folder-add" data-media="${media}">Add</button>
            </div>
        </div>`;
    }).join("");
    return `${setupStepHead("folders", "Library folders", "Folders are paths inside Curator's container, the right-hand side of a volume in docker-compose. Each folder has one media type, and a folder cannot sit inside a folder of another type. Curator needs to read every folder, and to write .nfo files and artwork it needs write access too.")}
        ${suggestions}
        <div class="setup-grid">${cards}</div>
        <p class="setup-actions"><button type="button" class="btn-ghost" data-action="setup-folders-check">Check folders again</button></p>`;
}

function setupFolderRow(media, path) {
    const check = state.setup.checks[`${media}|${path}`];
    let badge = `<span class="setup-badge is-wait">Checking…</span>`;
    let lines = "";
    if (check) {
        const cls = !check.ok ? "is-bad" : check.writable ? "is-ok" : "is-warn";
        const text = !check.ok ? (check.exists ? "Cannot use" : "Not found") : check.writable ? "Read and write" : "Read only";
        badge = `<span class="setup-badge ${cls}">${escapeHtml(text)}</span>`;
        lines = [...(check.problems || []).map((line) => `<p class="setup-line is-bad">${escapeHtml(line)}</p>`),
            ...(check.notes || []).map((line) => `<p class="setup-line">${escapeHtml(line)}</p>`)].join("");
    }
    const kind = (state.setup.kinds || {})[path] === "artist" ? "artist" : "artists";
    const kindSelect = media === "music"
        ? `<select data-setup-kind="${escapeHtml(path)}" aria-label="What ${escapeHtml(path)} contains" title="What this folder contains">
            <option value="artists" ${kind === "artists" ? "selected" : ""}>Many artists</option>
            <option value="artist" ${kind === "artist" ? "selected" : ""}>One artist</option>
        </select>`
        : "";
    return `<div class="setup-folder" data-setup-path="${escapeHtml(path)}">
        <div class="setup-folder-line">
            <span class="mono setup-path" title="${escapeHtml(path)}">${escapeHtml(path)}</span>
            ${badge}
            ${kindSelect}
            <button type="button" class="btn-ghost btn-remove" data-action="setup-folder-remove" data-media="${media}" data-path="${escapeHtml(path)}" aria-label="Remove ${escapeHtml(path)}">Remove</button>
        </div>
        ${lines}
    </div>`;
}

function repaintSetupFolders() {
    const panel = document.querySelector(`[data-setup-panel="folders"]`);
    if (!panel || !state.setup) return;
    document.querySelectorAll("[data-setup-kind]").forEach((select) => { state.setup.kinds[select.dataset.setupKind] = select.value; });
    const typed = {};
    document.querySelectorAll("[data-setup-folder-input]").forEach((input) => { typed[input.dataset.setupFolderInput] = input.value; });
    panel.innerHTML = setupFoldersHtml();
    Object.entries(typed).forEach(([media, value]) => {
        const input = panel.querySelector(`[data-setup-folder-input="${media}"]`);
        if (input) input.value = value;
    });
}

function setupAddFolder(path, media, kind) {
    const setup = state.setup;
    if (!setup) return;
    const type = SETUP_MEDIA.some(([key]) => key === media) ? media : "music";
    const value = normalizeClientPath(path);
    const label = SETUP_MEDIA.find(([key]) => key === type)[1].toLowerCase();
    if (!value || !value.startsWith("/")) {
        notify("Use the path inside the container. It starts with /, for example /movies.", "warning");
        return;
    }
    const own = ownFolderClash(value);
    if (own) {
        notify(`${value} overlaps ${own}, Curator's own folder for settings, cache or artwork. Pick a library folder outside it.`, "warning");
        return;
    }
    const clash = setupFolderOwner(value);
    if (clash && clash[1] === value) {
        notify(`${value} is already a ${SETUP_MEDIA.find(([key]) => key === clash[0])[1].toLowerCase()} folder.`, "info");
        return;
    }
    if (clash && clash[0] !== type) {
        notify(`${value} overlaps the ${SETUP_MEDIA.find(([key]) => key === clash[0])[1].toLowerCase()} folder ${clash[1]}. Each folder can have only one media type.`, "warning");
        return;
    }
    setup.folders[type] = [...(setup.folders[type] || []), value];
    if (type === "music") setup.kinds[value] = kind === "artist" ? "artist" : "artists";
    setup.dirty.add("folders");
    const input = document.querySelector(`[data-setup-folder-input="${type}"]`);
    if (input) input.value = "";
    repaintSetupFolders();
    checkSetupFolders([type]);
    setSetupStatus(`Added ${value} as a ${label} folder. Save and continue keeps it.`, "info");
}

function setupRemoveFolder(media, path) {
    const setup = state.setup;
    if (!setup) return;
    setup.folders[media] = (setup.folders[media] || []).filter((item) => item !== path);
    delete setup.checks[`${media}|${path}`];
    setup.dirty.add("folders");
    repaintSetupFolders();
}

function browseSetupFolder(media) {
    state.setupPickMedia = media;
    return openPathBrowser("setup-folder");
}

async function checkSetupFolders(only) {
    const setup = state.setup;
    if (!setup) return;
    const kinds = (only && only.length ? only : SETUP_MEDIA.map(([media]) => media)).filter((media) => (setup.folders[media] || []).length);
    await Promise.all(kinds.map(async (media) => {
        try {
            const data = await api("/api/v1/setup/check-folders", { method: "POST", body: { media, paths: setup.folders[media] } });
            (data.results || []).forEach((result, index) => {
                const asked = setup.folders[media][index];
                if (asked) setup.checks[`${media}|${asked}`] = result;
            });
        } catch (error) {
            (setup.folders[media] || []).forEach((path) => {
                setup.checks[`${media}|${path}`] = { ok: false, problems: [error.message || "The check failed."], notes: [] };
            });
        }
    }));
    if (state.setup === setup) repaintSetupFolders();
}

function readSetupFolders(cfg) {
    const setup = state.setup;
    document.querySelectorAll("[data-setup-kind]").forEach((select) => { setup.kinds[select.dataset.setupKind] = select.value; });
    SETUP_MEDIA.forEach(([media, , key]) => { cfg[key] = [...(setup.folders[media] || [])]; });
    cfg.music_path_kinds = {};
    (setup.folders.music || []).forEach((path) => { cfg.music_path_kinds[path] = setup.kinds[path] === "artist" ? "artist" : "artists"; });
    cfg.music_path_roles = Object.fromEntries((setup.folders.music || []).map((path) => [path, "library"]));
}

// Step 2: metadata and artwork sources

function setupKeyStatus(field, env) {
    const status = (((state.settings || {}).key_status || {})[field]) || "";
    if (status === "saved") return `<span class="setup-badge is-ok">Saved</span>`;
    if (status === "environment") return `<span class="setup-badge is-ok" title="From ${escapeHtml(env)} in docker-compose">From docker-compose</span>`;
    return `<span class="setup-badge">Not set</span>`;
}

function setupProviderIcon(name) {
    return typeof PROVIDER_ICONS !== "undefined" && PROVIDER_ICONS[name] ? providerIcon(name) : "";
}

function setupKeyCard(service) {
    const spec = SETUP_KEYS[service];
    const id = `setup-key-${service}`;
    const saved = ((state.settings || {}).key_status || {})[spec.field];
    const secret = service === "lastfm" ? `<label class="setup-field">Shared secret <span class="muted">(optional)</span>
            <input id="setup-key-lastfm-secret" type="password" autocomplete="new-password" placeholder="${((state.settings || {}).key_status || {}).lastfm_secret ? "•••••••• (saved)" : "Paste the shared secret"}">
        </label>` : "";
    return `<div class="setup-card">
        <div class="setup-card-head">${setupProviderIcon(spec.icon || service)}<h4>${escapeHtml(spec.label)}</h4><span class="setup-tag">${escapeHtml(spec.badge)}</span>${setupKeyStatus(spec.field, spec.env)}</div>
        <p class="muted setup-hint">${escapeHtml(spec.note)} <a href="${spec.link}" target="_blank" rel="noopener">Get a key</a></p>
        <div class="key-row">
            <label class="setup-field">${escapeHtml(spec.label)} ${escapeHtml(spec.what)}
                <input id="${id}" type="password" autocomplete="new-password" data-setup-key="${spec.field}" placeholder="${saved ? "•••••••• (blank keeps it)" : "Paste the key"}">
            </label>
            <button type="button" class="btn-ghost key-test" data-action="test-key" data-service="${service}" data-input="${id}" data-field="${spec.field}" data-label="${escapeHtml(spec.label)}">Test</button>
        </div>
        ${secret}
    </div>`;
}

function setupKeylessCard(service, label, note, extra) {
    return `<div class="setup-card">
        <div class="setup-card-head">${setupProviderIcon(service)}<h4>${escapeHtml(label)}</h4><span class="setup-tag">No key needed</span></div>
        <p class="muted setup-hint">${escapeHtml(note)}</p>
        ${extra || ""}
        <p class="setup-actions"><button type="button" class="btn-ghost key-test" data-action="test-key" data-service="${service}" data-input="" data-label="${escapeHtml(label)}">Test</button></p>
    </div>`;
}

function setupSourcesHtml() {
    const cfg = state.settings || {};
    const contact = `<label class="setup-field">Contact for MusicBrainz <span class="muted">(an email address or web page)</span>
            <input id="setup-mb-contact" type="text" spellcheck="false" value="${escapeHtml(cfg.musicbrainz_contact || "")}" placeholder="you@example.com">
        </label>`;
    return `${setupStepHead("sources", "Metadata and artwork", "Curator looks titles up in these services. Paste a key and press Test: the test uses the typed key, or the saved one when the box is blank. Keys set in docker-compose are used when nothing is saved here.")}
        <h4 class="setup-group">Movies and TV</h4>
        <div class="setup-grid">${["tmdb", "tvdb", "omdb", "fanart"].map(setupKeyCard).join("")}</div>
        <h4 class="setup-group">Music</h4>
        <div class="setup-grid">
            ${setupKeylessCard("musicbrainz", "MusicBrainz", "Album and artist identities, track lists and release dates. MusicBrainz asks every app for a way to contact its user.", contact)}
            ${setupKeylessCard("theaudiodb", "TheAudioDB", "Artist biographies, album reviews and artwork. The free service needs no key.")}
            ${setupKeyCard("lastfm")}
            ${setupKeyCard("acoustid")}
        </div>
        <h4 class="setup-group">Trakt</h4>
        <div class="setup-card setup-card-wide">
            <div class="setup-card-head">${setupProviderIcon("trakt")}<h4>Trakt</h4><span class="setup-tag">Optional</span></div>
            <p class="muted setup-hint">Syncs watched state and collections, and adds Trakt ratings. Create an app at <a href="https://trakt.tv/oauth/applications" target="_blank" rel="noopener">trakt.tv/oauth/applications</a> (any redirect URI, for example urn:ietf:wg:oauth:2.0:oob), paste its Client ID, press Save Trakt app, then Connect with Trakt and enter the code at trakt.tv/activate. This part saves by itself.</p>
            <div id="trakt-box"><p class="muted">Loading…</p></div>
        </div>`;
}

function readSetupSources(cfg) {
    document.querySelectorAll("[data-setup-key]").forEach((input) => {
        if (input.value.trim()) cfg[input.dataset.setupKey] = input.value.trim();
    });
    const secret = document.getElementById("setup-key-lastfm-secret");
    if (secret && secret.value.trim()) cfg.lastfm_secret = secret.value.trim();
    const contact = document.getElementById("setup-mb-contact");
    if (contact) cfg.musicbrainz_contact = contact.value.trim();
}

// Step 3: download apps

function setupWebhookUrls() {
    const key = state.setup.cmmKey || "YOUR_KEY";
    const query = `/api/v1/webhooks/arr?apikey=${encodeURIComponent(key)}`;
    return {
        webhook: `${location.protocol}//${location.host}${query}`,
        apprise: `${location.protocol === "https:" ? "jsons" : "json"}://${location.host}${query}`,
    };
}

function setupCopyField(value, label) {
    return `<span class="path-field setup-copy">
        <input class="mono" readonly spellcheck="false" value="${escapeHtml(value)}" aria-label="${escapeHtml(label)}">
        <button type="button" class="icon-btn" data-action="setup-copy" data-copy="${escapeHtml(value)}" title="Copy" aria-label="Copy ${escapeHtml(label)}">${typeof clipboardIcon === "function" ? clipboardIcon() : "Copy"}</button>
    </span>`;
}

function setupMapRows(source) {
    const rows = ((state.settings || {}).automation || {}).path_mappings || [];
    return rows.filter((row) => row.source === source);
}

function setupArrMapRow(app, row) {
    const item = row || {};
    const label = SETUP_ARR[app].label;
    return `<div class="setup-map auto-row" data-auto-map data-setup-map="${app}">
        <input data-map-remote value="${escapeHtml(item.remote || "")}" placeholder="Path in ${escapeHtml(label)}, e.g. /data/media/${app === "sonarr" ? "tv" : app === "lidarr" ? "music" : "movies"}" spellcheck="false" aria-label="Path in ${escapeHtml(label)}">
        <span class="setup-arrow" aria-hidden="true">→</span>
        <span class="path-field"><input data-map-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator, e.g. /${app === "sonarr" ? "tv" : app === "lidarr" ? "music" : "movies"}" spellcheck="false" aria-label="Path in Curator"><button type="button" class="btn-ghost" data-action="browse-map-local">Browse</button></span>
        <button type="button" class="btn-ghost btn-remove" data-action="setup-row-remove" aria-label="Remove this mapping">Remove</button>
        <div class="setup-map-result" data-setup-map-result></div>
    </div>`;
}

function setupArrCard(app) {
    const spec = SETUP_ARR[app];
    const cfg = state.settings || {};
    const saved = (cfg.key_status || {})[`${app}_api_key`];
    const urls = setupWebhookUrls();
    const hook = app === "bazarr"
        ? `<p class="setup-sub">Bazarr has no webhook. In Bazarr open Settings, Notifications, add an Apprise notification with this address:</p>${setupCopyField(urls.apprise, "Bazarr Apprise address")}`
        : `<p class="setup-sub">In ${escapeHtml(spec.label)} open Settings, Connect, add a Webhook, paste the address above, set the method to POST and tick On Import, On Upgrade, On Rename and the delete triggers.</p>`;
    // An app with no address yet starts ticked (Lidarr is off by default); a saved app shows its saved switch.
    const enabled = String(cfg[`${app}_url`] || "").trim() && Object.prototype.hasOwnProperty.call(cfg, `${app}_enabled`)
        ? cfg[`${app}_enabled`] !== false : true;
    return `<div class="setup-card setup-card-wide" data-setup-arr="${app}">
        <div class="setup-card-head">${setupProviderIcon(app)}<h4>${escapeHtml(spec.label)}</h4><span class="setup-tag">${escapeHtml(spec.media)}</span>${saved ? `<span class="setup-badge is-ok">Key saved</span>` : ""}</div>
        <div class="setup-two">
            <label class="setup-field">Address <input id="setup-${app}-url" type="text" spellcheck="false" value="${escapeHtml(cfg[`${app}_url`] || "")}" placeholder="http://${app}:${spec.port}"></label>
            <label class="setup-field">API key <input id="setup-${app}-key" type="password" autocomplete="new-password" placeholder="${saved ? "•••••••• (blank keeps it)" : "Paste the API key"}"></label>
        </div>
        <p class="muted setup-hint">The key is under ${escapeHtml(spec.where)}.</p>
        <label class="choice"><input type="checkbox" id="setup-${app}-enabled" ${enabled ? "checked" : ""}> Use ${escapeHtml(spec.label)} once an address is saved</label>
        <div class="arr-test"><button type="button" class="btn-ghost" data-action="setup-test-arr" data-app="${app}">Test connection</button><p class="muted" data-arr-test>${escapeHtml(typeof arrVersionNote === "function" ? arrVersionNote(`auto-${app}-test`) : "")}</p></div>
        ${hook}
        <h5 class="setup-sub-head">Path mapping</h5>
        <p class="muted setup-hint">Only needed when ${escapeHtml(spec.label)} sees the library under another path than Curator, for example /data/media/movies in ${escapeHtml(spec.label)} and /movies here. Leave it empty when both use the same path.</p>
        <div class="setup-maps" data-setup-maps="${app}">${setupMapRows(app).map((row) => setupArrMapRow(app, row)).join("")}</div>
        <p class="setup-actions">
            <button type="button" class="btn-ghost" data-action="setup-map-add" data-app="${app}">Add mapping</button>
            <button type="button" class="btn-ghost" data-action="setup-test-maps" data-app="${app}" data-step="arr" title="Saves this step, then checks every mapping">Save and test paths</button>
        </p>
    </div>`;
}

function setupArrHtml() {
    const urls = setupWebhookUrls();
    const anyRows = setupMapRows("any").length;
    const keyLine = state.setup.cmmKey
        ? `<p class="muted setup-hint">The address holds CMM_API_KEY from docker-compose. Webhooks without it are refused.</p>`
        : `<p class="settings-warning">CMM_API_KEY is not set in docker-compose, so webhooks are refused. Add CMM_API_KEY to the environment, recreate the container, and replace YOUR_KEY in the address with it.</p>`;
    return `${setupStepHead("arr", "Download apps", "Radarr, Sonarr and Lidarr tell Curator when they import something, so Curator scans just that folder. Curator can also ask them to search for missing movies, episodes and albums, and Bazarr for missing subtitles. Leave an app's address empty to skip it.")}
        <div class="setup-card setup-card-wide setup-webhook">
            <div class="setup-card-head"><h4>Webhook address for Radarr, Sonarr and Lidarr</h4></div>
            ${setupCopyField(urls.webhook, "Webhook address")}
            ${keyLine}
        </div>
        ${anyRows ? `<p class="muted">${anyRows} mapping ${anyRows === 1 ? "row" : "rows"} for Any app ${anyRows === 1 ? "is" : "are"} kept as ${anyRows === 1 ? "it is" : "they are"}. Edit ${anyRows === 1 ? "it" : "them"} under Settings, General, Remote path mappings.</p>` : ""}
        <div class="setup-stack">${Object.keys(SETUP_ARR).map(setupArrCard).join("")}</div>`;
}

function readSetupArr(cfg) {
    const mappings = [];
    Object.keys(SETUP_ARR).forEach((app) => {
        const url = document.getElementById(`setup-${app}-url`);
        const key = document.getElementById(`setup-${app}-key`);
        const enabled = document.getElementById(`setup-${app}-enabled`);
        if (url) cfg[`${app}_url`] = url.value.trim();
        if (key && key.value.trim()) cfg[`${app}_api_key`] = key.value.trim();
        if (url && url.value.trim() && enabled) cfg[`${app}_enabled`] = enabled.checked;
        document.querySelectorAll(`[data-setup-map="${app}"]`).forEach((row) => {
            const remote = row.querySelector("[data-map-remote]").value.trim();
            const local = row.querySelector("[data-map-local]").value.trim();
            if (remote && local) mappings.push({ source: app, remote, local });
        });
    });
    const automation = cfg.automation || {};
    const kept = (automation.path_mappings || []).filter((row) => !SETUP_ARR[row.source]);
    cfg.automation = { ...automation, path_mappings: [...kept, ...mappings] };
}

// Step 4: players

function setupPlayerMapRow(player, row) {
    const spec = SETUP_PLAYERS[player];
    const item = row || {};
    return `<div class="setup-map auto-row" data-setup-player-map="${player}">
        <span class="path-field"><input data-map-local value="${escapeHtml(item.local || "")}" placeholder="Path in Curator, e.g. /movies" spellcheck="false" aria-label="Path in Curator"><button type="button" class="btn-ghost" data-action="setup-browse-local">Browse</button></span>
        <span class="setup-arrow" aria-hidden="true">→</span>
        <input data-map-remote value="${escapeHtml(item[spec.remoteKey] || "")}" placeholder="Path in ${escapeHtml(spec.label)}, e.g. ${player === "kodi" ? "smb://nas/movies" : "/data/movies"}" spellcheck="false" aria-label="Path in ${escapeHtml(spec.label)}">
        <button type="button" class="btn-ghost btn-remove" data-action="setup-row-remove" aria-label="Remove this path">Remove</button>
        <div class="setup-map-result" data-setup-map-result></div>
    </div>`;
}

function setupPlayerCard(player) {
    const spec = SETUP_PLAYERS[player];
    const cfg = state.settings || {};
    const n = cfg.notify || {};
    const saved = (cfg.key_status || {})[spec.secret];
    const hasHost = String(n[spec.host] || "").trim();
    const video = hasHost ? libraryOn(n, `${player}_video_enabled`, player === "kodi" ? "kodi_library_enabled" : `${player}_enabled`) : true;
    const music = hasHost ? libraryOn(n, `${player}_music_enabled`, player === "kodi" ? "kodi_library_enabled" : `${player}_enabled`) : true;
    const user = spec.user ? `<label class="setup-field">User name <input id="setup-${player}-user" type="text" spellcheck="false" value="${escapeHtml(n[spec.user] || "")}" placeholder="kodi"></label>` : "";
    return `<div class="setup-card setup-card-wide" data-setup-player="${player}">
        <div class="setup-card-head">${setupProviderIcon(player)}<h4>${escapeHtml(spec.label)}</h4>${saved ? `<span class="setup-badge is-ok">${escapeHtml(spec.secretLabel)} saved</span>` : ""}</div>
        <div class="setup-two">
            <label class="setup-field">Address <input id="setup-${player}-url" type="text" spellcheck="false" value="${escapeHtml(n[spec.host] || "")}" placeholder="${escapeHtml(spec.placeholder)}"></label>
            ${user}
            <label class="setup-field">${escapeHtml(spec.secretLabel)} <input id="setup-${player}-secret" type="password" autocomplete="new-password" placeholder="${saved ? "•••••••• (blank keeps it)" : `Paste the ${escapeHtml(spec.secretLabel.toLowerCase())}`}"></label>
        </div>
        <p class="muted setup-hint">${escapeHtml(spec.where)}</p>
        <div class="setup-checks">
            <label class="choice"><input type="checkbox" id="setup-${player}-video" ${video ? "checked" : ""}> Update the ${escapeHtml(spec.label)} video library after changes</label>
            <label class="choice"><input type="checkbox" id="setup-${player}-music" ${music ? "checked" : ""}> Update the ${escapeHtml(spec.label)} music library after changes</label>
        </div>
        <div class="arr-test"><button type="button" class="btn-ghost" data-action="setup-test-player" data-player="${player}">Test connection</button><p class="muted" data-setup-test-note></p></div>
        <h5 class="setup-sub-head">Path mapping</h5>
        <p class="muted setup-hint">Needed when ${escapeHtml(spec.label)} reaches the files by another path${player === "kodi" ? ", such as smb://nas/movies" : ""}. With paths, only the changed folders are scanned; without them ${escapeHtml(spec.label)} scans its whole library.</p>
        <div class="setup-maps" data-setup-player-maps="${player}">${(n[spec.paths] || []).map((row) => setupPlayerMapRow(player, row)).join("")}</div>
        <p class="setup-actions">
            <button type="button" class="btn-ghost" data-action="setup-player-map-add" data-player="${player}">Add path</button>
            <button type="button" class="btn-ghost" data-action="setup-test-maps" data-app="${player}" data-step="players" title="Saves this step, then checks every path">Save and test paths</button>
        </p>
    </div>`;
}

function setupNavidromeCard() {
    const cfg = state.settings || {};
    const saved = (cfg.key_status || {}).webhook_navidrome_key;
    const has = String(cfg.webhook_navidrome || "").trim();
    const on = has ? cfg.webhook_navidrome_enabled !== false : true;
    return `<div class="setup-card setup-card-wide" data-setup-player="navidrome">
        <div class="setup-card-head">${setupProviderIcon("navidrome")}<h4>Navidrome</h4><span class="setup-tag">music</span>${saved ? `<span class="setup-badge is-ok">Password saved</span>` : ""}</div>
        <div class="setup-two">
            <label class="setup-field">Address <input id="setup-navidrome-url" type="text" spellcheck="false" value="${escapeHtml(cfg.webhook_navidrome || "")}" placeholder="http://navidrome:4533"></label>
            <label class="setup-field">User name <input id="setup-navidrome-user" type="text" spellcheck="false" value="${escapeHtml(cfg.webhook_navidrome_user || "")}" placeholder="Navidrome user name"></label>
            <label class="setup-field">Password <input id="setup-navidrome-secret" type="password" autocomplete="new-password" placeholder="${saved ? "•••••••• (blank keeps it)" : "The account password"}"></label>
        </div>
        <p class="muted setup-hint">Navidrome has no API key. Curator asks it to scan with the user name and password, and it always scans its whole library, so it has no paths.</p>
        <label class="choice"><input type="checkbox" id="setup-navidrome-music" ${on ? "checked" : ""}> Update the Navidrome music library after changes</label>
        <div class="arr-test"><button type="button" class="btn-ghost" data-action="setup-test-player" data-player="navidrome">Test scan</button><p class="muted" data-setup-test-note></p></div>
    </div>`;
}

function setupPlayersHtml() {
    return `${setupStepHead("players", "Players", "After Curator changes something (a new movie, new artwork, a rename) it can tell your players to update just what changed. Leave a player's address empty to skip it. Tick the libraries each player should update.")}
        <div class="setup-stack">${Object.keys(SETUP_PLAYERS).map(setupPlayerCard).join("")}${setupNavidromeCard()}</div>`;
}

function readSetupPlayers(cfg) {
    const value = (id) => ((document.getElementById(id) || {}).value || "").trim();
    const checked = (id) => !!(document.getElementById(id) || {}).checked;
    const notifyCfg = { ...(cfg.notify || {}) };
    Object.entries(SETUP_PLAYERS).forEach(([player, spec]) => {
        const host = value(`setup-${player}-url`);
        notifyCfg[spec.host] = host;
        if (spec.user) notifyCfg[spec.user] = value(`setup-${player}-user`);
        const secret = value(`setup-${player}-secret`);
        if (secret) cfg[spec.secret] = secret;
        if (host) {
            const video = checked(`setup-${player}-video`);
            const music = checked(`setup-${player}-music`);
            notifyCfg[`${player}_video_enabled`] = video;
            notifyCfg[`${player}_music_enabled`] = music;
            notifyCfg[player === "kodi" ? "kodi_library_enabled" : `${player}_enabled`] = video || music;
            if (spec.on) notifyCfg[spec.on] = true;
        }
        notifyCfg[spec.paths] = [...document.querySelectorAll(`[data-setup-player-map="${player}"]`)].map((row) => ({
            local: row.querySelector("[data-map-local]").value.trim(),
            [spec.remoteKey]: row.querySelector("[data-map-remote]").value.trim(),
        })).filter((row) => row.local && row[spec.remoteKey]);
    });
    const navidrome = value("setup-navidrome-url");
    cfg.webhook_navidrome = navidrome;
    cfg.webhook_navidrome_user = value("setup-navidrome-user");
    const password = value("setup-navidrome-secret");
    if (password) cfg.webhook_navidrome_key = password;
    if (navidrome) {
        cfg.webhook_navidrome_enabled = checked("setup-navidrome-music");
        notifyCfg.navidrome_on = true;
    }
    cfg.notify = notifyCfg;
}

// Tests

async function testSetupArr(button) {
    const app = button.dataset.app;
    const body = {
        url: ((document.getElementById(`setup-${app}-url`) || {}).value || "").trim(),
        key: ((document.getElementById(`setup-${app}-key`) || {}).value || "").trim(),
    };
    return testArrConnection(`/api/v1/${app}/test`, body, button);
}

async function testSetupPlayer(button) {
    const player = button.dataset.player;
    const target = player === "navidrome" ? "navidrome" : SETUP_PLAYERS[player].target;
    const value = (id) => ((document.getElementById(id) || {}).value || "").trim();
    const note = button.parentElement ? button.parentElement.querySelector("[data-setup-test-note]") : null;
    beginConnectionTest(button);
    try {
        const data = await api("/api/v1/notify/test", {
            method: "POST",
            body: { target, url: value(`setup-${player}-url`), user: value(`setup-${player}-user`), secret: value(`setup-${player}-secret`) },
        });
        paintConnectionTest(button, true);
        if (note) {
            note.textContent = data.message || "Connected.";
            note.className = "key-set";
        }
    } catch (error) {
        paintConnectionTest(button, false);
        if (note) {
            note.textContent = (error && error.message) || "The connection test failed.";
            note.className = "setup-line is-bad";
        }
    }
}

async function testSetupMappings(button) {
    const app = button.dataset.app;
    const step = button.dataset.step;
    const selector = SETUP_ARR[app] ? `[data-setup-map="${app}"]` : `[data-setup-player-map="${app}"]`;
    const rows = [...document.querySelectorAll(selector)];
    if (!rows.length) {
        notify("Add a mapping row first.", "info");
        return;
    }
    if (!(await saveSetupStep(step, { quiet: true }))) return;
    rows.forEach((row) => { row.querySelector("[data-setup-map-result]").innerHTML = `<p class="setup-line">Checking…</p>`; });
    let data;
    try {
        data = await api("/api/v1/setup/check-mappings", {
            method: "POST",
            body: { app, rows: rows.map((row) => ({ remote: row.querySelector("[data-map-remote]").value, local: row.querySelector("[data-map-local]").value })) },
        });
    } catch (error) {
        rows.forEach((row) => { row.querySelector("[data-setup-map-result]").innerHTML = `<p class="setup-line is-bad">${escapeHtml(error.message || "The test failed.")}</p>`; });
        return;
    }
    const results = data.results || [];
    let index = 0;
    rows.forEach((row) => {
        const box = row.querySelector("[data-setup-map-result]");
        const remote = row.querySelector("[data-map-remote]").value.trim();
        const local = row.querySelector("[data-map-local]").value.trim();
        if (!remote && !local) {
            box.innerHTML = "";
            return;
        }
        const result = results[index] || {};
        index += 1;
        box.innerHTML = setupMappingResultHtml(result, data.message);
    });
    const bad = results.filter((row) => !row.ok).length;
    notify(bad ? `${bad} of ${results.length} ${results.length === 1 ? "path does" : "paths do"} not work yet.` : "Every path checks out.", bad ? "warning" : "success");
}

function setupMappingResultHtml(result, message) {
    const lines = [];
    lines.push(`<p class="setup-line ${result.ok ? "is-ok" : "is-bad"}">${result.ok ? "✓ The Curator path exists." : "✕ This mapping does not work yet."}</p>`);
    (result.problems || []).forEach((line) => lines.push(`<p class="setup-line is-bad">${escapeHtml(line)}</p>`));
    (result.matches || []).forEach((hit) => lines.push(`<p class="setup-line ${hit.exists ? "is-ok" : "is-bad"}"><span class="mono">${escapeHtml(hit.remote)}</span> → <span class="mono">${escapeHtml(hit.local)}</span> ${hit.exists ? "exists here" : "is missing here"}</p>`));
    (result.notes || []).forEach((line) => lines.push(`<p class="setup-line">${escapeHtml(line)}</p>`));
    if (message) lines.push(`<p class="setup-line">${escapeHtml(message)}</p>`);
    return lines.join("");
}

// Saving

const SETUP_READERS = { folders: readSetupFolders, sources: readSetupSources, arr: readSetupArr, players: readSetupPlayers };

async function saveSetupStep(id, options) {
    const reader = SETUP_READERS[id];
    if (!reader || !state.setup) return true;
    const quiet = !!(options && options.quiet);
    setSetupStatus("Saving…", "info");
    try {
        const cfg = await api("/api/settings");
        reader(cfg);
        state.settings = await api("/api/settings", { method: "PUT", body: settingsPutBody(cfg, {}) });
        state.musicPaths = state.settings.music_paths || state.musicPaths;
        state.moviePaths = state.settings.movie_paths || state.moviePaths;
        state.tvPaths = state.settings.tv_paths || state.tvPaths;
        state.setup.dirty.delete(id);
        state.setup.saved.add(SETUP_STEPS.findIndex((step) => step.id === id));
        paintSetupProgress();
        setSetupStatus(quiet ? "Saved." : "", "info");
        return true;
    } catch (error) {
        setSetupStatus(error.message || "This step was not saved.", "error");
        notify(error.message || "This step was not saved.", "error");
        return false;
    }
}

async function setupNext() {
    const setup = state.setup;
    if (!setup || setup.busy) return;
    const id = SETUP_STEPS[setup.step].id;
    if (id === "finish") {
        closeSetupWizard();
        notify("Setup finished. Everything here is also under Settings.", "success");
        return;
    }
    setup.busy = true;
    const next = document.getElementById("setup-next");
    if (next) next.disabled = true;
    try {
        if (!(await saveSetupStep(id))) return;
        setup.saved.add(setup.step);
        // A saved key now shows as saved, and a typed secret leaves its box.
        if (id === "sources" || id === "arr" || id === "players") paintSetupPanel(id);
        showSetupStep(setup.step + 1);
    } finally {
        setup.busy = false;
        if (next) next.disabled = false;
    }
}

function setupMove(index) {
    const setup = state.setup;
    if (!setup) return;
    const id = SETUP_STEPS[setup.step].id;
    if (setup.dirty.has(id) && Number(index) !== setup.step) {
        notify(`${SETUP_STEPS[setup.step].title} has changes that are not saved yet. Go back and press Save and continue to keep them.`, "warning");
    }
    showSetupStep(index);
}

// Step 5: finish

function setupMark(ok, text, detail) {
    return `<li class="${ok ? "is-ok" : "is-off"}"><span class="setup-mark" aria-hidden="true">${ok ? "✓" : "–"}</span><span>${escapeHtml(text)}${detail ? ` <span class="muted">${escapeHtml(detail)}</span>` : ""}</span></li>`;
}

async function paintSetupFinish() {
    const panel = document.querySelector(`[data-setup-panel="finish"]`);
    if (!panel) return;
    let cfg = state.settings || {};
    let trakt = {};
    try {
        [cfg, trakt] = await Promise.all([api("/api/settings"), api("/api/v1/trakt/status").catch(() => ({}))]);
        state.settings = cfg;
    } catch (error) { /* show what is known */ }
    const keys = cfg.key_status || {};
    const n = cfg.notify || {};
    const folders = SETUP_MEDIA.map(([media, label, key]) => {
        const list = cfg[key] || [];
        return setupMark(list.length > 0, label, list.length ? list.join(", ") : "no folder");
    }).join("");
    const sources = [
        ...Object.values(SETUP_KEYS).map((spec) => setupMark(!!keys[spec.field], spec.label, keys[spec.field] === "environment" ? "from docker-compose" : keys[spec.field] ? "key saved" : "no key")),
        setupMark(!!String(cfg.musicbrainz_contact || "").trim(), "MusicBrainz contact", cfg.musicbrainz_contact || "not set"),
        setupMark(!!trakt.connected, "Trakt", trakt.connected ? `connected${trakt.username ? ` as ${trakt.username}` : ""}` : "not connected"),
    ].join("");
    const apps = Object.entries(SETUP_ARR).map(([app, spec]) => {
        const url = String(cfg[`${app}_url`] || "").trim();
        const version = ((cfg.arr_versions || {})[app] || {}).version;
        const on = url && (!Object.prototype.hasOwnProperty.call(cfg, `${app}_enabled`) || cfg[`${app}_enabled`] !== false);
        return setupMark(!!on, spec.label, url ? `${url}${version ? `, version ${version}` : ""}${on ? "" : ", turned off"}` : "not set up");
    }).join("");
    const players = [
        ...Object.entries(SETUP_PLAYERS).map(([player, spec]) => {
            const host = String(n[spec.host] || "").trim();
            const paths = (n[spec.paths] || []).length;
            return setupMark(!!host, spec.label, host ? `${host}${paths ? `, ${paths} path${paths === 1 ? "" : "s"}` : ""}` : "not set up");
        }),
        setupMark(!!String(cfg.webhook_navidrome || "").trim(), "Navidrome", cfg.webhook_navidrome || "not set up"),
    ].join("");
    const scans = SETUP_MEDIA.filter(([, , key]) => (cfg[key] || []).length).map(([media, label]) =>
        `<label class="choice"><input type="checkbox" data-setup-scan="${media}" checked> Scan ${escapeHtml(label.toLowerCase())}</label>`).join("");
    panel.innerHTML = `${setupStepHead("finish", "All set", "Here is what Curator is set up with. Anything marked – can be added later under Settings, or by running this wizard again from Settings, About.")}
        <div class="setup-summary">
            <div class="setup-card"><h4>Library folders</h4><ul class="setup-marks">${folders}</ul></div>
            <div class="setup-card"><h4>Metadata and artwork</h4><ul class="setup-marks">${sources}</ul></div>
            <div class="setup-card"><h4>Download apps</h4><ul class="setup-marks">${apps}</ul></div>
            <div class="setup-card"><h4>Players</h4><ul class="setup-marks">${players}</ul></div>
        </div>
        <div class="setup-card setup-card-wide setup-scan">
            <div class="setup-card-head"><h4>First scans</h4></div>
            ${scans
                ? `<p class="muted setup-hint">An incremental scan reads every folder and looks each title up. Tick the libraries to scan now. They run one after another, and the activity bar at the bottom shows how far each has come.</p>
                   <div class="setup-checks">${scans}</div>
                   <p class="setup-actions"><button type="button" data-action="setup-scan">Start the ticked scans</button></p>`
                : `<p class="muted">No library folder is saved yet, so there is nothing to scan. Go back to Library folders to add one.</p>`}
        </div>`;
}

async function startSetupScans(button) {
    const chosen = [...document.querySelectorAll("[data-setup-scan]")].filter((box) => box.checked).map((box) => box.dataset.setupScan);
    if (!chosen.length) {
        notify("Tick at least one library to scan.", "info");
        return;
    }
    if (button) {
        button.disabled = true;
        button.textContent = "Starting…";
    }
    const started = [];
    const failed = [];
    for (const media of chosen) {
        const label = SETUP_MEDIA.find(([key]) => key === media)[1];
        try {
            if (media === "music") await api("/api/scan", { method: "POST", body: { force: false, mode: "incremental", roots: [], verbose: false } });
            else if (media === "musicvideos") await api("/api/v1/musicvideos/scan", { method: "POST", body: { mode: "incremental", roots: [] } });
            else await api("/api/v1/scan", { method: "POST", body: { media, mode: "incremental", roots: [], verbose: false } });
            started.push(label);
        } catch (error) {
            failed.push(`${label}: ${error.message || "could not start"}`);
        }
    }
    if (started.length) notify(`Scans started or queued: ${started.join(", ")}.`, "success");
    if (failed.length) notify(failed.join(" "), "error");
    if (typeof pollSystem === "function") pollSystem();
    if (button) {
        button.disabled = false;
        button.textContent = started.length ? "Scans started" : "Start the ticked scans";
    }
}

async function copySetupText(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
        else copyPlainText(text);
        notify("Copied.", "info");
    } catch (error) {
        try {
            copyPlainText(text);
            notify("Copied.", "info");
        } catch (again) {
            notify("Could not copy. Select the text and copy it yourself.", "warning");
        }
    }
}

function onSetupAction(name, action) {
    const setup = state.setup;
    if (name === "setup-open") return openSetupWizard({ auto: false });
    if (!setup) return;
    if (name === "setup-close") return closeSetupWizard();
    // Not through runAction: it puts the old label back on the button afterwards, and these buttons change theirs.
    if (name === "setup-next") return setupNext().catch((error) => notify(error.message || "This step was not saved.", "error"));
    if (name === "setup-back") return setupMove(setup.step - 1);
    if (name === "setup-skip") return setupMove(setup.step + 1);
    if (name === "setup-goto") return setupMove(Number(action.dataset.step));
    if (name === "setup-folder-add") {
        const media = action.dataset.media || "music";
        const input = document.querySelector(`[data-setup-folder-input="${media}"]`);
        return setupAddFolder(action.dataset.path || (input ? input.value : ""), media, "artists");
    }
    if (name === "setup-folder-remove") return setupRemoveFolder(action.dataset.media, action.dataset.path);
    if (name === "setup-folder-browse") return runAction(() => browseSetupFolder(action.dataset.media));
    if (name === "setup-folders-check") return runAction(() => checkSetupFolders(), "Checking folders…");
    if (name === "setup-test-arr") return testSetupArr(action);
    if (name === "setup-test-player") return testSetupPlayer(action);
    if (name === "setup-test-maps") return runAction(() => testSetupMappings(action), "Testing paths…");
    if (name === "setup-map-add") {
        const box = document.querySelector(`[data-setup-maps="${action.dataset.app}"]`);
        if (box) box.insertAdjacentHTML("beforeend", setupArrMapRow(action.dataset.app));
        setup.dirty.add("arr");
        return;
    }
    if (name === "setup-player-map-add") {
        const box = document.querySelector(`[data-setup-player-maps="${action.dataset.player}"]`);
        if (box) box.insertAdjacentHTML("beforeend", setupPlayerMapRow(action.dataset.player));
        setup.dirty.add("players");
        return;
    }
    if (name === "setup-row-remove") {
        const row = action.closest(".setup-map");
        const panel = action.closest("[data-setup-panel]");
        if (row) row.remove();
        if (panel) setup.dirty.add(panel.dataset.setupPanel);
        return;
    }
    if (name === "setup-browse-local") {
        const row = action.closest(".setup-map");
        state.pathMapInput = row ? row.querySelector("[data-map-local]") : null;
        return openPathBrowser("map-local");
    }
    if (name === "setup-copy") return copySetupText(action.dataset.copy || "");
    if (name === "setup-scan") return startSetupScans(action);
}

document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !state.setup || !event.target.dataset || !event.target.dataset.setupFolderInput) return;
    event.preventDefault();
    setupAddFolder(event.target.value, event.target.dataset.setupFolderInput, "artists");
});

document.addEventListener("input", (event) => {
    if (!state.setup) return;
    const panel = event.target.closest && event.target.closest("[data-setup-panel]");
    if (panel && panel.dataset.setupPanel !== "finish" && !event.target.closest("#trakt-box")) state.setup.dirty.add(panel.dataset.setupPanel);
});
