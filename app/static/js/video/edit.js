const SOURCE_PRESETS = [
    "UHD Remux", "UHD Blu-ray", "Complete UHD Blu-ray", "UHD Rip", "Blu-ray Remux", "Blu-ray", "Blu-ray Rip", "Complete Blu-ray",
    "HD-DVD Remux", "HD-DVD", "WEB-DL", "WEBRip", "WEBCap", "HDTV", "PDTV", "DSR", "TVRip",
    "DVD", "DVDRip", "HDRip", "VHS", "VHSRip", "Screener", "Telecine", "Telesync", "CAM", "Workprint", "R5",
];
const EDITION_PRESETS = [
    "Director's Cut", "Extended Cut", "Theatrical Cut", "Unrated", "Uncut", "Remastered", "Restored",
    "IMAX", "IMAX Enhanced", "Final Cut", "Ultimate Cut", "Ultimate Collector's Edition", "Criterion", "Open Matte",
    "Assembly Cut", "Bootleg Cut", "International Cut", "Hong Kong Cut", "Mandarin Cut", "Recut", "Vinegar Syndrome",
    "Special Edition",
    "Anniversary Edition", "Collector's Edition", "Limited Edition",
];

const VIDEO_EDIT_FIELDS = {
    movie: [
        ["title", "Title"], ["original_title", "Original title"], ["sort_title", "Sort title"], ["year", "Year", "number"],
        ["set_name", "Movie set", "set_name"], ["set_overview", "Movie set overview", "area"],
        ["source_format", "Source format", "source"], ["release_group", "Release group"], ["edition", "Edition", "edition"], ["is_hybrid", "Hybrid", "bool"],
        ["tagline", "Tagline"], ["outline", "Outline", "area"], ["plot", "Plot", "area"],
        ["runtime_minutes", "Runtime (minutes)", "number"], ["mpaa", "Certification", "cert"], ["premiered", "Premiered", "date"],
        ["rating", "Rating (0-10)", "decimal"], ["votes", "Votes", "number"], ["top250", "Top 250", "number"],
        ["scrape_language", "Scrape language", "locale"],
        ["genres", "Genres", "list"], ["countries", "Countries", "list"], ["studios", "Studios", "list"],
        ["directors", "Directors", "list"], ["writers", "Writers", "list"], ["tags", "Tags", "list"], ["trailer", "Trailer"],
    ],
    show: [
        ["title", "Title"], ["original_title", "Original title"], ["sort_title", "Sort title"], ["year", "Year", "number"],
        ["tagline", "Tagline"], ["outline", "Outline", "area"], ["plot", "Plot", "area"],
        ["show_status", "Status"], ["premiered", "Premiered", "date"],
        ["mpaa", "Certification", "cert"], ["runtime_minutes", "Runtime (minutes)", "number"], ["rating", "Rating (0-10)", "decimal"],
        ["votes", "Votes", "number"], ["user_rating", "User rating (0-10)", "decimal"], ["top250", "Top 250", "number"],
        ["original_language", "Original language", "lang"], ["scrape_language", "Scrape language", "locale"], ["trailer", "Trailer"],
        ["genres", "Genres", "list"], ["studios", "Networks", "list"], ["countries", "Countries", "list"],
        ["directors", "Directors", "list"], ["tags", "Tags", "list"],
        ["episode_order", "Episode order", "order"],
    ],
    season: [
        ["title", "Title"], ["season_name", "Season name"], ["plot", "Plot", "area"], ["premiered", "Premiered", "date"], ["year", "Year", "number"], ["trailer", "Trailer"],
    ],
    episode: [
        ["title", "Title"], ["plot", "Plot", "area"], ["aired", "Aired", "date"], ["runtime_minutes", "Runtime (minutes)", "number"],
        ["mpaa", "Certification", "cert"], ["scrape_language", "Scrape language", "locale"],
        ["source_format", "Source format", "source"], ["release_group", "Release group"], ["edition", "Edition", "edition"], ["is_hybrid", "Hybrid", "bool"],
        ["rating", "Rating (0-10)", "decimal"], ["votes", "Votes", "number"], ["user_rating", "User rating (0-10)", "decimal"],
        ["display_season", "Display season", "number"], ["display_episode", "Display episode", "number"],
        ["resume_position", "Resume position (seconds)", "seconds"], ["resume_total", "Resume length (seconds)", "seconds"],
        ["directors", "Directors", "list"], ["writers", "Writers", "list"],
    ],
    set: [
        ["name", "Title"], ["overview", "Overview", "area"],
    ],
};

state.videoEdit = null;

function arrSearchButtons(kind, item) {
    const sonarr = integrationOn("sonarr") ? "" : " is-unavailable";
    if (kind === "movie") {
        return `<button type="button" class="btn-ghost" data-action="video-bazarr-missing" data-kind="movie" data-id="${escapeHtml(item.id)}" title="Ask Bazarr to search the subtitles it lists as missing">Search missing subtitles</button>`;
    }
    if (kind === "show") {
        return `<button type="button" class="btn-ghost${sonarr}" data-action="video-sonarr-missing" data-show="${escapeHtml(item.id)}" title="Ask Sonarr to search monitored episodes it has no file for">Search missing episodes</button>
            <button type="button" class="btn-ghost" data-action="video-bazarr-missing" data-kind="show" data-id="${escapeHtml(item.id)}" title="Ask Bazarr to search the subtitles it lists as missing">Search missing subtitles</button>`;
    }
    if (kind === "episode") {
        return `<button type="button" class="btn-ghost${sonarr}" data-action="video-sonarr-episode" data-id="${escapeHtml(item.id)}" title="Look up in Sonarr">${lookUpIn("sonarr")}</button>
            <button type="button" class="btn-ghost${sonarr}" data-action="video-sonarr-missing" data-show="${escapeHtml(item.show_id || "")}" data-season="${item.season_number}" title="Ask Sonarr to search monitored episodes in this season that it has no file for">Search missing episodes</button>
            <button type="button" class="btn-ghost" data-action="video-bazarr-missing" data-kind="episode" data-id="${escapeHtml(item.id)}" title="Ask Bazarr to search the subtitles it lists as missing for this episode">Search missing subtitles</button>`;
    }
    return "";
}

async function searchMissingEpisodes(action) {
    const body = { show_id: action.dataset.show };
    if (action.dataset.season !== undefined && action.dataset.season !== "") body.season_number = Number(action.dataset.season);
    const data = await api("/api/v1/sonarr/missing", { method: "POST", body });
    notify(data.message || "Sonarr is searching.", "success");
}

async function searchMissingSubtitles(action) {
    const data = await api("/api/v1/bazarr/missing", { method: "POST", body: { kind: action.dataset.kind, id: action.dataset.id } });
    notify(data.message || "Bazarr is searching.", "success");
}

function remuxFile(item) {
    return item && item.file ? item.file : null;
}

function remuxButtons(kind, item) {
    if (kind !== "movie" && kind !== "episode") return "";
    const file = remuxFile(item);
    const path = String((file && file.path) || "");
    if (!path.toLowerCase().endsWith(".mkv")) return "";
    const profile = String((file && file.dovi_profile) || "");
    const layer = String((file && file.dovi_el_type) || "").toUpperCase();
    const convert = profile.startsWith("7") && (layer === "FEL" || layer === "MEL")
        ? `<button type="button" class="btn-ghost" data-action="video-dovi" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Convert to DV 8.1</button>`
        : "";
    return `<button type="button" class="btn-ghost" data-action="video-tracks" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Tracks</button>${convert}`;
}

function videoItemActions(kind, item) {
    const locked = !!item.locked;
    if (isWanted(item)) {
        return `<div class="vactions">
            <button type="button" class="btn-ghost" data-action="video-edit" data-kind="${kind}" data-id="${escapeHtml(item.id)}" ${locked ? "disabled title=\"Unlock to edit\"" : ""}>Edit</button>
            <button type="button" class="btn-ghost" data-action="video-scrape-prefs" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Custom scrapers…</button>
        </div>${storyCopy(item)}`;
    }
    return `<div class="vactions">
        <button type="button" class="btn-ghost" data-action="video-edit" data-kind="${kind}" data-id="${escapeHtml(item.id)}" ${locked ? "disabled title=\"Unlock to edit\"" : ""}>Edit</button>
        <button type="button" class="btn-ghost" data-action="video-scrape-prefs" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Custom scrapers…</button>
        ${kind === "movie" || kind === "show" || kind === "episode" ? `<button type="button" class="btn-ghost" data-action="video-ratings" data-kind="${kind}" data-id="${escapeHtml(item.id)}" ${locked ? "disabled" : ""}>Update ratings</button>` : ""}
        ${kind === "movie" || kind === "episode" ? `<button type="button" class="btn-ghost" data-action="video-mediainfo" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Update media info</button>` : ""}
        ${kind === "episode" && !item.missing ? `<button type="button" class="btn-ghost" data-action="video-gen-thumb" data-id="${escapeHtml(item.id)}">Generate thumb</button>` : ""}
        ${remuxButtons(kind, item)}
        ${kind === "movie" || kind === "show" ? `<button type="button" class="btn-ghost" data-action="video-library-update" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Update library…</button>` : ""}
        ${arrSearchButtons(kind, item)}
        <button type="button" class="btn-ghost" data-action="video-nfo-one" data-kind="${kind}" data-id="${escapeHtml(item.id)}">Write .nfo</button>
        ${kind === "episode" && typeof splitEpisodesButton === "function" ? splitEpisodesButton(item) : ""}
    </div>${kind === "episode" ? "" : storyCopy(item)}${item.scrape_error ? `<p class="vscrape-error">Last scrape: ${escapeHtml(item.scrape_error)} <button type="button" class="btn-ghost" data-action="video-copy-probe" data-fail="scrape" title="${escapeHtml(item.scrape_error)}">Copy</button></p>` : ""}`;
}

function videoEditUrl(kind, id) {
    const path = { movie: "movies", show: "tv/shows", episode: "tv/episodes", set: "sets" }[kind];
    return `/api/v1/${path}/${encodeURIComponent(id)}`;
}

function editValue(item, field, type) {
    const value = item[field];
    if (type === "list") return (value || []).join(", ");
    if (value === null || value === undefined) return "";
    return String(value);
}

function presetField(field, presets, current, blank, max) {
    const options = presets.map((label) =>
        `<button type="button" class="preset-option" data-action="video-preset-pick" data-preset="${escapeHtml(label)}">${escapeHtml(label)}</button>`
    ).join("");
    return `<span class="preset-field">
        <input type="text" data-edit-field="${field}" value="${escapeHtml(current)}" maxlength="${max}" placeholder="${escapeHtml(blank)}" autocomplete="off">
        <button type="button" class="btn-ghost preset-toggle" data-action="video-preset-toggle" aria-label="Show presets" title="Show presets">▾</button>
        <span class="preset-menu hidden" role="listbox">${options}</span>
    </span>`;
}

function closePresetMenus() {
    document.querySelectorAll(".preset-menu").forEach((menu) => {
        menu.classList.add("hidden");
        const field = menu._presetField;
        if (field && menu.parentElement !== field) field.appendChild(menu);
    });
}

function openPresetMenu(field) {
    if (!field) return;
    const menu = field.querySelector(".preset-menu") || field._presetMenu;
    const input = field.querySelector("input");
    if (!menu || !input) return;
    closePresetMenus();
    if (!field.dataset.presetId) field.dataset.presetId = `preset-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    menu.dataset.presetFor = field.dataset.presetId;
    menu._presetField = field;
    field._presetMenu = menu;
    const current = input.value.trim();
    menu.querySelectorAll(".preset-option").forEach((button) => {
        button.classList.toggle("is-current", button.dataset.preset === current);
    });
    document.body.appendChild(menu);
    menu.classList.remove("hidden");
    const box = field.getBoundingClientRect();
    const below = window.innerHeight - box.bottom;
    menu.style.left = `${box.left}px`;
    menu.style.width = `${box.width}px`;
    if (below >= 140 || below >= box.top) {
        menu.style.top = `${box.bottom + 2}px`;
        menu.style.bottom = "auto";
        menu.style.maxHeight = `${Math.max(120, Math.min(280, below - 8))}px`;
    } else {
        menu.style.top = "auto";
        menu.style.bottom = `${window.innerHeight - box.top + 2}px`;
        menu.style.maxHeight = `${Math.max(120, Math.min(280, box.top - 8))}px`;
    }
    const marked = menu.querySelector(".is-current");
    if (marked) marked.scrollIntoView({ block: "nearest" });
}

function togglePresetMenu(button) {
    const field = button.closest(".preset-field");
    if (!field) return;
    const menu = field.querySelector(".preset-menu") || field._presetMenu;
    if (!menu || menu.classList.contains("hidden")) openPresetMenu(field);
    else closePresetMenus();
}

function pickPreset(button) {
    const menu = button.closest(".preset-menu");
    const field = (menu && menu._presetField) || button.closest(".preset-field");
    const input = field && field.querySelector("input");
    if (!input) return;
    input.value = button.dataset.preset || "";
    input.dispatchEvent(new Event("change", { bubbles: true }));
    closePresetMenus();
    input.focus();
}

function storyCopy(item) {
    const tagline = item.tagline ? `<p class="vtagline">${escapeHtml(item.tagline)}</p>` : "";
    const outline = item.outline ? `<p class="vplot voutline">${escapeHtml(item.outline)}</p>` : "";
    const plot = item.plot ? `<p class="vplot">${escapeHtml(item.plot)}</p>` : "";
    if (!tagline && !outline && !plot) return "";
    return `<div class="vstory">${tagline}${outline}${plot}</div>`;
}

function mediaFlagSection(item) {
    const flags = (item && item.media_flags) || [];
    const room = flags.find((flag) => flag.slot === "room");
    const icons = flags.filter((flag) => flag.slot !== "room");
    if (!icons.length && !room) return "";
    const cards = icons.map((flag) => `<div class="vflag-card" title="${escapeHtml(flag.name || "")}"><img src="${escapeHtml(flag.src || "")}" alt="${escapeHtml(flag.name || "")}"></div>`).join("");
    const roomHtml = room
        ? `<div class="vflag-room" title="${escapeHtml(room.name || "")}"><img class="vflag-room-base" src="${escapeHtml(room.base || "")}" alt=""><img class="vflag-room-overlay" src="${escapeHtml(room.overlay || "")}" alt="${escapeHtml(room.name || "")}"></div>`
        : "";
    return `<div class="vmedia-split"><div class="vmedia-flags">${cards}</div>${roomHtml}</div>`;
}

async function refreshVideoMediaInfo(kind, ids) {
    const list = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
    const data = await api("/api/v1/mediainfo", { method: "POST", body: { kind, ids: list } });
    notify(data.message || "Media info updated.", data.updated ? "success" : "info");
    if (kind === "movie" && state.video.movieId && list.includes(state.video.movieId)) return openMovie(state.video.movieId);
    if (kind === "episode" && state.video.tvSel && state.video.tvSel.type === "episode" && list.includes(state.video.tvSel.id)) return openEpisode(state.video.tvSel.id);
}

async function generateEpisodeThumb(id) {
    const data = await api(`/api/v1/tv/episodes/${encodeURIComponent(id)}/thumb`, { method: "POST", body: {} });
    notify("Thumbnail generated.", "success");
    if (state.video.tvSel && state.video.tvSel.type === "episode" && state.video.tvSel.id === id) {
        await openEpisode(id);
    }
    return data;
}

async function refreshVideoRatings(kind, id) {
    const data = await api(`/api/v1/ratings/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, { method: "POST", body: {} });
    notify(data.message || "Ratings updated.", "success");
    if (kind === "movie") return openMovie(id);
    if (kind === "show") return openShow(id);
    return openEpisode(id);
}

async function openVideoEdit(kind, id) {
    const center = document.getElementById("video-center");
    const token = (state.video.detailToken += 1);
    center.innerHTML = `<p class="muted vpad">Loading…</p>`;
    let item;
    if (kind === "season") {
        let show = [...state.video.showDetails.values()].find((entry) => (entry.seasons || []).some((season) => season.id === id));
        if (!show) {
            const node = (state.video.rows || []).find((row) => row.id === id && row._kind === "season");
            if (node && node._showId && typeof showDetail === "function") show = await showDetail(node._showId);
        }
        item = show && (show.seasons || []).find((season) => season.id === id);
        if (!item) throw new Error("Open the season, then edit it");
        const names = (show && show.season_names) || {};
        item = { ...item, season_name: names[String(item.season_number)] || "" };
    } else {
        item = await api(videoEditUrl(kind, id));
    }
    if (token !== state.video.detailToken) return;
    const file = item.file || {};
    if (file.source_format) item.source_format = file.source_format;
    item.release_group = file.release_group || "";
    if (kind === "episode") item.edition = file.edition || item.edition || "";
    item.is_hybrid = !!file.is_hybrid;
    if (item.locked) {
        notify("This item is locked. Unlock it to edit.", "warning");
        return renderVideoCenter();
    }
    state.videoEdit = { kind, id, item };
    const locked = new Set(item.locked_fields || []);
    const rows = VIDEO_EDIT_FIELDS[kind].map(([field, label, type]) => {
        const value = editValue(item, field, type);
        const pinField = field === "set_name" || field === "set_overview" ? "set" : field;
        const isLocked = locked.has(field) || locked.has(pinField);
        const pin = `<button type="button" class="vfield-lock${isLocked ? " is-locked" : ""}" data-action="video-unlock-field" data-field="${pinField}" title="${isLocked ? "Scrapes leave this field alone. Click to let scrapes update it again." : "Click to lock this field so scrapes leave it alone."}">${lockIcon(isLocked)}</button>`;
        let input;
        if (type === "area") input = `<textarea data-edit-field="${field}" rows="${field === "plot" || field === "overview" ? 7 : 3}">${escapeHtml(value)}</textarea>`;
        else if (type === "set_name") {
            const setNames = [...new Set(((state.video && state.video.sets) || []).map((s) => s.name).filter(Boolean))];
            input = presetField(field, setNames, value, "Type a set name or leave blank to remove from set", 120);
        }
        else if (type === "source") input = presetField(field, SOURCE_PRESETS, value, "Type or choose a source", 40);
        else if (type === "cert") input = certControl(kind, value);
        else if (type === "lang") input = languageSelect(field, value);
        else if (type === "edition") input = presetField(field, EDITION_PRESETS, value, "Type or choose an edition", 80);
        else if (type === "bool") input = `<input type="checkbox" data-edit-field="${field}" ${value === "true" ? "checked" : ""}>`;
        else if (type === "locale") {
            const options = [["", "Library default"], ...(typeof SCRAPE_LOCALES !== "undefined" ? SCRAPE_LOCALES : [["en-US", "English (US)"]])];
            const current = value || "";
            const listed = options.some(([key]) => key === current) ? options : [[current, current], ...options];
            input = `<select data-edit-field="${field}">${listed.map(([key, text]) =>
                `<option value="${escapeHtml(key)}" ${key === current ? "selected" : ""}>${escapeHtml(text)}</option>`).join("")}</select>`;
        }
        else if (type === "order") {
            input = `<select data-edit-field="${field}">${[["", "Use the setting"], ["aired", "Aired"], ["dvd", "DVD"], ["absolute", "Absolute"]].map(([key, text]) =>
                `<option value="${key}" ${key === value ? "selected" : ""}>${text}</option>`).join("")}</select>`;
        } else {
            const attrs = type === "number" ? `type="number" step="1"` : type === "decimal" ? `type="number" step="0.1" min="0" max="10"` : type === "seconds" ? `type="number" step="0.001" min="0"` : `type="text"`;
            const extra = field === "release_group" ? ` maxlength="40" placeholder="FraMeSToR"` : "";
            input = `<input ${attrs} data-edit-field="${field}" value="${escapeHtml(value)}"${extra}${type === "list" ? ` placeholder="Comma separated"` : ""}${type === "date" ? ` placeholder="YYYY-MM-DD"` : ""}>`;
        }
        return `<label class="vedit-row"><span>${escapeHtml(label)} ${pin}</span>${input}</label>`;
    }).join("");
    const heading = kind === "episode" ? `${episodeCode(item)} · ${item.title || ""}` : kind === "set" ? (item.name || item.title || "") : `${item.title || ""}${item.year ? ` (${item.year})` : ""}`;
    const filePath = shownPath(item, "file") || shownPath(item);
    center.innerHTML = `<article class="vinfo"><section class="vsection">
        <h2>Edit ${escapeHtml(heading)}</h2>
        ${filePathBlock(filePath)}
        <p class="muted">Edited fields are locked, so scrapes keep your values. The padlock next to a field unlocks it again.</p>
        <form id="video-edit-form" class="vedit">${rows}</form>
        <p class="vactions"><button type="button" data-action="video-edit-save">Save</button>
            <button type="button" class="btn-ghost" data-action="video-edit-cancel">Cancel</button></p>
    </section></article>`;
    bindCertCountry(center);
}

function changedEditFields() {
    const edit = state.videoEdit;
    const fields = {};
    document.querySelectorAll("#video-edit-form [data-edit-field]").forEach((input) => {
        const field = input.dataset.editField;
        const spec = VIDEO_EDIT_FIELDS[edit.kind].find(([key]) => key === field);
        const before = editValue(edit.item, field, spec && spec[2]);
        const after = input.type === "checkbox" ? (input.checked ? "true" : "false") : input.value.trim();
        if (spec && spec[2] === "list") {
            const norm = (text) => text.split(",").map((part) => part.trim()).filter(Boolean).join(", ");
            if (norm(after) !== norm(before)) fields[field] = after.split(",").map((part) => part.trim()).filter(Boolean);
        } else if (spec && spec[2] === "bool") {
            if (after !== (before === "true" ? "true" : "false")) fields[field] = after === "true";
        } else if (after !== before.trim()) {
            fields[field] = after;
        }
    });
    return fields;
}

async function saveVideoEdit() {
    const edit = state.videoEdit;
    if (!edit) return;
    const fields = changedEditFields();
    if (!Object.keys(fields).length) {
        notify("Nothing changed.", "info");
        return closeVideoEdit();
    }
    const data = await api(`/api/v1/items/${edit.kind}/${encodeURIComponent(edit.id)}`, { method: "PATCH", body: { fields } });
    if (data.nfo_error) notify(`Saved, but the .nfo was not written: ${data.nfo_error}`, "warning");
    else notify("Saved.", "info");
    const kind = edit.kind;
    const savedId = edit.id;
    const showId = edit.item.show_id;
    state.videoEdit = null;
    patchVideoRows(kind, [savedId], fields);
    if (kind === "movie" && (Object.prototype.hasOwnProperty.call(fields, "set_name") || Object.prototype.hasOwnProperty.call(fields, "set_overview"))) {
        state.video.stale.sets = true;
    }
    if (kind === "movie") return openMovie(savedId);
    if (kind === "show") return openShow(savedId);
    if (kind === "season") return openSeason(savedId, showId, true);
    if (kind === "set") return openSet(savedId);
    return openEpisode(savedId);
}

async function unlockVideoField(field, action) {
    const edit = state.videoEdit;
    if (!edit || !field) return;
    const current = new Set(Array.isArray(edit.item.locked_fields) ? edit.item.locked_fields : []);
    const wasLocked = current.has(field);
    const endpoint = wasLocked ? "unlock-fields" : "lock-fields";
    await api(`/api/v1/items/${edit.kind}/${encodeURIComponent(edit.id)}/${endpoint}`, { method: "POST", body: { fields: [field] } });
    if (wasLocked) current.delete(field);
    else current.add(field);
    edit.item.locked_fields = [...current];
    const nowLocked = !wasLocked;
    document.querySelectorAll(`#video-edit-form [data-action="video-unlock-field"][data-field="${CSS.escape(field)}"]`).forEach((btn) => {
        btn.classList.toggle("is-locked", nowLocked);
        btn.innerHTML = lockIcon(nowLocked);
        btn.title = nowLocked
            ? "Scrapes leave this field alone. Click to let scrapes update it again."
            : "Click to lock this field so scrapes leave it alone.";
    });
    notify(nowLocked ? `Locked ${field.replace(/_/g, " ")}.` : `Scrapes can update ${field.replace(/_/g, " ")} again.`, "info");
}

function closeVideoEdit() {
    state.videoEdit = null;
    renderVideoCenter();
}

function settingsCountry() {
    const code = typeof videoCfg === "function" ? videoCfg().country : "";
    return String(code || "US").trim().toUpperCase() || "US";
}

function certLabel(country, value) {
    const text = String(value || "").trim();
    if (!text || /^(nr|n\/a|not rated|unrated)$/i.test(text)) return "Not Rated";
    if (String(country || "").toUpperCase() === "US" && !text.toLowerCase().startsWith("rated")) return `Rated ${text}`;
    return text;
}

function certPresets(kind, country) {
    const code = String(country || settingsCountry()).trim().toUpperCase() || "US";
    const row = (typeof CERT_RATINGS !== "undefined" && CERT_RATINGS[code]) || (typeof CERT_RATINGS !== "undefined" && CERT_RATINGS.US) || {};
    const list = (kind === "movie" ? row.movie : row.tv) || [];
    const labels = [];
    const seen = new Set();
    list.concat(["Not Rated"]).forEach((item) => {
        const label = certLabel(code, item);
        const key = label.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        labels.push(label);
    });
    return labels;
}

function certCountries() {
    const saved = settingsCountry();
    const options = typeof CERT_COUNTRIES !== "undefined" ? CERT_COUNTRIES.slice() : [["US", "United States"]];
    if (!options.some(([code]) => code === saved)) options.unshift([saved, saved]);
    return options;
}

function certControl(kind, current) {
    const country = settingsCountry();
    const select = `<select data-cert-country data-cert-kind="${escapeHtml(kind)}" title="Certification country">${certCountries().map(([code, label]) =>
        `<option value="${escapeHtml(code)}" ${code === country ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select>`;
    return `<div class="cert-field">${select}${presetField("mpaa", certPresets(kind, country), current || "", "Type or choose a certification", 40)}</div>`;
}

function fillCertMenu(select) {
    const wrap = select.closest(".cert-field");
    const field = wrap && wrap.querySelector(".preset-field");
    const menu = field && (field.querySelector(".preset-menu") || field._presetMenu);
    if (!menu) return;
    menu.innerHTML = certPresets(select.dataset.certKind, select.value).map((label) =>
        `<button type="button" class="preset-option" data-action="video-preset-pick" data-preset="${escapeHtml(label)}">${escapeHtml(label)}</button>`
    ).join("");
}

function bindCertCountry(root) {
    (root || document).querySelectorAll("[data-cert-country]").forEach((select) => {
        select.addEventListener("change", () => fillCertMenu(select));
    });
}

function languageSelect(field, current) {
    const options = typeof ORIGIN_LANGUAGES !== "undefined" ? ORIGIN_LANGUAGES : [["en", "English"]];
    const value = current || "";
    const listed = typeof withCurrentOption === "function" ? withCurrentOption(options, value) : options;
    return `<select data-edit-field="${field}">${listed.map(([key, text]) =>
        `<option value="${escapeHtml(key)}" ${key === value ? "selected" : ""}>${escapeHtml(text)}</option>`).join("")}</select>`;
}

const BATCH_EDIT_FIELDS = {
    movie: [
        ["watched", "Watched", "watched"],
        ["set_name", "Movie set", "set_name"],
        ["mpaa", "Certification", "cert"], ["genres", "Genres", "list"], ["countries", "Countries", "list"],
        ["studios", "Studios", "list"], ["tags", "Tags", "list"],
        ["source_format", "Source format", "source"], ["edition", "Edition", "edition"],
        ["is_hybrid", "Hybrid", "yesno"], ["scrape_language", "Scrape language", "locale"],
    ],
    show: [
        ["mpaa", "Certification", "cert"], ["genres", "Genres", "list"], ["studios", "Networks", "list"],
        ["countries", "Countries", "list"], ["tags", "Tags", "list"],
        ["show_status", "Status", "status"], ["original_language", "Original language", "lang"],
        ["scrape_language", "Scrape language", "locale"], ["episode_order", "Episode order", "order"],
    ],
    episode: [
        ["watched", "Watched", "watched"],
        ["mpaa", "Certification", "cert"], ["source_format", "Source format", "source"], ["edition", "Edition", "edition"],
        ["is_hybrid", "Hybrid", "yesno"], ["scrape_language", "Scrape language", "locale"],
    ],
    album: [
        ["type", "Release type", "release"], ["edition", "Edition", "edition"], ["label", "Label"],
        ["country", "Country"], ["genres", "Genres", "list"], ["mood", "Mood"], ["style", "Style"],
        ["theme", "Theme"], ["release_status", "Release status"], ["boxset", "Box set", "yesno"],
    ],
};

const BATCH_EDIT_NOUN = { movie: "movies", show: "shows", episode: "episodes", album: "albums" };

function batchEditIds(kind) {
    if (kind === "movie") return [...selectionChecked("movie")];
    if (kind === "album") return [...selectionChecked("album")];
    const prefix = `${kind}:`;
    return [...selectionChecked("tv")].filter((key) => String(key).startsWith(prefix)).map((key) => key.slice(prefix.length));
}

function batchFieldControl(field, type, kind) {
    if (type === "set_name") {
        const setNames = [...new Set(((state.video && state.video.sets) || []).map((s) => s.name).filter(Boolean))];
        return presetField(field, setNames, "", "Type a set name or leave blank to clear set", 120);
    }
    if (type === "source") return presetField(field, SOURCE_PRESETS, "", "Type or choose a source", 40);
    if (type === "edition") return presetField(field, EDITION_PRESETS, "", "Type or choose an edition", 80);
    if (type === "cert") return certControl(kind, "");
    if (type === "lang") return languageSelect(field, "");
    if (type === "yesno") {
        return `<select data-edit-field="${field}"><option value="true">Yes</option><option value="false">No</option></select>`;
    }
    if (type === "watched") {
        return `<select data-edit-field="${field}"><option value="true">Watched</option><option value="false">Not watched</option></select>`;
    }
    if (type === "status") {
        const options = ["Continuing", "Ended", "Canceled", "Returning Series", "Planned", "In Production", "Pilot"];
        return `<select data-edit-field="${field}">${options.map((text) => `<option value="${escapeHtml(text)}">${escapeHtml(text)}</option>`).join("")}</select>`;
    }
    if (type === "release") {
        const options = [["album", "Album"], ["single", "Single"], ["ep", "EP"], ["compilation", "Compilation"], ["live", "Live"], ["unknown", "Unknown"]];
        return `<select data-edit-field="${field}">${options.map(([key, text]) => `<option value="${key}">${text}</option>`).join("")}</select>`;
    }
    if (type === "locale") {
        const options = [["", "Library default"], ...(typeof SCRAPE_LOCALES !== "undefined" ? SCRAPE_LOCALES : [["en-US", "English (US)"]])];
        return `<select data-edit-field="${field}">${options.map(([key, text]) => `<option value="${escapeHtml(key)}">${escapeHtml(text)}</option>`).join("")}</select>`;
    }
    if (type === "order") {
        return `<select data-edit-field="${field}">${[["aired", "Aired"], ["dvd", "DVD"], ["absolute", "Absolute"]].map(([key, text]) =>
            `<option value="${key}">${text}</option>`).join("")}</select>`;
    }
    return `<input type="text" data-edit-field="${field}"${type === "list" ? ` placeholder="Comma separated"` : ""}>`;
}

function markBatchField(node) {
    const row = node && node.closest(".batch-field");
    const box = row && row.querySelector("[data-batch-on]");
    if (box && node !== box && !(node.matches && node.matches("[data-cert-country]"))) box.checked = true;
}

function openBatchEdit(kind, ids) {
    const specs = BATCH_EDIT_FIELDS[kind];
    const chosen = (ids || []).filter(Boolean);
    if (!specs || !chosen.length) return;
    state.batchEdit = { kind, ids: chosen };
    const noun = BATCH_EDIT_NOUN[kind] || "items";
    document.getElementById("batch-edit-title").textContent = `Edit ${chosen.length} ${chosen.length === 1 ? noun.replace(/s$/, "") : noun}`;
    document.getElementById("batch-edit-note").textContent = "Check a field to write it on every selected item. Titles, plots, dates, and episode numbers stay as they are. Locked items are skipped.";
    const rows = specs.map(([field, label, type]) => `<div class="batch-field">
        <input type="checkbox" id="batch-on-${field}" data-batch-on="${field}">
        <label for="batch-on-${field}">${escapeHtml(label)}</label>
        <div class="batch-control">${batchFieldControl(field, type, kind)}</div>
    </div>`).join("");
    document.getElementById("batch-edit-body").innerHTML = `<form id="batch-edit-form" class="batch-fields">${rows}</form>
        <p class="vactions"><button type="button" data-action="batch-edit-save">Save</button>
            <button type="button" class="btn-ghost" data-close="batch-edit-modal">Cancel</button></p>`;
    document.getElementById("batch-edit-form").addEventListener("change", (event) => markBatchField(event.target));
    bindCertCountry(document.getElementById("batch-edit-form"));
    document.getElementById("batch-edit-modal").classList.remove("hidden");
}

function batchEditValues() {
    const edit = state.batchEdit;
    const fields = {};
    if (!edit) return fields;
    document.querySelectorAll("#batch-edit-form [data-batch-on]:checked").forEach((box) => {
        const field = box.dataset.batchOn;
        const spec = BATCH_EDIT_FIELDS[edit.kind].find(([key]) => key === field);
        const input = document.querySelector(`#batch-edit-form [data-edit-field="${field}"]`);
        if (!input || !spec) return;
        const type = spec[2];
        if (type === "list") fields[field] = input.value.split(",").map((part) => part.trim()).filter(Boolean);
        else if (type === "yesno" || type === "watched") fields[field] = input.value === "true";
        else fields[field] = input.value.trim();
    });
    return fields;
}

// Put the old values back. Items that had the same old values are written together in one call.
function batchEditUndo(path, previous) {
    const entries = Object.entries(previous || {});
    if (!entries.length) return null;
    const groups = new Map();
    entries.forEach(([id, fields]) => {
        const key = JSON.stringify(fields);
        if (!groups.has(key)) groups.set(key, { fields, ids: [] });
        groups.get(key).ids.push(id);
    });
    return async () => {
        for (const group of groups.values()) await api(path, { method: "POST", body: { ids: group.ids, fields: group.fields } });
        notify("Edit undone.", "info");
        if (path.includes("/albums/")) return loadLibrary();
        return refreshVideoItems(path.split("/")[4]);
    };
}

async function saveBatchEdit() {
    const edit = state.batchEdit;
    if (!edit) return;
    const fields = batchEditValues();
    if (!Object.keys(fields).length) {
        notify("Check the fields you want to change.", "info");
        return;
    }
    const path = edit.kind === "album" ? "/api/albums/batch-edit" : `/api/v1/items/${edit.kind}/batch`;
    const data = await api(path, { method: "POST", body: { ids: edit.ids, fields } });
    const updated = Number(data.updated) || 0;
    const skipped = Number(data.skipped) || 0;
    let message = `Updated ${updated}.`;
    if (skipped) message += ` Skipped ${skipped} locked.`;
    if (data.nfo_error) message += ` The .nfo was not written: ${data.nfo_error}`;
    else if (data.nfo_errors) message += ` ${data.nfo_errors} .nfo file${data.nfo_errors === 1 ? "" : "s"} could not be written.`;
    const undo = batchEditUndo(path, data.previous);
    notify(message, data.nfo_error || data.nfo_errors ? "warning" : "info", undo ? { undo } : undefined);
    document.getElementById("batch-edit-modal").classList.add("hidden");
    const kind = edit.kind;
    const ids = edit.ids.slice();
    state.batchEdit = null;
    if (kind === "album") return loadLibrary();
    patchVideoRows(kind, ids, fields);
    return refreshVideoItems(kind);
}

function scrapePrefSelect(id, names, current) {
    const labels = { tmdb: "TMDB", tvdb: "TheTVDB", tvmaze: "TVMaze", omdb: "OMDb", trakt: "Trakt", fanart: "Fanart.tv" };
    const options = [["", "Default"]];
    (names || []).forEach((name) => {
        if (name && !options.some(([value]) => value === name)) options.push([name, labels[name] || name]);
    });
    const node = document.getElementById(id);
    node.innerHTML = options.map(([value, text]) => `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`).join("");
    node.value = options.some(([value]) => value === (current || "")) ? (current || "") : "";
}

async function openScrapePrefs(kind, id) {
    const data = await api(`/api/v1/scrape/prefs?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`);
    state.scrapePrefs = { kind, id, show: kind === "show" };
    scrapePrefSelect("scrape-prefs-source", data.sources, data.source);
    scrapePrefSelect("scrape-prefs-art", data.art_sources, data.art);
    const orderWrap = document.getElementById("scrape-prefs-order-wrap");
    orderWrap.classList.toggle("hidden", kind !== "show");
    if (kind === "show") document.getElementById("scrape-prefs-order").value = data.episode_order || "";
    document.getElementById("scrape-prefs-modal").classList.remove("hidden");
}

async function saveScrapePrefs() {
    const prefs = state.scrapePrefs || {};
    const body = {
        kind: prefs.kind,
        id: prefs.id,
        source: document.getElementById("scrape-prefs-source").value,
        art: document.getElementById("scrape-prefs-art").value,
    };
    if (prefs.show) body.episode_order = document.getElementById("scrape-prefs-order").value;
    await api("/api/v1/scrape/prefs", { method: "PUT", body });
    document.getElementById("scrape-prefs-modal").classList.add("hidden");
    notify("Custom scrapers saved.", "info");
}

const VIDEO_EDIT_ACTIONS = {
    "video-edit": (action) => runAction(() => openVideoEdit(action.dataset.kind, action.dataset.id)),
    "video-scrape-prefs": (action) => runAction(() => openScrapePrefs(action.dataset.kind, action.dataset.id)),
    "video-scrape-prefs-save": () => runAction(saveScrapePrefs, "Saving…"),
    "video-edit-save": () => runAction(saveVideoEdit, "Saving…"),
    "video-edit-cancel": () => closeVideoEdit(),
    "video-batch-edit": (action) => openBatchEdit(action.dataset.kind, batchEditIds(action.dataset.kind)),
    "batch-edit-save": () => runAction(saveBatchEdit, "Saving…"),
    "video-unlock-field": (action) => runAction(() => unlockVideoField(action.dataset.field, action)),
    "video-match": (action) => openFixMatch(action.dataset.kind, action.dataset.id),
    "video-scrape-one": (action) => openVideoScrapeModal("selected", { media: scrapeMediaFor(action.dataset.kind), ids: [action.dataset.id] }),
    "video-nfo-one": (action) => runAction(() => writeVideoNfo(action.dataset.kind, [action.dataset.id])),
    "video-scrape-set": (action) => openVideoScrapeModal("selected", { media: "sets", ids: [action.dataset.id] }),
    "video-delete-one": (action) => deleteVideoItemsAsk({ kind: action.dataset.kind, ids: [action.dataset.id] }),
    "video-radarr-search": (action) => {
        if (arrSearchBlocked("radarr")) return;
        return runAction(() => searchSetInRadarr(action), "Asking Radarr…");
    },
    "video-sonarr-missing": (action) => {
        if (arrSearchBlocked("sonarr")) return;
        return runAction(() => searchMissingEpisodes(action), "Asking Sonarr…");
    },
    "video-sonarr-episode": (action) => {
        if (arrSearchBlocked("sonarr")) return;
        return runAction(() => lookupEpisodesInSonarr({ kind: "episode", ids: [action.dataset.id] }), "Asking Sonarr…");
    },
    "video-bazarr-missing": (action) => runAction(() => searchMissingSubtitles(action), "Asking Bazarr…"),
    "video-ratings": (action) => runAction(() => refreshVideoRatings(action.dataset.kind, action.dataset.id), "Updating ratings…"),
    "video-mediainfo": (action) => runAction(() => refreshVideoMediaInfo(action.dataset.kind, [action.dataset.id]), "Reading media info…"),
    "video-gen-thumb": (action) => runAction(() => generateEpisodeThumb(action.dataset.id), "Generating thumbnail…"),
    "video-tracks": (action) => runAction(() => openTracks(action.dataset.kind, action.dataset.id)),
    "video-tracks-save": () => runAction(saveTracks, "Rewriting tracks…"),
    "video-dovi": (action) => confirmProfile8(action.dataset.kind, action.dataset.id),
    "video-dovi-convert": () => runAction(startProfile8, "Converting Dolby Vision…"),
    "video-sub-save": (action) => runAction(() => saveSubtitleFlags(action), "Saving subtitle…"),
    "video-default-track": (action) => runAction(() => setDefaultTrack(action), "Setting the default track…"),
    "video-track-lang": (action) => runAction(() => setTrackLanguage(action), "Setting the language…"),
    "video-preset-toggle": (action) => togglePresetMenu(action),
    "video-preset-pick": (action) => pickPreset(action),
    "video-view-nfo": (action) => runAction(() => showVideoNfo(action.dataset.kind, action.dataset.id)),
    "video-split-open": (action) => openEpisodeSplit(action.dataset.id),
    "video-split-run": (action) => runAction(() => runEpisodeSplit(action.dataset.id), "Splitting…"),
    "video-split-all": () => runAction(() => runAllEpisodeSplits(), "Splitting…"),
    "video-split-restore": (action) => runAction(() => restoreEpisodeSplit(action.dataset.id), "Restoring the original file…"),
    "video-split-mark": () => markSplitVideoTime(),
    "video-split-delete-source": (action) => {
        askDanger(
            "Delete Source File",
            "Are you sure you want to permanently delete the original source video file from disk? This cannot be undone.",
            "Delete Source File",
            () => runAction(() => deleteSplitSource(action.dataset.id), "Deleting the source file…"),
            true
        );
    },
};

async function setDefaultTrack(action) {
    holdCenterScroll();
    const data = await api("/api/v1/tracks/default", {
        method: "POST",
        body: {
            kind: action.dataset.kind,
            id: action.dataset.id,
            track: action.dataset.track,
            index: Number(action.dataset.index),
        },
    });
    notify(data.message || "Default track saved.", "success");
    if (action.dataset.kind === "movie") return openMovie(action.dataset.id, true);
    return openEpisode(action.dataset.id, true);
}

// Picking a language only asks. The file is changed after the person confirms.
function setTrackLanguage(action) {
    const select = action.parentElement && action.parentElement.querySelector("select");
    const lang = select ? select.value : "";
    if (!lang) {
        notify("Choose a language first.", "warning");
        return;
    }
    const kind = action.dataset.track === "subtitle" ? "subtitle" : "audio";
    const number = Number(action.dataset.index) + 1;
    askDanger(
        "Confirm language change",
        `Change the language of ${kind} track ${number} from ${trackLanguageName(action.dataset.current)} to ${trackLanguageName(lang)}? This is written into the video file.`,
        "Confirm",
        () => writeTrackLanguage({ kind: action.dataset.kind, id: action.dataset.id, track: action.dataset.track, index: Number(action.dataset.index), lang }),
        false,
    );
}

async function writeTrackLanguage(change) {
    holdCenterScroll();
    const data = await api("/api/v1/tracks/language", { method: "POST", body: change });
    notify(data.message || "Language saved.", "success");
    if (change.kind === "movie") return openMovie(change.id, true);
    return openEpisode(change.id, true);
}

function saveSubtitleFlags(action) {
    const form = action.closest(".vsub-edit");
    const flags = [...form.querySelectorAll("[data-sub-flag]:checked")].map((input) => input.dataset.subFlag);
    const lang = form.querySelector("[data-sub-lang]").value;
    if (!lang) {
        notify("Choose a language first.", "warning");
        return;
    }
    const change = { kind: action.dataset.kind, id: action.dataset.id, file: form.dataset.subFile, lang, flags };
    // Flags alone are saved straight away. A new language renames the file, so that one is confirmed first.
    if (lang.toLowerCase() === (form.dataset.subCurrent || "")) return writeSubtitle(change);
    askDanger(
        "Confirm language change",
        `Change the language of ${form.dataset.subFile} from ${trackLanguageName(form.dataset.subCurrent)} to ${trackLanguageName(lang)}? The subtitle file is renamed to match.`,
        "Confirm",
        () => writeSubtitle(change),
        false,
    );
}

async function writeSubtitle(change) {
    holdCenterScroll();
    const data = await api("/api/v1/subtitles", { method: "POST", body: change });
    notify(data.file ? `Subtitle saved as ${data.file}.` : "Subtitle saved.", "success");
    if (change.kind === "movie") return openMovie(change.id, true);
    return openEpisode(change.id, true);
}

function trackLine(track) {
    const detail = [track.lang, track.type === "audio" ? track.channels : "", track.forced ? "forced" : "", track.default ? "default" : "", track.name]
        .filter(Boolean).join(" · ");
    return `<label class="track-row"><input type="checkbox" value="${Number(track.id)}" checked data-track-type="${escapeHtml(track.type)}">
        <span>${escapeHtml(track.type)} ${Number(track.id)} · ${escapeHtml(track.codec || "")}${detail ? ` · ${escapeHtml(detail)}` : ""}</span></label>`;
}

function tracksReady() {
    const boxes = [...document.querySelectorAll("#tracks-list input[type='checkbox']")];
    const video = boxes.some((box) => box.checked && box.dataset.trackType === "video");
    const audio = boxes.some((box) => box.checked && box.dataset.trackType === "audio");
    const button = document.getElementById("tracks-confirm");
    if (button) button.disabled = !(video && audio);
}

async function openTracks(kind, id) {
    const data = await api(`/api/v1/remux/tracks?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`);
    state.video.tracksItem = { kind, id };
    const groups = ["video", "audio", "subtitle"].map((type) => {
        const rows = (data.tracks || []).filter((track) => track.type === type);
        if (!rows.length) return "";
        const title = type === "subtitle" ? "Subtitles" : type[0].toUpperCase() + type.slice(1);
        return `<h3>${title}</h3>${rows.map(trackLine).join("")}`;
    }).join("");
    document.getElementById("tracks-list").innerHTML = groups || "<p>This file has no tracks.</p>";
    document.getElementById("tracks-list").onchange = tracksReady;
    tracksReady();
    document.getElementById("tracks-modal").classList.remove("hidden");
}

async function saveTracks() {
    const item = state.video.tracksItem;
    if (!item) return;
    const tracks = [...document.querySelectorAll("#tracks-list input[type='checkbox']:checked")].map((box) => Number(box.value));
    document.getElementById("tracks-modal").classList.add("hidden");
    await api("/api/v1/remux/tracks", { method: "POST", body: { kind: item.kind, id: item.id, tracks } });
    notify("Rewriting this file.", "info");
    watchRemux(item.kind, item.id, true);
}

function confirmProfile8(kind, id) {
    state.video.doviItem = { kind, id };
    const box = document.getElementById("dovi-remove-original");
    if (box) box.checked = false;
    document.getElementById("dovi-modal").classList.remove("hidden");
}

async function startProfile8() {
    const item = state.video.doviItem;
    if (!item) return;
    const removeOriginal = !!document.getElementById("dovi-remove-original").checked;
    document.getElementById("dovi-modal").classList.add("hidden");
    await api("/api/v1/remux/dovi", { method: "POST", body: { kind: item.kind, id: item.id, remove_original: removeOriginal } });
    notify(removeOriginal
        ? "Converting Dolby Vision. The original is removed after the new file is deep scanned."
        : "Converting Dolby Vision. The original file stays in place.", "info");
    watchRemux(item.kind, item.id, false);
}

async function watchRemux(kind, id, reload) {
    for (let attempt = 0; attempt < 1080; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const status = await api("/api/v1/remux/status");
        if (status.status === "running") continue;
        if (status.failed && status.failed.length) notify(status.failed[0], "error");
        else notify(status.message || "Remux finished.", "success");
        const openId = status.item_id || id;
        const openKind = status.kind || kind;
        if ((reload || status.item_id) && openKind === "movie") await openMovie(openId);
        if ((reload || status.item_id) && openKind === "episode") await openEpisode(openId);
        return;
    }
}

function onVideoEditAction(name, action) {
    const run = VIDEO_EDIT_ACTIONS[name];
    if (!run) return false;
    run(action);
    return true;
}
