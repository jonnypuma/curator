function placeBatchBar() {
    const bar = document.getElementById("batch-bar");
    const scan = document.getElementById("dock-scan");
    const slot = bar && bar.parentElement;
    if (!bar || !scan || !slot) return;
    const gap = 8;
    const width = scan.getBoundingClientRect().left - slot.getBoundingClientRect().left - gap;
    bar.style.width = width > 0 ? `${Math.round(width)}px` : "";
}

window.addEventListener("resize", placeBatchBar);
let lookupCompareToken = 0;

function visibleAlbums() {
    const rows = [];
    for (const artist of state.artists) {
        for (const album of artist.albums || []) rows.push({ artist, album });
    }
    return rows;
}

function selectByTier(tier) {
    selectionReplace("album", visibleAlbums().filter((row) => (
        tier === "new" ? row.album.status === "NEW" : albumTier(row.album) === tier
    )).map((row) => row.album.id));
    renderTree();
    renderBatchBar();
    refreshOpenLookup();
}

function selectVisible(on) {
    selectionReplace("album", on ? visibleAlbums().map((row) => row.album.id) : []);
    renderTree();
    renderBatchBar();
    refreshOpenLookup();
}

function expandAll() {
    const open = state.artists.some((artist) => !state.expanded.has(artist.id));
    state.expanded = open ? new Set(state.artists.map((artist) => artist.id)) : new Set();
    persistExpanded();
    renderTree();
}

function renderBatchBar() {
    const rows = visibleAlbums().filter((row) => state.selected.has(row.album.id));
    const bar = document.getElementById("batch-bar");
    const open = rows.length > 0;
    bar.classList.toggle("is-open", open);
    bar.setAttribute("aria-hidden", open ? "false" : "true");
    placeBatchBar();
    const tracks = rows.reduce((sum, row) => sum + (row.album.total_tracks || 0), 0);
    const gold = rows.filter((row) => row.album.match_tier === "gold").length;
    const silver = rows.filter((row) => row.album.match_tier === "silver").length;
    document.getElementById("batch-selected-count").textContent = String(rows.length);
    const mark = rows.length > 1 ? ` (${rows.length})` : "";
    const review = document.querySelector("[data-action='open-batch']");
    const scrape = document.querySelector("#batch-bar [data-action='batch-scrape']");
    const edit = document.querySelector("#batch-bar [data-action='batch-edit-fields']");
    const merge = document.querySelector("[data-action='group-compilation']");
    const nfo = document.querySelector("#batch-bar [data-action='batch-nfo']");
    const processed = document.querySelector("#batch-bar [data-action='batch-processed']");
    const lockBtn = document.querySelector("#batch-bar [data-action='batch-lock']");
    const forget = document.querySelector("#batch-bar [data-action='batch-forget']");
    const removeDisk = document.querySelector("#batch-bar [data-action='batch-delete']");
    const rescan = document.querySelector("#batch-bar [data-action='batch-rescan']");
    if (review) review.textContent = `Review batch${mark}`;
    if (scrape) scrape.textContent = `Scrape…${mark}`;
    if (edit) edit.textContent = `Edit fields…${mark}`;
    if (merge) merge.textContent = `Merge as compilation${mark}`;
    if (nfo) nfo.textContent = `Write .nfo${mark}`;
    if (processed) processed.textContent = `Mark processed${mark}`;
    if (lockBtn) lockBtn.textContent = `${rows.length && rows.every((row) => row.album.locked) ? "Unlock" : "Lock"}${mark}`;
    if (forget) forget.textContent = `Remove from library${mark}`;
    if (removeDisk) removeDisk.textContent = `Delete from disk${mark}`;
    if (rescan) {
        const mode = state.batchRescanMode || rescan.dataset.mode || "deep";
        const labels = { incremental: "Incremental", full: "Full", deep: "Deep" };
        rescan.dataset.mode = mode;
        rescan.dataset.count = String(rows.length);
        rescan.textContent = `Rescan${mark} | ${labels[mode] || "Deep"}`;
    }
    renderSelectedCount();
    document.getElementById("batch-selected-tracks").textContent = `${tracks} tracks`;
    document.getElementById("batch-gold-count").textContent = `${gold} gold`;
    document.getElementById("batch-silver-count").textContent = `${silver} partial`;
}

async function rescanSelectedAlbums(action) {
    const rows = visibleAlbums().filter((row) => state.selected.has(row.album.id));
    const albums = rows.map((row) => row.album && row.album.path).filter(Boolean);
    if (!albums.length) return;
    const mode = (action && action.dataset.mode) || state.batchRescanMode || "deep";
    const labels = { incremental: "Incremental", full: "Full", deep: "Deep" };
    const data = await api("/api/scan", { method: "POST", body: { mode, albums, force: false } });
    if (data.queued) {
        state.scanQueue = data.scan_queue || state.scanQueue || [];
        notify(data.duplicate ? "That music scan is already queued." : "Music scan queued. It starts when the current scan finishes.", "info");
        renderScanButton(state.scan || {});
        pollSystem();
        return;
    }
    if (data.started) {
        state.scanning = true;
        state.stopping = false;
        renderScanButton({ status: "running" });
        notify(`${labels[mode] || "Deep"} scan of ${albums.length} album${albums.length === 1 ? "" : "s"}.`, "info");
    } else if (data.blocked === "backup") {
        notify("A database backup is running.", "info");
    } else {
        state.scanning = true;
        notify("A scan is already running.", "info");
    }
    syncBackupButton();
    pollSystem();
}

async function openBatchModal() {
    const rows = visibleAlbums().filter((row) => state.selected.has(row.album.id));
    if (!rows.length) return;
    try {
        if (!state.settings) state.settings = await api("/api/settings");
    } catch (error) {
        notify(error.message, "error");
        return;
    }
    const body = rows.map((row) => `<tr>
        <td>${escapeHtml(row.artist.name)}</td>
        <td>${escapeHtml(row.album.title)}</td>
        <td>${row.album.total_tracks || 0}</td>
        <td>${matchIcon(row.album.match_tier)} ${row.album.match_ratio || 0}%</td>
        <td>${row.album.has_nfo ? "yes" : "no"}</td>
        <td>${row.album.has_artwork ? "yes" : "no"}</td>
    </tr>`).join("");
    document.getElementById("batch-preview").innerHTML = `<thead><tr><th>Artist</th><th>Album</th><th>Tracks</th><th>Match</th><th>NFO</th><th>Art</th></tr></thead><tbody>${body}</tbody>`;
    document.getElementById("batch-log").textContent = "Ready. Find metadata writes tags from the linked MusicBrainz release, or the closest search result. Missing artwork, lyrics, and album.nfo follow, in that order. Mark processed is last and only clears the NEW badge. Folder and file moves stay off unless you enable them.";
    document.getElementById("batch-progress").style.width = "0%";
    applyBatchRename();
    document.getElementById("batch-opt-rename-master").onchange = updateBatchRenameSummary;
    document.querySelectorAll("input[name='batch-rename-scope']").forEach((input) => {
        input.onchange = updateBatchRenameSummary;
    });
    document.getElementById("batch-modal").classList.remove("hidden");
}

function applyBatchRename() {
    const cfg = state.settings || {};
    document.getElementById("batch-opt-rename-master").checked = !!cfg.rename_enabled;
    const scope = cfg.rename_scope === "folder" || cfg.rename_scope === "file" ? cfg.rename_scope : "both";
    const radio = document.querySelector(`input[name="batch-rename-scope"][value="${scope}"]`);
    if (radio) radio.checked = true;
    updateBatchRenameSummary();
}

function updateBatchRenameSummary() {
    const enabled = document.getElementById("batch-opt-rename-master").checked;
    const summary = document.getElementById("batch-rename-summary");
    const panel = document.getElementById("batch-rename-subpanel");
    const card = document.getElementById("batch-rename-card");
    panel.classList.toggle("hidden", !enabled);
    card.classList.toggle("is-active", enabled);
    if (!enabled) {
        summary.textContent = "Renaming: Skipped (Safe Mode - paths preserved)";
        summary.className = "rename-summary";
        return;
    }
    const selected = document.querySelector("input[name='batch-rename-scope']:checked");
    const scope = selected ? selected.value : "both";
    const label = scope === "folder" ? "Folders Only" : scope === "file" ? "Files Only" : "Folders + Files";
    summary.textContent = `Renaming: Active (${label})`;
    summary.className = "rename-summary is-active";
    const cfg = state.settings || {};
    const folder = cfg.rename_folder_pattern || "%albumartist%/[%year%] %album%$if(%multidisc%,/CD%discnumber%)";
    const file = cfg.rename_file_pattern || "Disc %discnumber% - $num(%tracknumber%,2) - %title%";
    document.getElementById("batch-rename-pattern").textContent = `${folder}/${file}`;
}

function openRenameModal() {
    const cfg = state.settings || {};
    document.getElementById("rename-pattern-folder").value = cfg.rename_folder_pattern || "%albumartist%/[%year%] %album%$if(%multidisc%,/CD%discnumber%)";
    document.getElementById("rename-pattern-file").value = cfg.rename_file_pattern || "Disc %discnumber% - $num(%tracknumber%,2) - %title%";
    document.getElementById("rename-opt-clean").checked = cfg.rename_clean_chars !== false;
    document.getElementById("rename-opt-sidecars").checked = cfg.rename_move_sidecars !== false;
    document.getElementById("rename-opt-prune").checked = !!cfg.rename_prune_empty;
    document.getElementById("rename-opt-quotes").checked = !!cfg.rename_straight_quotes;
    document.getElementById("rename-opt-junk").checked = !!cfg.rename_strip_junk;
    document.getElementById("rename-opt-ascii").checked = !!cfg.rename_transliterate;
    const batchOn = document.getElementById("batch-opt-rename-master").checked;
    const batchScope = document.querySelector("input[name='batch-rename-scope']:checked");
    document.getElementById("rename-execute-switch").checked = batchOn;
    const scope = batchOn && batchScope ? batchScope.value : "none";
    const radio = document.querySelector(`input[name="rename-scope"][value="${scope}"]`);
    if (radio) radio.checked = true;
    const preset = document.getElementById("rename-preset");
    preset.value = "custom";
    preset.onchange = applyRenamePreset;
    document.getElementById("rename-execute-switch").onchange = onRenameSwitch;
    document.querySelectorAll("input[name='rename-scope']").forEach((input) => {
        input.onchange = onRenameScope;
    });
    ["rename-pattern-folder", "rename-pattern-file", "rename-opt-clean", "rename-opt-sidecars", "rename-opt-prune"].forEach((id) => {
        document.getElementById(id).oninput = scheduleRenamePreview;
        document.getElementById(id).onchange = scheduleRenamePreview;
    });
    syncRenameEditor();
    scheduleRenamePreview();
    document.getElementById("rename-modal").classList.remove("hidden");
}

function onRenameSwitch() {
    const enabled = document.getElementById("rename-execute-switch").checked;
    if (enabled) {
        const current = document.querySelector("input[name='rename-scope']:checked");
        if (!current || current.value === "none") {
            document.querySelector("input[name='rename-scope'][value='both']").checked = true;
        }
    }
    syncRenameEditor();
    scheduleRenamePreview();
}

function onRenameScope() {
    const selected = document.querySelector("input[name='rename-scope']:checked");
    document.getElementById("rename-execute-switch").checked = !!(selected && selected.value !== "none");
    syncRenameEditor();
    scheduleRenamePreview();
}

function applyRenamePreset() {
    const presets = {
        standard: ["%albumartist%/[%year%] %album%", "$num(%tracknumber%,2) - %title%"],
        multidisc: ["%albumartist%/[%year%] %album%$if(%multidisc%,/CD%discnumber%)", "Disc %discnumber% - $num(%tracknumber%,2) - %title%"],
        flat: ["%albumartist% - %album%", "%artist% - %album% - $num(%tracknumber%,2) - %title%"],
    };
    const pair = presets[document.getElementById("rename-preset").value];
    if (!pair) return;
    document.getElementById("rename-pattern-folder").value = pair[0];
    document.getElementById("rename-pattern-file").value = pair[1];
    scheduleRenamePreview();
}

function insertRenameToken(token) {
    const active = document.activeElement;
    const target = active && (active.id === "rename-pattern-folder" || active.id === "rename-pattern-file")
        ? active
        : document.getElementById("rename-pattern-file");
    if (!target) return;
    const start = target.selectionStart == null ? target.value.length : target.selectionStart;
    const end = target.selectionEnd == null ? target.value.length : target.selectionEnd;
    target.value = `${target.value.slice(0, start)}${token}${target.value.slice(end)}`;
    document.getElementById("rename-preset").value = "custom";
    scheduleRenamePreview();
}

function renameFormOptions() {
    const execute = document.getElementById("rename-execute-switch").checked;
    const selected = document.querySelector("input[name='rename-scope']:checked");
    const scope = selected ? selected.value : "none";
    const active = execute && scope !== "none";
    return {
        rename: active,
        rename_scope: active ? scope : "none",
        rename_folder_pattern: document.getElementById("rename-pattern-folder").value,
        rename_file_pattern: document.getElementById("rename-pattern-file").value,
        rename_clean_chars: document.getElementById("rename-opt-clean").checked,
        rename_move_sidecars: document.getElementById("rename-opt-sidecars").checked,
        rename_prune_empty: document.getElementById("rename-opt-prune").checked,
        rename_straight_quotes: document.getElementById("rename-opt-quotes").checked,
        rename_strip_junk: document.getElementById("rename-opt-junk").checked,
        rename_transliterate: document.getElementById("rename-opt-ascii").checked,
    };
}

function syncRenameEditor() {
    const form = renameFormOptions();
    document.getElementById("rename-patterns-box").classList.toggle("is-disabled", !form.rename);
    const labels = { both: "folders and audio files", folder: "folders only", file: "audio files only" };
    document.getElementById("rename-scope-note").textContent = form.rename
        ? `Renaming will apply to ${labels[form.rename_scope]}.`
        : "Renaming is skipped: files and folders stay untouched.";
}

refreshRenamePreview.current = 0;

function scheduleRenamePreview() {
    syncRenameEditor();
    clearTimeout(scheduleRenamePreview.timer);
    scheduleRenamePreview.timer = setTimeout(() => {
        refreshRenamePreview();
        paintRenamePatternExample();
    }, 250);
}

async function paintRenamePatternExample() {
    const node = document.getElementById("rename-pattern-example");
    const folder = document.getElementById("rename-pattern-folder");
    const file = document.getElementById("rename-pattern-file");
    if (!node || !folder || !file) return;
    try {
        const data = await api("/api/rename/example", {
            method: "POST",
            body: { rename_folder_pattern: folder.value, rename_file_pattern: file.value },
        });
        node.textContent = data.error || data.path || "";
    } catch (error) {
        node.textContent = "";
    }
}

async function refreshRenamePreview() {
    const request = ++refreshRenamePreview.current;
    const table = document.getElementById("rename-preview");
    const ids = albumActionIds();
    if (!ids.length) {
        table.innerHTML = "";
        return;
    }
    try {
        const data = await api("/api/rename/preview", {
            method: "POST",
            body: { album_ids: ids, ...renameFormOptions() },
        });
        if (request !== refreshRenamePreview.current) return;
        const rows = (data.rows || []).slice(0, 20);
        const body = rows.map((row) => `<tr>
            <td>${escapeHtml(row.album)}<div class="muted">${escapeHtml(row.track)}</div></td>
            <td class="mono">${escapeHtml(row.current)}</td>
            <td class="mono">${escapeHtml(row.destination)}</td>
        </tr>`).join("");
        const extra = (data.rows || []).length > rows.length ? `<p class="muted">Showing ${rows.length} of ${data.rows.length} paths.</p>` : "";
        const notes = (data.notes || []).slice(0, 4).map((note) => `<p class="muted">${escapeHtml(note)}</p>`).join("");
        table.innerHTML = `<thead><tr><th>Item</th><th>Current</th><th>Destination</th></tr></thead><tbody>${body || `<tr><td colspan="3">No files to preview.</td></tr>`}</tbody>`;
        let note = document.getElementById("rename-preview-note");
        if (!note) {
            note = document.createElement("div");
            note.id = "rename-preview-note";
            table.insertAdjacentElement("afterend", note);
        }
        note.innerHTML = `${extra}${notes}`;
    } catch (error) {
        table.innerHTML = `<tbody><tr><td>${escapeHtml(error.message)}</td></tr></tbody>`;
    }
}

async function saveRenameConfig() {
    const cfg = { ...(state.settings || await api("/api/settings")) };
    delete cfg.key_sources;
    const form = renameFormOptions();
    cfg.rename_enabled = form.rename;
    cfg.rename_scope = form.rename_scope;
    cfg.rename_folder_pattern = form.rename_folder_pattern;
    cfg.rename_file_pattern = form.rename_file_pattern;
    cfg.rename_clean_chars = form.rename_clean_chars;
    cfg.rename_move_sidecars = form.rename_move_sidecars;
    cfg.rename_prune_empty = form.rename_prune_empty;
    cfg.rename_straight_quotes = form.rename_straight_quotes;
    cfg.rename_strip_junk = form.rename_strip_junk;
    cfg.rename_transliterate = form.rename_transliterate;
    state.settings = await api("/api/settings", { method: "PUT", body: cfg });
    applyBatchRename();
    document.getElementById("rename-modal").classList.add("hidden");
    notify(cfg.rename_enabled ? "Rename patterns saved. The next batch will move files." : "Rename patterns saved. Moves stay off until you enable them.", "info");
}

async function runBatch() {
    const ids = [...state.selected];
    if (!ids.length) return;
    const data = await api("/api/batch", {
        method: "POST",
        body: {
            album_ids: ids,
            tags: document.getElementById("batch-opt-tags").checked,
            nfo: document.getElementById("batch-opt-nfo").checked,
            art: document.getElementById("batch-opt-art").checked,
            lyrics: document.getElementById("batch-opt-lrc").checked,
            processed: document.getElementById("batch-opt-processed").checked,
            replaygain: document.getElementById("batch-opt-gain").checked,
            rename: document.getElementById("batch-opt-rename-master").checked,
            rename_scope: (document.querySelector("input[name='batch-rename-scope']:checked") || {}).value || "both",
        },
    });
    state.batching = true;
    notify(data.started ? "Batch started." : "A batch is already running.", "info");
    pollSystem();
}

function renderBatchProgress(job) {
    const modal = document.getElementById("batch-modal");
    if (modal.classList.contains("hidden")) return;
    const width = job.total ? Math.round(100 * (job.processed || 0) / job.total) : 0;
    document.getElementById("batch-progress").style.width = `${job.status === "completed" ? 100 : width}%`;
    document.getElementById("batch-log").textContent = job.log || job.message || "";
    document.getElementById("batch-run").disabled = job.status === "running";
}

function selectedLookupItems() {
    return visibleAlbums()
        .filter((row) => albumActionIds().includes(row.album.id))
        .map((row) => ({
            album_id: row.album.id,
            artist: row.artist.name,
            title: row.album.title,
            year: row.album.release_year,
            edition: row.album.edition || "",
            country: row.album.country || "",
            catalog: row.album.catalog || "",
            label: row.album.label || "",
            type: row.album.type || "",
            track_count: row.album.total_tracks || 0,
            folder: folderName(row.album.path),
            status: "",
            note: "",
            chosen: "",
            candidates: [],
        }));
}

function sameAlbumSet(items) {
    const current = albumActionIds().map(String).sort();
    const shown = (items || []).map((item) => String(item.album_id)).sort();
    return current.length > 0 && current.length === shown.length && current.every((id, index) => id === shown[index]);
}

function syncLookupApply() {
    const apply = document.getElementById("lookup-apply");
    if (!apply) return;
    const busy = state.lookupPhase === "running" || state.lookupPhase === "applying" || state.lookupPhase === "loading";
    apply.disabled = busy || !state.lookupCanApply;
}

function liveCounted(label, job) {
    const counts = job && job.total ? `${job.processed || 0}/${job.total}` : "";
    const note = shortLiveNote(job && job.message);
    if (note && (!counts || note.includes(counts))) return `${label} · ${note}`;
    const head = counts ? `${label} ${counts}` : label;
    return note ? `${head} · ${note}` : head;
}

function liveScrapeLabel() {
    const scrape = state.videoScrape || {};
    if (scrape.status !== "running" || scrape.embedded) return "";
    return liveCounted(withoutLaneWord(scrapeJobLabel(scrape), "scrape"), scrape);
}

function liveVideoScanLabel() {
    const scan = state.videoScan || {};
    if (scan.status !== "running") return "";
    const name = scan.media === "tv" ? "TV" : scan.media === "sets" ? "Sets" : "Movies";
    return liveCounted(name, scan);
}

function shortLiveNote(message) {
    const text = String(message || "").replace(/\s+/g, " ").trim();
    if (!text || text.length > 42) return "";
    return text;
}

function activityChip(lane, label, open, extra) {
    return Object.assign({ lane, label, open }, extra || {});
}

function liveWork() {
    const chips = [];
    const scan = state.videoScan || {};
    if (scan.status === "running") {
        const media = scan.media === "tv" ? "tv" : scan.media === "sets" ? "sets" : "movies";
        chips.push(activityChip("Scan", liveVideoScanLabel(), "scan", { media }));
    }
    const parked = state.videoPaused || {};
    if (parked.media && parked.media !== scan.media) {
        const name = parked.media === "tv" ? "TV" : "Movies";
        chips.push(activityChip("Scan", liveCounted(`${name} · Paused`, parked), "scan", { media: parked.media }));
    }
    if (state.scanning && state.scan && state.scan.status === "running") {
        chips.push(activityChip("Scan", liveCounted(`Music · ${scanKindLabel(state.scan)}`, state.scan), "scan", { media: "music" }));
    }
    const scrapeLabel = liveScrapeLabel();
    if (scrapeLabel) chips.push(activityChip("Scrape", scrapeLabel, "scrape"));
    const queue = (typeof live !== "undefined" && live.queue) || {};
    const library = queue.library || state.queuePanel && state.queuePanel.library || [];
    const runningPlayers = new Set();
    library.filter((item) => item.status === "running").forEach((item) => {
        const player = item.player || item.source || "";
        runningPlayers.add(player);
        chips.push(activityChip("Library", item.title || item.where || "Update", "queue", { tab: "library" }));
    });
    const waitingByPlayer = {};
    library.filter((item) => item.status !== "running").forEach((item) => {
        const player = item.player || item.source || "library";
        if (runningPlayers.has(player)) return;
        waitingByPlayer[player] = (waitingByPlayer[player] || 0) + 1;
    });
    Object.keys(waitingByPlayer).forEach((player) => {
        const name = player ? player.charAt(0).toUpperCase() + player.slice(1) : "Library";
        chips.push(activityChip("Library", `${name} ${waitingByPlayer[player]} waiting`, "queue", { tab: "library" }));
    });
    const imports = Number(queue.queued_items_count) || 0;
    if (queue.running) {
        chips.push(activityChip("Import", shortLiveNote(queue.message) || "Imports running", "queue", { tab: "webhook" }));
    } else if (imports) {
        const clock = typeof queueClock === "function" ? queueClock(queue.remaining_seconds) : "";
        chips.push(activityChip("Import", clock ? `${imports} imports · ${clock}` : `${imports} imports`, "queue", { tab: "webhook" }));
    }
    const arr = queue.arr || (state.queuePanel && state.queuePanel.arr) || [];
    const runningArr = arr.find((item) => item.status === "running");
    if (runningArr) chips.push(activityChip("ARR", runningArr.title || "ARR", "queue", { tab: "arr" }));
    else if (arr.length) chips.push(activityChip("ARR", `${arr.length} waiting`, "queue", { tab: "arr" }));
    if (state.lookupPhase === "loading") chips.push(activityChip("Lookup", "Loading matches…", "jobs"));
    else if (state.lookupPhase === "applying") chips.push(activityChip("Lookup", "Writing matches…", "jobs"));
    else if (state.lookupPhase === "running") chips.push(activityChip("Lookup", "Finding metadata…", "jobs"));
    if (state.batching) chips.push(activityChip("Batch", "Updating albums…", "jobs"));
    const backup = state.backup || {};
    if (backup.status === "running" || backup.status === "waiting") {
        chips.push(activityChip("Backup", shortLiveNote(backup.message) || "Working on the database…", "jobs"));
    }
    const fileJob = state.fileJob || {};
    if (fileJob.status === "running") chips.push(activityChip("Files", shortLiveNote(fileJob.message) || "File job", "jobs"));
    const libraryNamed = chips.some((chip) => chip.lane === "Library");
    (state.workLive || []).forEach((job) => {
        if (!job || job.status !== "running") return;
        const kind = job.kind || "";
        if ((kind === "kodi-video" || kind === "kodi-music") && libraryNamed) return;
        const lane = kind.indexOf("kodi") === 0 ? "Library" : kind.indexOf("lidarr") === 0 ? "ARR" : "Job";
        const name = typeof jobLabel === "function" ? jobLabel(kind) : (kind || "Job");
        const note = shortLiveNote(job.message);
        chips.push(activityChip(lane, note ? `${name} · ${note}` : name, "jobs"));
    });
    if (state.activityLabel) chips.push(activityChip("Job", state.activityLabel, "jobs"));
    else if (state.working && !chips.some((chip) => chip.open === "jobs")) chips.push(activityChip("Job", "Working…", "jobs"));
    else if (state.busy && !chips.some((chip) => chip.lane === "Lookup")) chips.push(activityChip("Lookup", "Looking up…", "jobs"));
    return chips;
}

function activityChipHtml(chip) {
    const media = chip.media ? ` data-scan-media="${escapeHtml(chip.media)}"` : "";
    const tab = chip.tab ? ` data-tab="${escapeHtml(chip.tab)}"` : "";
    return `<button type="button" class="activity-chip" data-action="open-activity" data-open="${escapeHtml(chip.open || "")}"${media}${tab} title="${escapeHtml(chip.label)}"><small>${escapeHtml(chip.lane)}</small><span>${escapeHtml(chip.label)}</span></button>`;
}

function syncActivity() {
    const el = document.getElementById("activity");
    if (!el) return;
    const chips = liveWork();
    const idle = !chips.length;
    el.classList.remove("hidden");
    el.classList.toggle("is-idle", idle);
    el.classList.remove("is-scan");
    delete el.dataset.action;
    delete el.dataset.scanMedia;
    el.removeAttribute("title");
    el.removeAttribute("tabindex");
    const text = document.getElementById("activity-label");
    if (text) {
        text.textContent = idle ? "Idle" : "";
        text.classList.toggle("hidden", !idle);
    }
    const host = document.getElementById("activity-chips");
    if (host) host.innerHTML = idle ? "" : chips.map(activityChipHtml).join("");
    const now = document.getElementById("queue-now");
    if (now) now.innerHTML = idle ? "" : chips.map(activityChipHtml).join("");
    const local = document.getElementById("lookup-activity");
    if (!local) return;
    const lookupOn = state.lookupPhase === "running" || state.lookupPhase === "applying" || state.lookupPhase === "loading";
    local.classList.toggle("hidden", !lookupOn);
    const localLabel = document.getElementById("lookup-activity-label");
    const lookupChip = chips.find((chip) => chip.lane === "Lookup");
    if (localLabel && lookupOn) localLabel.textContent = lookupChip ? lookupChip.label : "Finding metadata…";
}

function showFreshLookup() {
    clearTimeout(state.lookupTimer);
    state.lookupGeneration += 1;
    state.lookupSignature = "";
    state.lookupSeen = "";
    state.lookupPhase = "";
    state.lookupAutoApply = false;
    state.lookupCanApply = false;
    const items = selectedLookupItems();
    document.getElementById("lookup-log").textContent = items.length
        ? `${items.length} albums selected. The search only looks up releases. Load matches keeps them in the library until you apply each album.`
        : "Select at least one album.";
    document.getElementById("lookup-progress").style.width = "0%";
    document.getElementById("lookup-review").disabled = !items.length;
    document.getElementById("lookup-auto").disabled = !items.length;
    document.getElementById("lookup-list").innerHTML = items.map((item) => renderLookupRow(item, false)).join("")
        || `<p class="muted">Select albums in the library tree.</p>`;
    state.lookupSignature = `fresh|${items.map((item) => item.album_id).join(",")}`;
    syncLookupApply();
    syncActivity();
}

function refreshOpenLookup() {
    const modal = document.getElementById("lookup-modal");
    if (!modal || modal.classList.contains("hidden")) return;
    const review = document.getElementById("lookup-review");
    if (review && review.disabled) return;
    showFreshLookup();
}

async function openLookupModal() {
    if (!albumActionIds().length) {
        notify("Select at least one album.", "info");
        return;
    }
    document.getElementById("batch-modal").classList.add("hidden");
    document.getElementById("lookup-modal").classList.remove("hidden");
    let data = { status: "idle", items: [] };
    try {
        data = await api("/api/batch/lookup");
    } catch (error) {
        notify(error.message, "error");
    }
    const live = data.status === "running" || data.status === "applying";
    if (live || sameAlbumSet(data.items)) {
        renderLookup(data);
        if (live) pollLookup();
        return;
    }
    showFreshLookup();
}

async function startLookup(mode) {
    const ids = albumActionIds();
    if (!ids.length) return;
    state.lookupGeneration += 1;
    const generation = state.lookupGeneration;
    state.lookupSeen = "";
    state.lookupSignature = "";
    state.lookupCanApply = false;
    state.lookupAutoApply = false;
    state.lookupPhase = "running";
    syncActivity();
    document.getElementById("lookup-list").innerHTML = selectedLookupItems().map((item) => renderLookupRow(item, false)).join("");
    document.getElementById("lookup-log").textContent = "Looking up the checked albums…";
    try {
        const data = await api("/api/batch/lookup", { method: "POST", body: { album_ids: ids, mode } });
        if (generation !== state.lookupGeneration) return;
        if (!data.started) {
            state.lookupAutoApply = false;
            notify("A batch is already running.", "info");
        }
        state.lookupSignature = "";
        renderLookup(data.job || {});
        const status = (data.job || {}).status;
        if (status === "running" || status === "applying") {
            pollLookup();
            schedulePoll(300);
        }
        else {
            state.lookupPhase = "";
            syncActivity();
        }
    } catch (error) {
        state.lookupPhase = "";
        state.lookupAutoApply = false;
        syncActivity();
        throw error;
    }
}

async function pollLookup() {
    const generation = state.lookupGeneration;
    clearTimeout(state.lookupTimer);
    const data = await api("/api/batch/lookup");
    if (generation !== state.lookupGeneration) return;
    renderLookup(data);
    if (data.status === "running" || data.status === "applying") {
        const wait = data.status === "applying" ? 700 : 1200;
        state.lookupTimer = setTimeout(() => {
            pollLookup().catch((error) => notify(error.message, "error"));
        }, wait);
        return;
    }
    if (data.status === state.lookupSeen) return;
    state.lookupSeen = data.status;
    if (data.status === "review") {
        notify("Suggestions are ready. Load matches, then open a highlighted album and apply it.", "info");
    }
    if (data.status === "completed") {
        notify(data.message || "Metadata updated.", "info");
        await loadLibrary();
        if (data.applied) showUndo("Album saved");
    }
    if (data.status === "failed") notify(data.message || "Lookup failed", "error");
}

function lookupRowLabel(albumId) {
    for (const artist of state.artists) {
        const album = (artist.albums || []).find((row) => row.id === albumId);
        if (album) return `${artist.name} — ${album.title}`;
    }
    return "Album";
}

async function loadLookupMatches() {
    const rows = [...document.querySelectorAll("#lookup-list [data-lookup-album]")];
    if (!rows.length) {
        notify("Look up the albums first.", "info");
        return;
    }
    return runAction(async () => {
        const plan = rows.map((row) => {
            const skip = row.querySelector("[data-lookup-skip]");
            const select = row.querySelector("[data-lookup-choice]");
            return {
                albumId: row.dataset.lookupAlbum,
                releaseId: skip && skip.checked ? "" : (select ? select.value : ""),
                skipped: !!(skip && skip.checked),
            };
        });
        const chosen = plan.filter((item) => item.releaseId);
        if (!chosen.length) {
            notify("Choose a release for at least one album.", "info");
            return;
        }
        state.lookupPhase = "loading";
        syncLookupApply();
        syncActivity();
        const log = document.getElementById("lookup-log");
        const lines = [];
        let loaded = 0;
        try {
            for (let index = 0; index < chosen.length; index += 1) {
                const item = chosen[index];
                const label = lookupRowLabel(item.albumId);
                lines.push(`Loading ${index + 1} of ${chosen.length}: ${label}`);
                if (log) {
                    log.textContent = lines.join("\n");
                    log.scrollTop = log.scrollHeight;
                }
                try {
                    const data = await api(`/api/albums/${item.albumId}/match`, {
                        method: "POST",
                        body: { release_id: item.releaseId },
                    });
                    if (!data.proposal) throw new Error("No proposal returned");
                    setPending(item.albumId, data.proposal);
                    if (state.album && state.album.album.id === item.albumId) state.proposal = data.proposal;
                    const artist = state.artists.find((row) => (row.albums || []).some((album) => album.id === item.albumId));
                    if (artist) state.expanded.add(artist.id);
                    loaded += 1;
                    lines[lines.length - 1] = `Loaded ${label}`;
                } catch (error) {
                    lines[lines.length - 1] = `${label}: ${error.message}`;
                }
            }
            plan.filter((item) => item.skipped).forEach((item) => {
                setPending(item.albumId, null);
                if (state.album && state.album.album.id === item.albumId) state.proposal = null;
            });
            persistExpanded();
            renderTree();
            if (log) {
                log.textContent = lines.join("\n");
                log.scrollTop = log.scrollHeight;
            }
            notify(
                loaded ? `Loaded ${loaded} ${loaded === 1 ? "match" : "matches"}. Highlighted albums are waiting for Apply match.` : "No matches were loaded.",
                loaded ? "info" : "warning",
            );
            if (loaded >= 2) document.getElementById("lookup-modal").classList.add("hidden");
        } finally {
            state.lookupPhase = "";
            syncLookupApply();
            syncActivity();
        }
    }, "Loading matches…");
}

function renderLookup(data) {
    const job = data || {};
    const busy = job.status === "running" || job.status === "applying";
    const width = job.total ? Math.round(100 * (job.processed || 0) / job.total) : 0;
    document.getElementById("lookup-progress").style.width = `${job.status === "completed" || job.status === "review" ? 100 : width}%`;
    const log = document.getElementById("lookup-log");
    const nextLog = job.log || job.message || "";
    if (state.lookupPhase !== "loading" && log.textContent !== nextLog) {
        log.textContent = nextLog;
        log.scrollTop = log.scrollHeight;
    }
    document.getElementById("lookup-review").disabled = busy;
    document.getElementById("lookup-auto").disabled = busy;
    const apply = document.getElementById("lookup-apply");
    apply.disabled = busy;
    if (state.lookupPhase !== "loading") state.lookupPhase = busy ? job.status : "";
    state.lookupCanApply = job.status === "review";
    syncLookupApply();
    syncActivity();
    const signature = `${job.status}|${(job.items || []).map((item) => `${item.album_id}:${item.status}:${(item.candidates || []).length}`).join(",")}`;
    if (signature === state.lookupSignature) return;
    state.lookupSignature = signature;
    const interactive = job.status === "review";
    const rows = (job.items || []).map((item) => renderLookupRow(item, interactive)).join("");
    document.getElementById("lookup-list").innerHTML = rows || `<p class="muted">Choose Review suggestions or Choose closest matches.</p>`;
    const compareIds = (job.items || [])
        .filter((item) => interactive && item.album_id && (item.candidates || []).length)
        .map((item) => {
            if (!state.compareFocus[item.album_id]) state.compareFocus[item.album_id] = item.chosen || "";
            return item.album_id;
        });
    lookupCompareToken += 1;
    const token = lookupCompareToken;
    compareIds.forEach((albumId) => {
        state.compareOpen.add(albumId);
        const panel = document.querySelector(`#lookup-list [data-compare-panel="${CSS.escape(albumId)}"]`);
        if (!panel) return;
        panel.classList.remove("hidden");
        panel.innerHTML = `<p class="muted compare-note">Loading the release tracks…</p>`;
    });
    const pending = [...compareIds];
    const workers = Array.from({ length: Math.min(4, pending.length) }, async () => {
        while (pending.length && token === lookupCompareToken) {
            const albumId = pending.shift();
            await loadLookupComparison(albumId);
        }
    });
    Promise.all(workers).catch(() => {});
}

function lookupSubject(item) {
    const counted = Number(item.track_count);
    const tracks = Number.isFinite(counted) && counted >= 0 ? counted : 0;
    const facts = [
        item.year || "",
        item.edition || "",
        countryLabel(item.country),
        `${tracks} tracks`,
        item.catalog || "",
        item.label || "",
        releaseTypeLabel(item.type || "album"),
    ].filter(Boolean).join(" · ");
    const title = [item.artist, item.title].filter(Boolean).join(" — ") || "Album";
    const folder = item.folder ? `<span class="compare-folder">${escapeHtml(item.folder)}</span>` : "";
    return `<div class="compare-subject">
        <span class="compare-kicker">Comparing these results to</span>
        ${folder}
        <span class="compare-line">${escapeHtml(title)}</span>
        <span class="compare-line muted">${escapeHtml(facts)}</span>
    </div>`;
}

function renderLookupRow(item, interactive) {
    const candidates = item.candidates || [];
    const note = item.note ? `<p class="muted">${escapeHtml(item.note)}</p>` : "";
    if (!interactive || !candidates.length) {
        return `<div class="lookup-row">
            <div>${lookupSubject(item)}${note}</div>
            <div class="muted">${escapeHtml(item.status || "")}</div>
            <div class="compare-files hidden" data-compare-panel="${escapeHtml(item.album_id || "")}" data-folder-path="${escapeHtml(item.path || "")}"></div>
        </div>`;
    }
    const stored = candidates.find((candidate) => candidate.locked);
    const options = candidates.map((candidate) => {
        const selected = candidate.release_id === item.chosen ? " selected" : "";
        const storedClass = candidate.locked ? ` class="stored-release"` : "";
        return `<option value="${escapeHtml(candidate.release_id)}"${storedClass}${selected}>${escapeHtml(candidateLabel(candidate))}</option>`;
    }).join("");
    const chosenStored = stored && stored.release_id === item.chosen;
    return `<div class="lookup-row" data-lookup-album="${escapeHtml(item.album_id)}">
        <div>
            ${lookupSubject(item)}
            <label class="choice"><input type="checkbox" data-lookup-skip="${escapeHtml(item.album_id)}"> Skip</label>
        </div>
        <label>Release
            <select class="${chosenStored ? "has-stored" : ""}" data-lookup-choice="${escapeHtml(item.album_id)}" data-stored-release="${stored ? escapeHtml(stored.release_id) : ""}">${options}</select>
        </label>
        <div class="compare-files hidden" data-compare-panel="${escapeHtml(item.album_id)}" data-folder-path="${escapeHtml(item.path || "")}"></div>
    </div>`;
}

function candidateLabel(item) {
    const percent = matchPercent(item);
    const badge = matchBadge(percent);
    const bits = [
        percent == null ? "" : `${badge.icon ? `${badge.icon} ` : ""}${percent}%`,
        item.title,
        item.year,
        releaseTypeLabel(item.type_label || item.type),
        countryLabel(item.country),
        item.edition,
        item.format,
        item.track_count ? `${item.track_count} tracks` : "",
        item.acoustid_match ? "AcoustID" : "",
        item.locked ? "Stored release" : "",
        item.disc_match ? "Disc ID" : "",
    ].filter(Boolean);
    return bits.join(" · ");
}

function queueSelectedProcessed() {
    const menu = document.getElementById("album-menu");
    if (menu) menu.classList.add("hidden");
    const ids = albumActionIds();
    if (!ids.length) return;
    notify("Selected albums queued for mark as processed.", "info");
    return runAction(() => completeSelectedProcessed(ids), "Marking albums processed…");
}

async function completeSelectedProcessed(ids) {
    const data = await api("/api/albums/mark", { method: "POST", body: { ids, status: "processed" } });
    paintAlbumStatus(data.updated || ids, data.status || "processed");
    notify("Selected albums marked processed.", "info");
}
