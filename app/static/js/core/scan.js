async function scan(force, mode, verbose) {
    const data = await api("/api/scan", {
        method: "POST",
        body: {
            force: !!force,
            mode: mode || "incremental",
            roots: state.scanRoot ? [state.scanRoot] : [],
            verbose: !!verbose,
        },
    });
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
        state.scanScope = state.scanRoot || "";
        renderScanButton({ status: "running" });
    } else if (data.blocked === "backup") {
        notify("A database backup is running.", "info");
    } else {
        state.scanning = true;
        notify("A scan is already running.", "info");
    }
    syncBackupButton();
    pollSystem();
}

async function cancelScan() {
    if (!state.scanning) return;
    state.stopping = true;
    renderScanButton({ status: "running" });
    const start = document.getElementById("scan-start");
    if (start) {
        start.disabled = true;
        start.textContent = "Stopping…";
    }
    try {
        await api("/api/scan/cancel", { method: "POST", body: {} });
        notify("Stopping the scan. Music already indexed stays.", "info");
        pollSystem();
    } catch (error) {
        state.stopping = false;
        renderScanButton({ status: state.scanning ? "running" : "idle" });
        notify(error.message, "error");
    }
}

function openScanModal() {
    const target = document.getElementById("scan-target");
    if (target) target.textContent = state.scanRoot || "All music paths";
    if (!state.scan || state.scan.status !== "running") selectDefaultScanMode("scan-mode", "music");
    document.getElementById("scan-modal").classList.remove("hidden");
    if (typeof syncLibraryTools === "function") syncLibraryTools();
    if (state.scan) renderScanModal(state.scan);
    pollSystem();
}

function closeScanMenu() {
    const menu = document.getElementById("scan-menu");
    const toggle = document.getElementById("scan-toggle");
    if (menu) menu.classList.add("hidden");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
}

function toggleScanMenu() {
    const menu = document.getElementById("scan-menu");
    const toggle = document.getElementById("scan-toggle");
    if (!menu) return;
    const opening = menu.classList.contains("hidden");
    menu.classList.toggle("hidden");
    if (toggle) toggle.setAttribute("aria-expanded", opening ? "true" : "false");
    if (opening) renderScanMenu();
}

function chooseScanRoot(root) {
    const kind = scanKind();
    if (kind === "music") state.scanRoot = root || "";
    else state.videoScanRoots[kind] = root || "";
    closeScanMenu();
    renderScanButton({ status: state.scanning ? "running" : "idle" });
    const target = document.getElementById(kind === "music" ? "scan-target" : "video-scan-target");
    if (target) target.textContent = currentScanRoot() || `All ${FOLDER_TYPE_LABELS[kind].toLowerCase()} folders`;
}

function renderScanMenu() {
    const menu = document.getElementById("scan-menu");
    if (!menu) return;
    const kind = scanKind();
    const paths = scanPaths(kind);
    const root = currentScanRoot();
    if (!paths.length) {
        menu.innerHTML = `<p class="muted">Add a ${FOLDER_TYPE_LABELS[kind].toLowerCase()} folder in Settings first.</p>`;
        return;
    }
    const items = [
        `<button type="button" data-action="choose-scan" data-root="" class="${root ? "" : "active"}">All ${escapeHtml(FOLDER_TYPE_LABELS[kind].toLowerCase())} folders</button>`,
        ...paths.map((path) => `<button type="button" data-action="choose-scan" data-root="${escapeHtml(path)}" class="${root === path ? "active" : ""}" title="${escapeHtml(path)}">${escapeHtml(path)}</button>`),
    ];
    menu.innerHTML = items.join("");
}

function scanButtonLabel(queue) {
    const root = currentScanRoot();
    const verb = queue ? "Queue" : "Scan";
    if (!root) return `${verb} | All ${FOLDER_TYPE_LABELS[scanKind()].toLowerCase()}`;
    return `${verb} | ${root}`;
}

async function startScanFromModal() {
    const mode = document.querySelector("input[name='scan-mode']:checked").value;
    const force = document.getElementById("scan-force").checked;
    const verbose = document.getElementById("scan-verbose");
    await scan(force, mode, !!(verbose && verbose.checked));
}

function schedulePoll(delay) {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(pollSystem, delay);
}

async function pollSystem() {
    const boot = typeof watchBoot === "function" ? watchBoot("system") : null;
    try {
    try {
        const data = await api("/api/system");
        state.scan = data.scan || {};
        state.scanQueue = data.scan_queue || [];
        state.system = data;
        if (data.video_scan) onVideoScanLive(data.video_scan);
        if (data.video_scrape) onVideoScrapeLive(data.video_scrape);
        state.mounts = data.mounts || [];
        state.offlinePaths = data.offline_paths || {};
        state.unreadablePaths = data.unreadable_paths || {};
        state.emptyPaths = data.empty_paths || {};
        noteOfflinePaths(state.offlinePaths);
        noteUnreadablePaths(state.unreadablePaths);
        noteEmptyPaths(state.emptyPaths);
        state.musicPaths = data.music_paths || [];
        state.moviePaths = data.movie_paths || [];
        state.tvPaths = data.tv_paths || [];
        if (state.scanRoot && !state.musicPaths.includes(state.scanRoot)) state.scanRoot = "";
        ["movies", "tv"].forEach((kind) => {
            if (state.videoScanRoots[kind] && !scanPaths(kind).includes(state.videoScanRoots[kind])) state.videoScanRoots[kind] = "";
        });
        renderScanButton(data.scan || {});
        renderFooter(data);
        const memory = data.memory || null;
        const stamp = memory ? `${memory.app_bytes || 0}:${memory.available_bytes || 0}` : "";
        if (stamp !== state.memoryStamp) {
            state.memoryStamp = stamp;
            if (typeof refreshInsightsMemory === "function") refreshInsightsMemory();
        }
        renderScanModal(data.scan || {});
        renderBatchProgress(data.batch || {});
        if (data.totals) setTotals(data.totals);
        noteLidarr(data);
        noteConnections(data);
        if (data.fill_missing_during_scan != null) state.fillMissingDuringScan = data.fill_missing_during_scan !== false;
        applyScanSteps();
        const lidarrPending = !!(data.lidarr && data.lidarr.pending);
        const running = data.scan && data.scan.status === "running";
        const batching = data.batch && data.batch.status === "running";
        const lookupStatus = (data.lookup && data.lookup.status) || "idle";
        const lookupBusy = lookupStatus === "running" || lookupStatus === "applying" || lookupStatus === "loading";
        const runningWork = (data.work || []).filter((job) => job.status === "running");
        state.workLive = runningWork;
        state.fileJob = data.file_job || null;
        const queuedWork = (data.work || []).some((job) => job.status === "queued");
        const working = runningWork.some((job) => job.kind !== "artwork");
        const artworkBusy = runningWork.some((job) => job.kind === "artwork");
        const latestMissing = (data.work || []).find((job) => job.kind === "missing-art");
        const latestArtistArt = (data.work || []).find((job) => job.kind === "missing-artist-art");
        const wasWorking = !!state.working;
        const missingJustDone = state.missingArtSeen === "running" && latestMissing && latestMissing.status !== "running";
        const artistArtJustDone = state.missingArtistArtSeen === "running" && latestArtistArt && latestArtistArt.status !== "running";
        if (missingJustDone && latestMissing.status === "completed") {
            notify(latestMissing.message || "Missing artwork download finished.", "info");
        } else if (missingJustDone && latestMissing.status === "failed") {
            notify(latestMissing.message || "Missing artwork download failed.", "error");
        }
        state.missingArtSeen = latestMissing ? latestMissing.status : "";
        if (artistArtJustDone && latestArtistArt.status === "completed") {
            notify(latestArtistArt.message || "Artist artwork download finished.", "info");
        } else if (artistArtJustDone && latestArtistArt.status === "failed") {
            notify(latestArtistArt.message || "Artist artwork download failed.", "error");
        }
        state.missingArtistArtSeen = latestArtistArt ? latestArtistArt.status : "";
        const artLive = (latestMissing && latestMissing.status === "running") || missingJustDone
            || (latestArtistArt && latestArtistArt.status === "running") || artistArtJustDone;
        if (artLive) await refreshLiveArtwork();
        const scanStatus = (data.scan && data.scan.status) || "idle";
        if (running && state.scanSeen !== "running") {
            state.scanLibraryToken = "";
            notify(`${scanKindLabel(data.scan)} music scan started.`, "info");
        }
        const scanJustFinished = state.scanSeen === "running" && scanStatus !== "running";
        state.scanSeen = scanStatus;
        if (running) refreshLibraryDuringScan(data.scan);
        syncScanPrompt(data.scan || {});
        if (scanJustFinished) state.libraryStale = true;
        renderJobs(data);
        if (data.file_job && typeof onVideoFilesLive === "function") onVideoFilesLive(data.file_job);
        const fileBusy = data.file_job && data.file_job.status === "running";
        state.working = !!working;
        state.backup = data.backup || { status: "idle", message: "" };
        const backupBusy = state.backup.status === "running" || state.backup.status === "waiting";
        noteBackupChange();
        const drawer = document.getElementById("job-drawer");
        const drawerOpen = drawer && !drawer.classList.contains("hidden");
        const batchWasRunning = !!state.batching;
        const videoBusy = data.video_scan && data.video_scan.status === "running";
        const scrapeBusy = data.video_scrape && data.video_scrape.status === "running" && !data.video_scrape.embedded;
        const scanQueued = (data.scan_queue || []).length > 0;
        if (running || videoBusy || scrapeBusy || scanQueued || fileBusy || batching || working || queuedWork || artworkBusy || lookupBusy || backupBusy || lidarrPending) {
            const batchDone = batchWasRunning && data.batch && data.batch.status === "completed";
            const batchFailed = batchWasRunning && data.batch && data.batch.status === "failed";
            state.scanning = !!running;
            state.batching = !!batching;
            syncActivity();
            syncBackupButton();
            if (batchDone || batchFailed) {
                if (batchDone) rememberProcessed([...state.selected]);
                fetchLibraryChanges().then(() => {
                    if (state.center === "album" && state.album) return selectAlbum(state.album.album.id, true);
                    if (state.center === "artist" && state.artistId) return selectArtist(state.artistId);
                });
                if (batchDone) showUndo("Album saved");
                else notify((data.batch && data.batch.message) || "Batch failed", "error");
            } else if (state.libraryStale && !running) {
                state.libraryStale = false;
                loadLibrary();
            }
            schedulePoll(state.stopping ? 700 : 1500);
            return;
        }
        if (state.scanning || state.batching || wasWorking || missingJustDone || artistArtJustDone || state.libraryStale) {
            const failedScan = (state.scanning || scanJustFinished) && data.scan && data.scan.status === "failed";
            const cancelledScan = (state.scanning || scanJustFinished) && data.scan && data.scan.status === "cancelled";
            const finishedScan = (state.scanning || scanJustFinished) && data.scan && data.scan.status === "completed";
            const finishedBatch = state.batching && data.batch && data.batch.status === "completed";
            state.scanning = false;
            state.stopping = false;
            state.batching = false;
            state.working = false;
            state.libraryStale = false;
            syncActivity();
            await loadLibrary();
            if (state.center === "album" && state.album) await selectAlbum(state.album.album.id, true);
            if (state.center === "artist" && state.artistId) await selectArtist(state.artistId);
            if (failedScan) notify(data.scan.message || "Scan failed", "error");
            else if (cancelledScan) notify("Scan stopped. Music already indexed was kept.", "info");
            else if (finishedScan) notify(`Scan finished for ${scannedPathLabel()}. ${data.scan.message || ""}`.trim(), "info");
            if (failedScan || cancelledScan || finishedScan) showScanResults(data.scan);
            if (finishedBatch) showUndo("Album saved");
        }
        syncActivity();
        syncBackupButton();
        const settingsModal = document.getElementById("settings-modal");
        const settingsOpen = settingsModal && !settingsModal.classList.contains("hidden");
        if (settingsOpen || drawerOpen || lidarrPending) schedulePoll(2000);
        else schedulePoll(5000);
    } catch (error) {
        const label = document.getElementById("activity-label");
        const host = document.getElementById("activity");
        if (label && host && host.classList.contains("is-idle")) label.textContent = error.message;
        schedulePoll(5000);
    }
    } finally {
        if (boot) boot.done();
    }
}

function noteBackupChange() {
    const backup = state.backup || {};
    const previous = state.backupSeen || "idle";
    state.backupSeen = backup.status || "idle";
    const wasBusy = previous === "running" || previous === "waiting";
    if (!wasBusy) return;
    if (backup.status === "completed") {
        const fallback = backup.kind === "import" ? "Music imported." : backup.kind === "restore" ? "Database restored." : "Database dump written.";
        notify(backup.message || fallback, "info");
        if (backup.kind === "import" || backup.kind === "restore") setTimeout(() => window.location.reload(), 1500);
    } else if (backup.status === "failed") {
        notify(backup.message || "The database operation failed.", "error");
    }
}

function syncBackupButton() {
    const button = document.getElementById("backup-now");
    const note = document.getElementById("backup-now-note");
    if (!button) return;
    const backup = state.backup || {};
    const scanRunning = !!state.scanning || state.scanSeen === "running";
    const backupBusy = backup.status === "running" || backup.status === "waiting";
    button.disabled = scanRunning || backupBusy;
    if (!note) return;
    if (scanRunning) note.textContent = "A scan is running. Backup now is available when the scan finishes. A scheduled dump waits for that scan.";
    else if (backup.status === "waiting") note.textContent = "Waiting for the scan to finish, then the dump will start.";
    else if (backup.status === "running") note.textContent = backup.message || "Writing the database dump.";
    else if (backup.status === "failed") note.textContent = backup.message || "Backup failed.";
    else if (backup.status === "completed") note.textContent = backup.message || "Database dump written.";
    else note.textContent = "";
}

async function backupNow() {
    const button = document.getElementById("backup-now");
    if (button && button.disabled) return;
    if (button) button.disabled = true;
    try {
        state.backup = await api("/api/backup", { method: "POST", body: {} });
        state.backupSeen = "running";
        syncBackupButton();
        notify("Backup started.", "info");
        pollSystem();
    } catch (error) {
        notify(error.message || "Backup did not start.", "error");
        syncBackupButton();
    }
}

function rememberProcessed(ids) {
    const wanted = new Set((ids || []).map(String));
    if (!wanted.size) return;
    (state.artists || []).forEach((artist) => {
        let touched = false;
        (artist.albums || []).forEach((album) => {
            if (!wanted.has(String(album.id))) return;
            album.status = "PROCESSED";
            touched = true;
        });
        if (touched) artist.status = "PROCESSED";
    });
    if (state.album && state.album.album && wanted.has(String(state.album.album.id))) {
        state.album.album.status = "PROCESSED";
    }
    renderTree();
    if (state.center === "album" && state.album) renderAlbum();
}

function refreshLibraryDuringScan(scan) {
    const result = (scan && scan.result) || {};
    const token = [
        Math.floor((Number(result.albums_scanned) || 0) / 50),
        Math.floor((Number(result.metadata_lookups) || 0) / 50),
        Math.floor((Number(result.artwork_lookups) || 0) / 50),
    ].join(":");
    if (!state.scanLibraryToken) {
        state.scanLibraryToken = token;
        return;
    }
    if (token === state.scanLibraryToken) return;
    state.scanLibraryToken = token;
    fetchLibraryChanges().then(() => refreshOpenDuringScan());
}

function fetchLibraryChanges() {
    if (!state.libraryAsOf) return loadLibrary();
    return api(`/api/library/changes?since=${encodeURIComponent(state.libraryAsOf)}`).then((data) => {
        applyLibraryChanges(data);
    }).catch(() => loadLibrary());
}

function applyLibraryChanges(data) {
    if (!data) return;
    const byId = new Map((state.artists || []).map((artist) => [String(artist.id), artist]));
    (data.artists || []).forEach((incoming) => {
        const existing = byId.get(String(incoming.id));
        if (!existing) {
            incoming.albums = incoming.albums || [];
            state.artists.push(incoming);
            byId.set(String(incoming.id), incoming);
            return;
        }
        const albums = existing.albums || [];
        Object.assign(existing, incoming);
        existing.albums = albums;
    });
    (data.albums || []).forEach((album) => {
        let placed = false;
        (state.artists || []).forEach((artist) => {
            const list = artist.albums || [];
            const index = list.findIndex((item) => String(item.id) === String(album.id));
            if (index < 0) return;
            if (String(artist.id) === String(album.artist_id)) {
                list[index] = album;
                placed = true;
            } else {
                list.splice(index, 1);
            }
        });
        if (placed) return;
        const artist = byId.get(String(album.artist_id));
        if (!artist) return;
        artist.albums = artist.albums || [];
        if (!artist.albums.some((item) => String(item.id) === String(album.id))) artist.albums.push(album);
    });
    if (data.as_of) state.libraryAsOf = data.as_of;
    renderTree();
}

function statusName(status) {
    const text = String(status || "").toLowerCase();
    if (text === "processed") return "PROCESSED";
    if (text === "ignored") return "IGNORED";
    return "NEW";
}

function paintAlbumStatus(ids, status) {
    const next = statusName(status);
    const wanted = new Set((ids || []).map(String));
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => {
            if (wanted.has(String(album.id))) album.status = next;
        });
    });
    if (state.album && state.album.album && wanted.has(String(state.album.album.id))) {
        state.album.album.status = next;
        if (state.center === "album") renderAlbum();
    }
    renderTree();
}

function paintArtistStatus(ids, status) {
    const next = statusName(status);
    const wanted = new Set((ids || []).map(String));
    (state.artists || []).forEach((artist) => {
        if (wanted.has(String(artist.id))) artist.status = next;
    });
    if (state.artistDetail && state.artistDetail.artist && wanted.has(String(state.artistDetail.artist.id))) {
        state.artistDetail.artist.status = next;
        if (state.center === "artist") renderArtist();
    }
    if (state.album && state.album.artist && wanted.has(String(state.album.artist.id))) {
        state.album.artist.status = next;
        if (state.center === "album") renderAlbum();
    }
    renderTree();
}

function refreshOpenDuringScan() {
    if (document.querySelector(".modal:not(.hidden)")) return;
    const active = document.activeElement;
    if (active && active.closest && active.closest("input, textarea, select, [contenteditable='true']")) return;
    if (state.bioEditing || state.artistNameEditing || state.proposal) return;
    if (state.center === "album" && state.album && state.album.album) {
        if (state.dirtyAlbums.has(state.album.album.id)) return;
        return selectAlbum(state.album.album.id, true);
    }
    if (state.center === "artist" && state.artistId) {
        if (state.dirtyArtists.has(state.artistId)) return;
        return selectArtist(state.artistId);
    }
}

function syncScanPrompt(scan) {
    const running = scan && scan.status === "running";
    const wait = running && scan.result && typeof scan.result === "object" ? scan.result.wait : null;
    if (!wait || !wait.kind || !wait.album_id) {
        state.scanPromptKey = "";
        state.scanPromptOpening = false;
        closeScanPromptModals();
        return;
    }
    const key = `${wait.kind}:${wait.album_id}`;
    const modalId = wait.kind === "artwork" ? "artwork-modal" : "match-modal";
    const modal = document.getElementById(modalId);
    const open = modal && !modal.classList.contains("hidden");
    if (state.scanPromptKey === key && (open || state.scanPromptOpening)) return;
    state.scanPromptKey = key;
    state.scanPromptAlbum = wait.album_id;
    state.scanPromptOpening = true;
    const opener = wait.kind === "artwork" ? openScanArtworkPrompt(wait) : openScanReleasePrompt(wait);
    Promise.resolve(opener).finally(() => {
        state.scanPromptOpening = false;
    });
}

function closeScanPromptModals() {
    ["match-modal", "artwork-modal"].forEach((id) => {
        const modal = document.getElementById(id);
        if (!modal || !modal.classList.contains("is-prompt")) return;
        modal.classList.add("hidden");
        modal.classList.remove("is-prompt");
    });
    const matchActions = document.getElementById("match-scan-actions");
    const artActions = document.getElementById("artwork-scan-actions");
    if (matchActions) matchActions.classList.add("hidden");
    if (artActions) artActions.classList.add("hidden");
}

async function openScanReleasePrompt(wait) {
    const modal = document.getElementById("match-modal");
    const host = document.getElementById("match-body");
    const actions = document.getElementById("match-scan-actions");
    document.getElementById("artwork-modal").classList.add("hidden");
    document.getElementById("artwork-modal").classList.remove("is-prompt");
    modal.classList.add("is-prompt");
    document.getElementById("match-title").textContent = "Choose a MusicBrainz release";
    host.innerHTML = `<p class="muted">Loading releases for ${escapeHtml(wait.label || "this album")}…</p>`;
    if (actions) {
        actions.classList.remove("hidden");
        actions.innerHTML = `<label class="choice"><input type="checkbox" id="scan-apply-match"> Apply match</label><button type="button" class="btn-ghost" data-action="skip-scan-release">Skip this album</button>`;
    }
    modal.classList.remove("hidden");
    try {
        const data = await api("/api/scan/prompt");
        const search = data.search || {};
        const albumId = data.album_id || wait.album_id;
        state.scanPromptAlbum = albumId;
        state.candidates = search.candidates || [];
        state.localTracks = search.local_tracks || [];
        rememberSearchComparison(albumId, state.localTracks, state.candidates);
        paintReleaseSearch(albumId, search, true, data.label || wait.label);
    } catch (error) {
        host.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function releaseCandidateButton(item, action) {
    return `<button type="button" class="candidate${item.locked ? " is-stored" : ""}" data-action="${action}" data-release="${escapeHtml(item.release_id)}">
        ${candidateScore(item)}
        <span class="candidate-copy"><strong>${escapeHtml(item.title || "")}</strong>${item.locked ? `<span class="badge-stored">Stored release</span>` : ""}<br><small>${escapeHtml([item.artist, item.year, releaseTypeLabel(item.type_label || item.type), countryLabel(item.country), item.edition, item.format, item.label].filter(Boolean).join(" · "))}</small></span>
        <span class="candidate-side"><small>${item.track_count || 0} tracks${item.acoustid_match ? " · AcoustID" : ""}${item.disc_match ? " · Disc ID" : ""}</small><small class="candidate-status"></small></span>
    </button>`;
}

function scanReleaseSubject(albumId, label, query) {
    state.scanPromptLabel = label || state.scanPromptLabel || "";
    return `<div class="compare-subject">
        <span class="compare-kicker">Comparing these results to</span>
        <span class="compare-line">${escapeHtml(state.scanPromptLabel)}</span>
        <button type="button" class="compare-hint" data-action="show-files" data-files-album="${escapeHtml(albumId)}">Show files on disk</button>
    </div>
    ${matchQueryForm(query)}
    <div class="compare-files hidden" data-compare-panel="${escapeHtml(albumId)}"></div>
    <p class="muted">Choose a release, or skip this album. Apply match also saves the Tags, .nfo, and Lyrics categories that are on in Settings.</p>`;
}

function focusScanCandidate(releaseId) {
    const albumId = state.scanPromptAlbum;
    if (!albumId || !releaseId) return;
    state.compareFocus[albumId] = releaseId;
    return runAction(() => showReleaseFiles(albumId), "Comparing tracks…");
}

async function chooseScanRelease(releaseId) {
    const buttons = [...document.querySelectorAll("#match-body .candidate")];
    const applyBox = document.getElementById("scan-apply-match");
    const apply = !!(applyBox && applyBox.checked);
    buttons.forEach((button) => {
        const picked = button.dataset.release === releaseId;
        button.classList.toggle("is-picked", picked);
        button.disabled = true;
        if (picked) {
            const status = button.querySelector(".candidate-status");
            if (status) status.textContent = apply ? "Applying this release…" : "Matching this release…";
        }
    });
    try {
        await answerScanPrompt({ action: "release", release_id: releaseId, apply });
    } catch (error) {
        buttons.forEach((button) => {
            button.disabled = false;
            button.classList.remove("is-picked");
            const status = button.querySelector(".candidate-status");
            if (status) status.textContent = "";
        });
        throw error;
    }
}

async function answerScanPrompt(body) {
    await api("/api/scan/prompt", { method: "POST", body });
}

function indexedAlbum(id) {
    const wanted = String(id || "");
    for (const artist of state.artists || []) {
        const album = (artist.albums || []).find((row) => String(row.id) === wanted);
        if (album) return { album, artistName: artist.name || "" };
    }
    return null;
}

function albumArtworkTitle(album, artistName) {
    const title = stripReleaseType(String((album && album.title) || "Album").trim()) || "Album";
    const year = album && album.release_year ? String(album.release_year).trim() : "";
    const withYear = year && !title.endsWith(year) ? `${title} (${year})` : title;
    const name = String(artistName || "").trim();
    return name ? `${name} — ${withYear}` : withYear;
}

async function openScanArtworkPrompt(wait) {
    const modal = document.getElementById("artwork-modal");
    const actions = document.getElementById("artwork-scan-actions");
    const releaseModal = document.getElementById("match-modal");
    releaseModal.classList.add("hidden");
    releaseModal.classList.remove("is-prompt");
    modal.classList.add("is-prompt");
    const found = indexedAlbum(wait.album_id);
    document.getElementById("artwork-title").textContent = found
        ? albumArtworkTitle(found.album, found.artistName)
        : (wait.label || "Album artwork");
    const searchText = found ? artworkSearchText(found.album, found.artistName) : (wait.label || "");
    setArtworkSearch(true, searchText, "album");
    state.artworkPick = null;
    state.artworkTarget = { subject: "album", albumId: wait.album_id, artistId: "" };
    document.getElementById("artwork-body").innerHTML = `<p class="muted">Loading artwork…</p>`;
    const scanCurrent = currentArtUrl("front", false);
    revealCompare(
        document.getElementById("art-compare"),
        document.getElementById("compare-current"),
        document.getElementById("compare-candidate"),
        document.getElementById("compare-label"),
        scanCurrent,
        scanCurrent,
        "Compare"
    );
    document.getElementById("art-zoom").classList.add("hidden");
    if (actions) {
        actions.classList.remove("hidden");
        actions.innerHTML = `<button type="button" data-action="continue-scan-artwork">Continue scan</button><button type="button" class="btn-ghost" data-action="skip-scan-artwork">Skip artwork</button>`;
    }
    modal.classList.remove("hidden");
    try {
        const data = await api(`/api/albums/${wait.album_id}/artwork`);
        syncArtworkQuery(data, searchText);
        paintArtworkResults(data, false);
    } catch (error) {
        document.getElementById("artwork-body").innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function renderFooter(data) {
    const scan = data.scan || { status: "idle", message: "Idle", processed: 0, total: 0 };
    const dbLabel = document.getElementById("db-label");
    if (dbLabel) dbLabel.textContent = "PostgreSQL";
    const progress = scan.total ? ` ${scan.processed || 0}/${scan.total}` : "";
    const dockScan = document.getElementById("dock-scan");
    if (dockScan && scanKind() === "music") {
        if (scan.status === "running") dockScan.title = `Scan progress: ${(scan.message || "Scanning")}${progress}`;
        else if (scan.status === "failed") dockScan.title = scan.message || "The last scan failed.";
        else dockScan.title = "Open the scan engine";
    }
    if (scanKind() !== "music") paintVideoScanFooter();
    if (scan.status === "running") state.scanning = true;
    renderScanButton(scan);
    if (scan.status === "failed" && /refusing to clear/i.test(scan.message || "")) {
        if (state.forceAlert !== scan.message) {
            state.forceAlert = scan.message;
            notify(scan.message, "warning", { action: "scan-force", label: "Clear index anyway" });
        }
    } else {
        state.forceAlert = "";
    }
}

function fillMissingDuringScan() {
    if (state.fillMissingDuringScan != null) return state.fillMissingDuringScan !== false;
    if (state.settings && state.settings.fill_missing_during_scan != null) {
        return state.settings.fill_missing_during_scan !== false;
    }
    return true;
}

function applyScanSteps() {
    const on = fillMissingDuringScan();
    document.querySelectorAll("#scan-steps [data-phase='metadata'], #scan-steps [data-phase='artwork']").forEach((step) => {
        step.classList.toggle("hidden", !on);
    });
}

function renderScanModal(scan) {
    if (typeof syncLibraryTools === "function") setTimeout(syncLibraryTools, 0);
    const modal = document.getElementById("scan-modal");
    if (modal.classList.contains("hidden")) return;
    applyScanSteps();
    const phases = fillMissingDuringScan() ? PHASES : PHASES.filter((phase) => phase !== "metadata" && phase !== "artwork");
    const current = phases.indexOf(scan.phase);
    document.querySelectorAll("#scan-steps span").forEach((step) => {
        if (step.classList.contains("hidden")) {
            step.classList.remove("done", "active");
            return;
        }
        const index = phases.indexOf(step.dataset.phase);
        const visible = index >= 0;
        step.classList.toggle("done", visible && (scan.status === "completed" || (current > index && current >= 0)));
        step.classList.toggle("active", visible && scan.status === "running" && current === index);
    });
    paintScanMeters("scan", scan);
    setScanLog(scan.log || scan.message || "Idle.");
    paintScanHeading("scan-title", "music", scanEngineTitle("music", scan.status === "running" ? scan.mode : selectedScanMode("scan-mode"), !!(scan.status === "running" ? scan.result && scan.result.force : document.getElementById("scan-force") && document.getElementById("scan-force").checked), scan.status === "running" ? (scan.result && scan.result.origin) : ""));
    const status = document.getElementById("scan-status");
    if (scan.status === "running") state.scanStatusCleared = null;
    const cleared = state.scanStatusCleared && state.scanStatusCleared === (scan.id || "idle") && scan.status !== "running";
    if (!cleared) {
        const banner = scanStatusCopy(scan);
        status.className = `scan-status${banner.tone ? ` ${banner.tone}` : ""}`;
        keepText(status, banner.text);
    }
    const running = scan.status === "running";
    if (!running && !cleared) {
        const wait = scanWaitNote("music");
        if (wait) keepText(status, wait);
    }
    lockScanMode(scan, running);
    const start = document.getElementById("scan-start");
    const queue = !running && (((state.videoScan || {}).status === "running") || (state.scanQueue || []).length > 0);
    start.disabled = running && state.stopping;
    start.classList.toggle("is-cancel", running);
    start.textContent = running ? (state.stopping ? "Stopping…" : "Cancel scan") : (queue ? "Queue scan" : "Start scan");
    start.dataset.action = running ? "cancel-scan" : "start-scan";
    paintScanClock("scan-clock", scan);
    armScanClock();
}

function libraryIsEmpty(media) {
    if (media === "music") {
        if (state.totals) return !(Number(state.totals.artists) || Number(state.totals.albums));
        if (state.libraryLoaded) return !(state.artists || []).length;
        return false;
    }
    const totals = (state.mediaTotals || {})[media];
    if (totals && typeof totals === "object") {
        if (media === "movies") return !Number(totals.movies);
        if (media === "tv") return !Number(totals.shows);
        if (media === "sets") return !Number(totals.sets);
    }
    const video = state.video || {};
    const rows = media === "tv" ? video.shows : media === "sets" ? video.sets : video.movies;
    if (Array.isArray(rows)) return rows.length === 0;
    return false;
}

function selectDefaultScanMode(radioName, media) {
    const value = libraryIsEmpty(media) ? "deep" : "incremental";
    const input = document.querySelector(`input[name="${radioName}"][value="${value}"]`);
    if (input) input.checked = true;
}

function applyScanModeChoices(radioName, media, running) {
    const empty = libraryIsEmpty(media);
    let checked = "";
    document.querySelectorAll(`input[name="${radioName}"]`).forEach((input) => {
        const block = input.closest(".scan-mode");
        const keep = !empty || input.value === "deep" || (running && input.checked);
        if (block) block.classList.toggle("hidden", !keep);
        if (!running) input.disabled = !keep;
        if (!keep) input.checked = false;
        else if (input.checked) checked = input.value;
    });
    if (!running && (empty || !checked)) selectDefaultScanMode(radioName, media);
}

function lockScanMode(scan, running) {
    const mode = scan.mode === "full" || scan.mode === "deep" ? scan.mode : "incremental";
    document.querySelectorAll("input[name='scan-mode']").forEach((input) => {
        if (running) input.checked = input.value === mode;
        input.disabled = !!running;
    });
    document.querySelectorAll("#scan-modal .scan-mode").forEach((block) => {
        block.classList.toggle("is-locked", !!running);
    });
    applyScanModeChoices("scan-mode", "music", !!running);
}

function scanLogSelectionHeld(node) {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount || !node) return false;
    const anchor = selection.anchorNode;
    return !!(anchor && node.contains(anchor));
}

function keepText(node, text) {
    if (!node || scanLogSelectionHeld(node)) return false;
    const next = text == null ? "" : String(text);
    if (node.textContent === next) return false;
    node.textContent = next;
    return true;
}

function replaceHtml(node, html) {
    if (!node || scanLogSelectionHeld(node) || node.innerHTML === html) return;
    node.innerHTML = html;
}

function setLogText(node, text) {
    if (!node || scanLogSelectionHeld(node)) return;
    const next = text == null ? "" : String(text);
    if (node.textContent === next) return;
    const atEnd = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    node.textContent = next;
    if (atEnd) node.scrollTop = node.scrollHeight;
}

function scanLogVisible(text) {
    const raw = String(text ?? "");
    const cut = state.scanLogCut;
    if (!cut) return raw;
    if (raw === cut) return "";
    if (raw.startsWith(cut)) return raw.slice(cut.length).replace(/^\n+/, "");
    state.scanLogCut = null;
    return raw;
}

function clearScanLog() {
    const node = document.getElementById("scan-log");
    state.scanLogCut = state.scanLogServer || (node ? node.textContent : "");
    state.scanStatusCleared = (state.scan && state.scan.id) || "idle";
    state.scanLogHeld = false;
    if (node) {
        node.textContent = "";
        node.scrollTop = 0;
    }
    const status = document.getElementById("scan-status");
    if (status) {
        status.className = "scan-status";
        status.textContent = "Ready to scan.";
    }
}

function setScanLog(text) {
    const node = document.getElementById("scan-log");
    if (!node) return;
    const raw = String(text ?? "");
    state.scanLogServer = raw;
    const shown = scanLogVisible(raw);
    if (scanLogSelectionHeld(node)) {
        state.scanLogHeld = true;
        return;
    }
    state.scanLogHeld = false;
    if (node.textContent === shown) return;
    const atEnd = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    node.innerHTML = scanLogHtml(shown);
    if (atEnd) node.scrollTop = node.scrollHeight;
}

function scanLogHtml(text) {
    return String(text).split("\n").map((line) => {
        const html = escapeHtml(line);
        if (line.includes("timestamped log in config/logs")) return `<span class="scan-log-note">${html}</span>`;
        return html;
    }).join("\n");
}

function scannedPathLabel() {
    if (state.scanScope) return state.scanScope;
    const paths = state.musicPaths || [];
    if (paths.length === 1) return paths[0];
    return "all music paths";
}

function scanIconMedia() {
    return state.media === "movies" || state.media === "sets" || state.media === "tv" ? state.media : "music";
}

function scanEngineIcon(media) {
    const glass = `<circle cx="17.3" cy="16.6" r="3.5"/><path d="m19.9 19.2 2.5 2.5"/>`;
    const marks = {
        music: `<path d="M7.2 20.2V11.4l8.6-1.5v7.6"/><circle cx="5.2" cy="20.2" r="2"/><circle cx="13.8" cy="18.8" r="2"/><circle cx="17.4" cy="5.3" r="3"/><path d="m19.6 3.2 2.5-1.8"/>`,
        movies: `<rect x="1.2" y="3.8" width="16.4" height="14.8" rx="1.6"/><path d="M5.5 3.8v14.8M13.4 3.8v14.8M1.2 8.2h4.3M1.2 14h4.3M13.4 8.2h4.2M13.4 14h4.2"/>${glass}`,
        sets: `<rect x="1" y="7.6" width="10.4" height="12.2" rx="1.3"/><path d="M4.4 7.6V5.5A1.2 1.2 0 0 1 5.6 4.3h9.4A1.2 1.2 0 0 1 16.2 5.5v10.2a1.2 1.2 0 0 1-1.2 1.2H12"/>${glass}`,
        tv: `<rect x="1.2" y="7.2" width="15.2" height="11.4" rx="1.6"/><path d="M5.2 2.8 8.6 7.2 12 2.8"/>${glass}`,
    };
    return `<svg class="scan-mark" viewBox="0 0 24 24" aria-hidden="true">${marks[media] || marks.music}</svg>`;
}

function paintScanHeading(id, media, text) {
    const title = document.getElementById(id);
    if (!title) return;
    const icon = title.querySelector("[data-scan-icon]");
    const label = title.querySelector("[data-scan-label]");
    if (!icon || !label) {
        title.textContent = text;
        return;
    }
    icon.innerHTML = scanEngineIcon(media);
    label.textContent = text;
}

const SCAN_ORIGINS = { manual: "Manual scan", scheduled: "Scheduled scan", webhook: "Webhook", "file job": "File job" };

function scanEngineTitle(media, mode, forced, origin) {
    const names = { music: "Music", movies: "Movies", tv: "TV Shows", sets: "Movie Sets" };
    const modes = { incremental: "Incremental deep", full: "Full", deep: "Deep" };
    const modeLabel = forced ? "Forced" : (modes[mode] || "Incremental deep");
    const from = SCAN_ORIGINS[origin] ? ` (${SCAN_ORIGINS[origin]})` : "";
    return `${names[media] || "Music"} - ${modeLabel} scan${from}`;
}

function selectedScanMode(name) {
    const picked = document.querySelector(`input[name='${name}']:checked`);
    return picked ? picked.value : "incremental";
}

function activeScanLabel() {
    if (state.scan && state.scan.status === "running") {
        return scanEngineTitle("music", state.scan.mode, !!(state.scan.result && state.scan.result.force), state.scan.result && state.scan.result.origin);
    }
    const video = state.videoScan || {};
    if (video.status === "running") return scanEngineTitle(video.media === "tv" ? "tv" : "movies", video.mode, false, video.origin);
    return "";
}

function scanWaitNote(media) {
    const active = activeScanLabel();
    const queued = (state.scanQueue || []).some((item) => item.media === media);
    if (queued && active) return `${active} is running. This scan is queued and will start when it finishes.`;
    if (queued) return "This scan is queued and will start when the current scan finishes.";
    if (active) return `${active} is running. Queue scan to run this one when it finishes.`;
    return "";
}

function scanKindLabel(scan) {
    const forced = !!(scan && scan.result && scan.result.force);
    if (forced) return "Forced";
    const mode = scan && scan.mode;
    if (mode === "full") return "Full";
    if (mode === "deep") return "Deep";
    return "Incremental deep";
}

function scanStatusCopy(scan) {
    const message = String(scan.message || "").trim();
    if (scan.status === "running") {
        const counts = scan.total ? `${scan.processed || 0}/${scan.total}` : "";
        const text = [`${scanKindLabel(scan)} scan`, "Running", message, counts].filter(Boolean).join(" · ");
        return { tone: "is-running", text };
    }
    if (scan.status === "completed") {
        const detail = message || "The library index was updated.";
        return { tone: "is-done", text: `Scan finished for ${scannedPathLabel()}. ${detail}` };
    }
    if (scan.status === "failed") return { tone: "is-failed", text: message ? `Last scan failed. ${message}` : "Last scan failed." };
    if (scan.status === "cancelled") return { tone: "is-stopped", text: message || "Scan stopped. Music already indexed was kept." };
    return { tone: "", text: "Ready to scan." };
}

function showScanResults(scan) {
    const modal = document.getElementById("scan-results-modal");
    if (!modal || !scan) return;
    const lists = scanIssueLists(scan);
    const title = document.getElementById("scan-results-title");
    const summary = document.getElementById("scan-results-summary");
    const lookupTitle = document.getElementById("scan-results-lookups-title");
    const lookupBox = document.getElementById("scan-results-lookups");
    const failureTitle = document.getElementById("scan-results-failures-title");
    const emptyTitle = document.getElementById("scan-results-empty-title");
    const failureBox = document.getElementById("scan-results-failures");
    const emptyBox = document.getElementById("scan-results-empty");
    const note = document.getElementById("scan-results-note");
    modal.querySelectorAll("[data-job]").forEach((button) => { button.dataset.job = "scan"; });
    if (title) {
        if (scan.status === "failed") title.textContent = "Scan failed";
        else if (scan.status === "cancelled") title.textContent = "Scan stopped";
        else title.textContent = "Scan results";
    }
    if (summary) {
        const banner = scanStatusCopy(scan);
        summary.className = `scan-status${banner.tone ? ` ${banner.tone}` : ""}`;
        summary.textContent = banner.text;
    }
    if (lookupTitle) lookupTitle.textContent = `Looked up (${lists.lookupCount})`;
    if (lookupBox) {
        lookupBox.textContent = lists.lookups.length ? lists.lookups.join("\n") : "No albums were looked up.";
    }
    if (failureTitle) failureTitle.textContent = `Failures (${lists.failureCount})`;
    if (emptyTitle) emptyTitle.textContent = `Empty folders (${lists.emptyCount})`;
    if (failureBox) {
        failureBox.textContent = lists.failures.length
            ? lists.failures.map(failureLine).join("\n")
            : "No failures.";
    }
    if (emptyBox) {
        emptyBox.textContent = lists.empty.length ? lists.empty.join("\n") : "No empty folders.";
    }
    [[lookupBox, lists.lookups.length], [failureBox, lists.failures.length], [emptyBox, lists.empty.length]].forEach(([box, count]) => {
        if (box) box.classList.toggle("is-empty", !count);
    });
    if (note) {
        const clipped = lists.failureCount > lists.failures.length
            || lists.emptyCount > lists.empty.length
            || lists.lookupCount > lists.lookups.length;
        note.textContent = clipped
            ? "The window shows the first 200 of each list. The full list is written to a timestamped log in config/logs when the scan finishes."
            : "These lines are kept in the scan log and written to a timestamped file in config/logs when the scan finishes.";
    }
    modal.classList.remove("hidden");
}

function scanIssueLists(scan) {
    const result = scan.result && typeof scan.result === "object" ? scan.result : {};
    const failures = Array.isArray(result.failures) ? result.failures.slice() : [];
    const empty = Array.isArray(result.empty_folders) ? result.empty_folders.slice() : [];
    if (!failures.length && !empty.length && scan.log) {
        String(scan.log).split("\n").forEach((line) => {
            if (line.startsWith("Failed:")) failures.push(line.slice(7).trim());
            else if (line.startsWith("Empty folder:")) empty.push(line.slice("Empty folder:".length).trim());
        });
    }
    const lookups = Array.isArray(result.lookups) ? result.lookups.slice() : [];
    const failureCount = Number.isInteger(result.failure_count) ? result.failure_count : failures.length;
    const emptyCount = Number.isInteger(result.empty_count) ? result.empty_count : empty.length;
    const lookupCount = Number.isInteger(result.lookup_count) ? result.lookup_count : lookups.length;
    return { failures, empty, lookups, failureCount, emptyCount, lookupCount };
}

function failureLine(item) {
    if (typeof item === "string") return item;
    const path = item && item.path ? item.path : "";
    const error = item && item.error ? item.error : "";
    return error ? `${path}: ${error}` : path;
}

function renderScanButton(scan) {
    const button = document.getElementById("scan-btn");
    const label = document.getElementById("scan-label");
    if (!button || !label) return;
    const kind = scanKind();
    const video = kind !== "music";
    const running = ownScanRunning();
    const stopping = video ? state.videoStopping : state.stopping;
    const queue = !running && otherScanActive();
    button.classList.toggle("is-cancel", running);
    button.disabled = running && stopping;
    label.textContent = running ? (stopping ? "Stopping…" : "Cancel") : scanButtonLabel(queue);
    const icon = scanEngineIcon(scanIconMedia());
    const mark = document.getElementById("scan-mark");
    const dockMark = document.getElementById("dock-scan-mark");
    if (mark) mark.innerHTML = icon;
    if (dockMark) dockMark.innerHTML = icon;
    button.title = running ? "Stop the scan" : (queue ? "Queue this scan until the current one finishes" : (currentScanRoot() || `Scan all ${FOLDER_TYPE_LABELS[kind].toLowerCase()} folders`));
    const toggle = document.getElementById("scan-toggle");
    if (toggle) toggle.classList.toggle("hidden", running);
    const cancel = document.getElementById("dock-cancel");
    if (cancel) cancel.classList.toggle("hidden", !running);
}

let scanClockTimer = 0;
let scanReport = { name: "", text: "" };

function scanStamp(value) {
    if (!value) return NaN;
    const parsed = Date.parse(String(value).replace(" ", "T"));
    return Number.isFinite(parsed) ? parsed : NaN;
}

function formatSpan(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    const pad = (value) => String(value).padStart(2, "0");
    if (hours) return `${hours}:${pad(minutes)}:${pad(seconds)}`;
    return `${minutes}:${pad(seconds)}`;
}

const PHASE_LABELS = {
    directory: "Directory walk",
    delta: "Changed files",
    musicbrainz: "MusicBrainz",
    sidecars: "Sidecar audit",
    metadata: "Metadata",
    artwork: "Artwork",
    walk: "Folders and files",
    read: "Folders and files",
    lookup: "Metadata and artwork",
    trailers: "Trailers",
    nfo: "Write .nfo",
};

function phaseLabel(phase) {
    return PHASE_LABELS[phase] || "This stage";
}

function scanPhasePlan(scan) {
    if (!scan || scan.media === "sets") return [];
    if (scan.media === "movies" || scan.media === "tv") {
        const cfg = typeof videoCfg === "function" ? videoCfg() : {};
        const fill = cfg.scan_fill_missing !== false;
        const trailers = scan.media === "tv" ? !!cfg.scan_download_tv_trailers : !!cfg.scan_download_trailers;
        const parallel = !!(scan.trailers_alongside || scan.trailers_done);
        return ["walk", "read"].concat(fill ? ["lookup"] : []).concat(trailers && !parallel ? ["trailers"] : []).concat(["nfo"]);
    }
    return fillMissingDuringScan() ? PHASES.slice() : PHASES.filter((phase) => phase !== "metadata" && phase !== "artwork");
}

const VIDEO_FILE_WALK = 0.15;
const VIDEO_STAGE_WEIGHT = { walk: 10, read: 45, lookup: 40, trailers: 5, nfo: 5 };

function ratio(done, total) {
    const whole = Number(total) || 0;
    if (whole <= 0) return 0;
    return Math.max(0, Math.min(1, (Number(done) || 0) / whole));
}

function videoFolderPart(scan) {
    if ((Number(scan.folders_total) || 0) > 0) return ratio(scan.folders_done, scan.folders_total);
    return scan.phase === "walk" ? 0 : 1;
}

function videoFilePart(scan) {
    if (scan.phase === "walk" && !(Number(scan.files_total) > 0)) return 0;
    if ((Number(scan.files_total) || 0) > 0) return ratio(scan.files_done, scan.files_total);
    if (scan.phase === "read" && (Number(scan.total) || 0) > 0) return ratio(scan.processed, scan.total);
    return scan.phase === "cleanup" ? 1 : 0;
}

function stageFraction(scan) {
    if (!scan || scan.status === "completed") return 1;
    if ((scan.media === "movies" || scan.media === "tv") && (scan.phase === "walk" || scan.phase === "read" || scan.phase === "cleanup")) {
        return VIDEO_FILE_WALK * videoFolderPart(scan) + (1 - VIDEO_FILE_WALK) * videoFilePart(scan);
    }
    return ratio(scan.processed, scan.total);
}

function paceFraction(scan) {
    if (scan && (scan.media === "movies" || scan.media === "tv")) {
        if (scan.phase === "walk" && (Number(scan.files_done) || 0) > 0) return videoFilePart(scan);
        if (scan.phase === "walk") return videoFolderPart(scan);
        if (scan.phase === "read" || scan.phase === "cleanup") return videoFilePart(scan);
    }
    return stageFraction(scan);
}

function stageSeconds(scan) {
    const start = scanStamp(scan && scan.pace && scan.pace.phase_started_at);
    if (!Number.isFinite(start)) return 0;
    const running = scan.status === "running";
    const finished = scanStamp(scan.finished_at);
    const end = running ? Date.now() : (Number.isFinite(finished) ? finished : Date.now());
    return Math.max(0, (end - start) / 1000);
}

function stageWeight(scan, phase, place, index, fraction) {
    const pace = scan.pace || {};
    const done = (pace.done || {})[phase];
    const history = (pace.history || {})[phase];
    if (place < index && done && Number(done.seconds) > 0) return Number(done.seconds);
    if (place < index && history && Number(history.avg_seconds) > 0) return Number(history.avg_seconds);
    if (place === index) {
        const elapsed = stageSeconds(scan);
        if (fraction > 0.02 && elapsed > 0) return elapsed / fraction;
        if (history && Number(history.avg_seconds) > 0) return Number(history.avg_seconds);
    }
    if (place > index && history && Number(history.avg_seconds) > 0) return Number(history.avg_seconds);
    return 60;
}

function videoScanFraction(scan, plan) {
    if (scan.status === "completed") return 1;
    const phase = scan.phase === "cleanup" ? "read" : scan.phase;
    const index = plan.indexOf(phase);
    if (index < 0) return stageFraction(scan);
    const weights = plan.map((name) => VIDEO_STAGE_WEIGHT[name] || 5);
    const total = weights.reduce((sum, value) => sum + value, 0);
    const done = weights.reduce((sum, weight, place) => {
        if (place < index) return sum + weight;
        if (place > index) {
            if (phase === "walk" && plan[place] === "read" && (Number(scan.files_total) || 0) > 0) {
                return sum + weight * videoFilePart(scan);
            }
            return sum;
        }
        if (plan[place] === "walk") return sum + weight * videoFolderPart(scan);
        if (plan[place] === "read") return sum + weight * videoFilePart(scan);
        return sum + weight * ratio(scan.processed, scan.total);
    }, 0);
    return total ? Math.max(0, Math.min(1, done / total)) : 0;
}

function scanFraction(scan, plan, fraction) {
    if (!plan.length) return fraction;
    if (scan.status === "completed") return 1;
    if (scan && (scan.media === "movies" || scan.media === "tv")) return videoScanFraction(scan, plan);
    const index = plan.indexOf(scan.phase);
    if (index < 0) return fraction;
    const weights = plan.map((phase, place) => stageWeight(scan, phase, place, index, fraction));
    const total = weights.reduce((sum, value) => sum + value, 0);
    if (!total) return fraction;
    const done = weights.reduce((sum, weight, place) => {
        if (place < index) return sum + weight;
        if (place === index) return sum + weight * fraction;
        return sum;
    }, 0);
    return Math.max(0, Math.min(1, done / total));
}

function remainEstimate(scan, plan, fraction) {
    if (!scan || scan.status !== "running") return { seconds: null, whole: false };
    const index = plan.indexOf(scan.phase);
    if (!plan.length || index < 0) {
        const started = scanStamp(scan.started_at);
        if (fraction > 0 && fraction < 1 && Number.isFinite(started)) {
            const spent = Math.max(0, (Date.now() - started) / 1000);
            return { seconds: spent * (1 - fraction) / fraction, whole: true };
        }
        return { seconds: null, whole: false };
    }
    const elapsed = stageSeconds(scan);
    let seconds = 0;
    let whole = true;
    if (fraction > 0 && fraction < 1 && elapsed > 0) seconds += elapsed * (1 - fraction) / fraction;
    else if (fraction <= 0) {
        const history = ((scan.pace || {}).history || {})[scan.phase];
        if (history && Number(history.avg_seconds) > 0) seconds += Number(history.avg_seconds);
        else whole = false;
    }
    for (let place = index + 1; place < plan.length; place++) {
        const history = ((scan.pace || {}).history || {})[plan[place]];
        if (history && Number(history.avg_seconds) > 0) seconds += Number(history.avg_seconds);
        else whole = false;
    }
    if (!whole && !(fraction > 0 && fraction < 1)) return { seconds: null, whole: false };
    return { seconds, whole };
}

function percentText(value) {
    return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function paintScanMeters(prefix, scan) {
    const plan = scanPhasePlan(scan || {});
    const fraction = stageFraction(scan || {});
    const overall = scanFraction(scan || {}, plan, fraction);
    const failed = scan && scan.status === "failed";
    const stopped = scan && scan.status === "cancelled";
    const totalBar = document.getElementById(`${prefix}-total-progress`);
    const stageBar = document.getElementById(`${prefix}-progress`);
    const totalLabel = document.getElementById(`${prefix}-total-label`);
    const stageLabel = document.getElementById(`${prefix}-stage-label`);
    [totalBar, stageBar].forEach((bar) => {
        if (!bar) return;
        bar.classList.toggle("low", !!failed);
        bar.classList.toggle("warn", !!stopped);
    });
    if (totalBar) totalBar.style.width = `${Math.round(overall * 100)}%`;
    if (stageBar) stageBar.style.width = `${Math.round(fraction * 100)}%`;
    if (totalLabel) totalLabel.textContent = `Scan ${percentText(overall)}`;
    if (stageLabel) {
        const countPart = (scan && scan.total > 0) ? ` ${scan.processed || 0}/${scan.total}` : "";
        stageLabel.textContent = `${phaseLabel(scan && scan.phase)}${countPart} ${percentText(fraction)}`;
    }
}

function formatScanClockTime(date, now = new Date(), isPast = false) {
    if (!date || isNaN(date.getTime())) return "";
    const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const nowDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const targetDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const dayDiff = Math.round((targetDay - nowDay) / 86400000);

    if (dayDiff === 0) {
        return `today, ${time}`;
    }
    const hasDiffYear = date.getFullYear() !== now.getFullYear();
    const dateOpts = {
        weekday: "short",
        month: "short",
        day: "numeric",
        ...(hasDiffYear ? { year: "numeric" } : {}),
    };
    const dateStr = date.toLocaleDateString([], dateOpts);
    if (dayDiff > 0) {
        const dayLabel = `+${dayDiff} day${dayDiff === 1 ? "" : "s"}`;
        return `${dateStr}, ${time} (${dayLabel})`;
    }
    const absDiff = Math.abs(dayDiff);
    const dayLabel = `-${absDiff} day${absDiff === 1 ? "" : "s"}`;
    return isPast ? `${dateStr}, ${time}` : `${dateStr}, ${time} (${dayLabel})`;
}

function scanClockCopy(scan) {
    const start = scanStamp(scan && scan.started_at);
    if (!Number.isFinite(start)) return "";
    const paused = scan.status === "paused";
    const running = scan.status === "running" || paused;
    const finished = scanStamp(scan.finished_at);
    const end = running ? Date.now() : (Number.isFinite(finished) ? finished : Date.now());
    const elapsed = Math.max(0, end - start);
    let line = `Duration ${formatSpan(elapsed)}`;
    if (paused) return `${line} · Paused for queued imports`;
    if (!running) {
        if (Number.isFinite(finished)) {
            const clock = formatScanClockTime(new Date(finished), new Date(), true);
            line += ` · Finished ${clock}`;
        }
        return line;
    }
    const plan = scanPhasePlan(scan);
    const fraction = stageFraction(scan);
    const overall = scanFraction(scan, plan, fraction);
    const estimate = remainEstimate(scan, plan, paceFraction(scan));
    line += ` · This stage ${formatSpan(stageSeconds(scan) * 1000)}`;
    line += ` · Scan ${percentText(overall)} · ${phaseLabel(scan.phase)} ${percentText(fraction)}`;
    if (estimate.seconds == null) line += " · Estimate after the first items";
    else if (!estimate.whole) line += ` · About ${formatSpan(estimate.seconds * 1000)} left in this stage`;
    else if (estimate.seconds > 0) {
        const finish = new Date(Date.now() + estimate.seconds * 1000);
        const clock = formatScanClockTime(finish);
        line += ` · About ${formatSpan(estimate.seconds * 1000)} left · Finishes ${clock}`;
    }
    return line;
}

function paintScanClock(id, scan) {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = scanClockCopy(scan || {});
}

function paintScanClocks() {
    const music = document.getElementById("scan-modal");
    const video = document.getElementById("video-scan-modal");
    const musicOpen = music && !music.classList.contains("hidden");
    const videoOpen = video && !video.classList.contains("hidden");
    if (musicOpen) paintScanClock("scan-clock", state.scan || {});
    if (videoOpen) {
        const scrape = state.videoScrape || {};
        const sets = state.videoScanFocus === "sets" && scrape.media === "sets";
        const shown = sets ? scrape : (typeof videoScanFor === "function" ? videoScanFor(state.videoScanFocus) : (state.videoScan || {}));
        paintScanClock("video-scan-clock", shown);
    }
    const musicLive = musicOpen && (state.scan || {}).status === "running";
    const videoLive = videoOpen && (((state.videoScan || {}).status === "running") || (state.videoPaused && state.videoPaused.media));
    const setsLive = videoOpen && state.videoScanFocus === "sets" && (state.videoScrape || {}).status === "running";
    if (!musicLive && !videoLive && !setsLive && scanClockTimer) {
        clearInterval(scanClockTimer);
        scanClockTimer = 0;
    }
}

function armScanClock() {
    paintScanClocks();
    if (scanClockTimer) return;
    scanClockTimer = setInterval(paintScanClocks, 1000);
}

function scanBytes(size) {
    const bytes = Number(size) || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function openScanHistory(targetMedia) {
    const list = document.getElementById("scan-history-list");
    const modal = document.getElementById("scan-history-modal");
    if (!list || !modal) return;
    const scanModalOpen = document.getElementById("scan-modal") && !document.getElementById("scan-modal").classList.contains("hidden");
    const media = targetMedia || (
        scanModalOpen
            ? "music"
            : (state.videoScanFocus || (scanKind() === "tv" ? "tv" : (state.media === "sets" ? "sets" : "movies")))
    );
    state.scanHistoryMedia = media;
    const title = document.getElementById("scan-history-title");
    const labels = { music: "Music", movies: "Movie", tv: "TV", sets: "Movie set" };
    const label = labels[media] || "";
    if (title) title.textContent = label ? `Saved ${label.toLowerCase()} scans` : "Saved scans";
    list.innerHTML = `<p class="muted">Loading saved scans…</p>`;
    modal.classList.remove("hidden");
    try {
        const query = media ? `?media=${encodeURIComponent(media)}` : "";
        const data = await api(`/api/v1/scan/logs${query}`);
        const logs = data.logs || [];
        if (!logs.length) {
            const noun = label ? `${label.toLowerCase()} ` : "";
            list.innerHTML = `<p class="muted">No saved ${noun}scans yet. A finished scan writes a report under config/logs.</p>`;
            return;
        }
        list.innerHTML = logs.map((item) => `
            <button type="button" class="scan-history-row" data-action="open-scan-report" data-name="${escapeHtml(item.name)}">
                <span>${escapeHtml(item.label || "Scan")}</span>
                <span class="muted">${escapeHtml(item.when || item.name)}</span>
                <span class="muted">${scanBytes(item.bytes)}</span>
            </button>
        `).join("");
    } catch (error) {
        list.innerHTML = `<p class="muted">${escapeHtml(error.message || "Saved scans could not be loaded.")}</p>`;
    }
}

async function openScanReport(name) {
    const body = document.getElementById("scan-report-body");
    const title = document.getElementById("scan-report-title");
    const modal = document.getElementById("scan-report-modal");
    if (!body || !modal || !name) return;
    scanReport = { name, text: "" };
    title.textContent = "Scan report";
    body.textContent = "Loading…";
    modal.classList.remove("hidden");
    try {
        const data = await api(`/api/v1/scan/logs/${encodeURIComponent(name)}`);
        scanReport = { name: data.name || name, text: data.text || "" };
        title.textContent = [data.label || "Scan", data.when || data.name].filter(Boolean).join(" · ");
        body.textContent = scanReport.text || "This report is empty.";
    } catch (error) {
        body.textContent = error.message || "That report could not be opened.";
        notify(error.message || "That report could not be opened.", "error");
    }
}

async function copyScanReport() {
    const text = scanReport.text || "";
    if (!text) return notify("This report is empty.", "warning");
    try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
        else copyPlainText(text);
        notify("Scan report copied.", "info");
    } catch (error) {
        try {
            copyPlainText(text);
            notify("Scan report copied.", "info");
        } catch (fallback) {
            notify("The report could not be copied.", "error");
        }
    }
}

function exportScanReport() {
    const text = scanReport.text || "";
    if (!text) return notify("This report is empty.", "warning");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = scanReport.name || "scan-report.log";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
}


async function copyScanResults() {
    const text = (id) => ((document.getElementById(id) || {}).textContent || "").trim();
    const block = (titleId, bodyId) => {
        const body = text(bodyId);
        return body ? `${text(titleId)}\n${body}` : text(titleId);
    };
    const parts = [
        text("scan-results-summary"),
        block("scan-results-lookups-title", "scan-results-lookups"),
        block("scan-results-failures-title", "scan-results-failures"),
        block("scan-results-empty-title", "scan-results-empty"),
    ].filter(Boolean);
    try {
        await navigator.clipboard.writeText(parts.join("\n\n"));
        notify("Scan results copied.", "success");
    } catch (error) {
        notify("The results could not be copied. Select the text and copy it by hand.", "warning");
    }
}
