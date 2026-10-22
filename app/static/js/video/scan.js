state.videoScan = { status: "idle", message: "Idle" };
state.videoScans = {
    movies: { status: "idle", message: "Idle", media: "movies", log: "" },
    tv: { status: "idle", message: "Idle", media: "tv", log: "" },
    sets: { status: "idle", message: "Idle", media: "sets", log: "" },
};
state.videoStopping = false;
state.videoScanTimer = 0;
state.videoScanReloaded = 0;

function videoScanRunning() {
    return (state.videoScan || {}).status === "running" || !!(state.videoPaused && state.videoPaused.media);
}

function videoScanNoun(media) {
    return media === "tv" ? "TV" : "movie";
}

function videoScanFor(media) {
    if (media === "sets") {
        const scrape = state.videoScrape || {};
        if (scrape.media === "sets" && (scrape.status === "running" || scrape.status === "paused")) {
            return scrape;
        }
        const savedSets = (state.videoScans && state.videoScans.sets) || {};
        if (savedSets.media === "sets" && (savedSets.log || (savedSets.status && savedSets.status !== "idle"))) {
            return savedSets;
        }
        return scrape.media === "sets" ? scrape : (savedSets.media === "sets" ? savedSets : { status: "idle", message: "Idle", media: "sets", log: "" });
    }
    const parked = state.videoPaused || {};
    if (parked.media === media) return parked;
    const live = state.videoScan || {};
    if (live.media === media && (live.status === "running" || live.status === "paused")) {
        return live;
    }
    const saved = (state.videoScans && state.videoScans[media]) || {};
    if (saved.media === media && (saved.log || (saved.status && saved.status !== "idle"))) {
        return saved;
    }
    if (live.media === media) return live;
    return saved.media === media ? saved : { status: "idle", message: "Idle", media: media || "", log: "" };
}

function openVideoScanModal(media) {
    const kind = media === "sets" || media === "movies" || media === "tv"
        ? media
        : (state.media === "sets" ? "sets" : (scanKind() === "tv" ? "tv" : "movies"));
    state.videoScanFocus = kind;
    const scan = videoScanFor(kind);
    const setsRunning = kind === "sets" && (state.videoScrape || {}).status === "running" && (state.videoScrape || {}).media === "sets";
    const fileRunning = kind !== "sets" && (scan.status === "running" || scan.status === "paused") && scan.media === kind;
    if (!setsRunning && !fileRunning) selectDefaultScanMode("video-scan-mode", kind);
    const showingRun = kind !== "sets" && scan.status === "running" && scan.media === kind;
    const root = showingRun ? ((scan.roots || []).length === 1 ? scan.roots[0] : "") : currentScanRoot();
    const target = kind === "sets" ? "All movie sets" : (root || `All ${FOLDER_TYPE_LABELS[kind].toLowerCase()} folders`);
    document.getElementById("video-scan-target").textContent = target;
    document.getElementById("video-scan-modal").classList.remove("hidden");
    renderVideoScanModal();
    if (kind === "sets") pollVideoScrape();
    else pollVideoScan();
}

async function startVideoScanFromModal() {
    const picked = document.querySelector("input[name='video-scan-mode']:checked");
    const mode = picked ? picked.value : "incremental";
    if (state.videoScanFocus === "sets") {
        state.setScanMode = mode;
        const data = await api("/api/v1/scrape", {
            method: "POST",
            body: {
                media: "sets",
                scope: mode === "incremental" ? "missing" : "all",
                policy: mode === "deep" ? "overwrite" : (mode === "full" ? "merge" : null),
            },
        });
        noteScrapeStart(data);
        renderVideoScanModal();
        return;
    }
    const media = state.videoScanFocus === "tv" || state.videoScanFocus === "movies" ? state.videoScanFocus : (state.media === "tv" ? "tv" : "movies");
    const root = (state.videoScanRoots && state.videoScanRoots[media]) || "";
    const verbose = document.getElementById("video-scan-verbose");
    const data = await api("/api/v1/scan", {
        method: "POST",
        body: { media, mode: mode, roots: root ? [root] : [], verbose: !!(verbose && verbose.checked) },
    });
    if (data.queued) {
        state.scanQueue = data.scan_queue || state.scanQueue || [];
        const name = FOLDER_TYPE_LABELS[state.videoScanFocus || scanKind()] || "Video";
        notify(data.duplicate ? `That ${name.toLowerCase()} scan is already queued.` : `${name} scan queued. It starts when the current scan finishes.`, "info");
        renderScanButton(state.scan || {});
        renderVideoScanModal();
        pollSystem();
        return;
    }
    if (!data.started) notify(`A ${videoScanNoun(data.scan && data.scan.media)} scan is already running.`, "info");
    state.videoStopping = false;
    applyVideoScan(data.scan || {});
    pollVideoScan();
}

async function openPendingMatches() {
    const focus = state.videoScanFocus === "tv" ? "tv" : "movies";
    const data = await api(`/api/v1/match/pending?media=${focus}`);
    const items = data.items || [];
    if (!items.length) {
        notify("Nothing is waiting for Apply match.", "info");
        return;
    }
    document.getElementById("pending-match-title").textContent = `Apply match (${items.length})`;
    document.getElementById("pending-match-list").innerHTML = `<table class="data-table"><thead><tr><th>Title</th><th>Type</th><th>Folder</th><th></th></tr></thead><tbody>${items.map((item) => `<tr data-pending-id="${escapeHtml(item.id)}">
        <td>${escapeHtml(item.title || "")}${item.year ? ` (${escapeHtml(String(item.year))})` : ""}</td>
        <td>${item.kind === "movie" ? "Movie" : "TV show"}</td>
        <td class="mono">${escapeHtml(item.path || "")}</td>
        <td class="pending-match-actions"><button type="button" class="btn-ghost" data-action="video-scrape-fix" data-kind="${escapeHtml(item.kind)}" data-id="${escapeHtml(item.id)}">Fix match…</button>
        <button type="button" class="btn-ghost" data-action="video-pending-match-remove" title="Leave this one out of Apply all. It stays waiting.">Remove</button></td>
    </tr>`).join("")}</tbody></table>`;
    document.getElementById("pending-match-modal").classList.remove("hidden");
}

function pendingMatchIds() {
    return [...document.querySelectorAll("#pending-match-list tr[data-pending-id]")].map((row) => row.dataset.pendingId);
}

function removePendingMatchRow(button) {
    const row = button.closest("tr");
    if (row) row.remove();
    const left = pendingMatchIds().length;
    document.getElementById("pending-match-title").textContent = left ? `Apply match (${left})` : "Apply match";
    const apply = document.querySelector("[data-action='video-apply-match-confirm']");
    if (apply) apply.disabled = !left;
}

async function applyPendingMatches(ids) {
    const data = await api("/api/v1/match/apply", { method: "POST", body: ids ? { ids } : {} });
    if (data.scrape) noteScrapeStart(data);
    notify("Apply match is writing the held movies and shows.", "info");
    renderVideoScanModal();
}

async function cancelVideoScan() {
    if (state.videoScanFocus === "sets") return cancelVideoScrape();
    const focused = videoScanFor(state.videoScanFocus);
    if (focused.status !== "running" && focused.status !== "paused") return;
    const interrupt = !!focused.interrupt;
    state.videoStopping = true;
    renderScanButton({});
    renderVideoScanModal();
    try {
        await api(interrupt ? "/api/v1/scan/cancel-import" : "/api/v1/scan/cancel", { method: "POST", body: {} });
        notify(interrupt ? "Stopping the import scan." : "Stopping the scan. Items already read stay in the library.", "info");
    } catch (error) {
        state.videoStopping = false;
        notify(error.message, "error");
    }
    pollVideoScan();
}

async function pollVideoScan() {
    const boot = typeof watchBoot === "function" ? watchBoot("scan") : null;
    clearTimeout(state.videoScanTimer);
    const ticket = (state.videoScanTicket = (state.videoScanTicket || 0) + 1);
    let data;
    try {
        try {
            const focus = state.videoScanFocus === "tv" ? "tv" : "movies";
            data = await api(`/api/v1/scan/status?media=${encodeURIComponent(focus)}`);
        } catch (error) {
            return;
        }
        if (ticket !== state.videoScanTicket) return;
        try {
            applyVideoScan(data);
        } catch (err) {
            console.error("applyVideoScan error", err);
        }
        if (videoScanRunning()) state.videoScanTimer = setTimeout(pollVideoScan, state.videoStopping ? 700 : 1500);
    } finally {
        if (boot) boot.done();
    }
}

function onVideoScanLive(snapshot) {
    const wasRunning = videoScanRunning();
    applyVideoScan(snapshot || {});
    if (!wasRunning && videoScanRunning()) pollVideoScan();
}

function applyVideoScan(scan) {
    const incoming = scan || {};
    const paused = incoming.paused_scan || null;
    const live = { ...incoming };
    delete live.paused_scan;
    const previous = state.videoScan || {};
    if (live.pending_match_movies !== undefined || live.pending_match_tv !== undefined) {
        state.videoPending = { movies: Number(live.pending_match_movies || 0), tv: Number(live.pending_match_tv || 0) };
    }
    const log = live.log !== undefined ? live.log : previous.log;
    state.videoScan = { ...live, log };

    if (!state.videoScans) state.videoScans = {};
    if (incoming.scans) {
        if (incoming.scans.movies) {
            const prevM = state.videoScans.movies || {};
            const mLog = incoming.scans.movies.log !== undefined ? incoming.scans.movies.log : prevM.log;
            state.videoScans.movies = { ...prevM, ...incoming.scans.movies, log: mLog };
        }
        if (incoming.scans.tv) {
            const prevT = state.videoScans.tv || {};
            const tLog = incoming.scans.tv.log !== undefined ? incoming.scans.tv.log : prevT.log;
            state.videoScans.tv = { ...prevT, ...incoming.scans.tv, log: tLog };
        }
    }
    if (live.media && (live.media === "movies" || live.media === "tv")) {
        const prevTarget = state.videoScans[live.media] || {};
        const targetLog = log !== undefined ? log : prevTarget.log;
        state.videoScans[live.media] = { ...prevTarget, ...live, log: targetLog };
    }

    if (paused && paused.media) {
        const previousPaused = state.videoPaused || {};
        const pausedLog = paused.log !== undefined ? paused.log : previousPaused.log;
        state.videoPaused = { ...paused, log: pausedLog };
    } else {
        state.videoPaused = null;
    }
    scan = state.videoScan;
    const started = previous.status !== "running" && scan.status === "running";
    const finished = previous.status === "running" && scan.status !== "running";
    const finishStamp = `${scan.media || ""}:${scan.status || ""}:${scan.finished_at || ""}`;
    const startStamp = scan.started_at || "running";
    if (finished && state.videoScanNoted === finishStamp) return;
    if (finished) state.videoScanNoted = finishStamp;
    if (started && state.videoScanStarted !== startStamp) {
        state.videoScanStarted = startStamp;
        const name = scan.media === "tv" ? "TV" : "Movie";
        const mode = scan.mode === "full" ? "full" : (scan.mode === "deep" ? "deep" : "incremental");
        notify(`${name} ${mode} scan started.`, "info");
    }
    if (finished) {
        state.videoStopping = false;
        if (scan.status === "failed") notify(scan.message || "The scan failed.", "error");
        else if (scan.status === "cancelled") notify(scan.message || "Scan stopped.", "info");
        else notify(`${scan.media === "tv" ? "TV" : "Movie"} scan finished. ${scan.message || ""}`.trim(), "info");
        loadMediaTotals();
        reloadVideoAfterScan(scan.media);
        refreshOpenAfterScan(scan.media);
        showVideoScanResults(scan);
    } else if (scan.status === "running" && Date.now() - state.videoScanReloaded > 20000) {
        state.videoScanReloaded = Date.now();
        if (previous.status === "running") reloadVideoAfterScan(scan.media, true);
    }
    renderScanButton({});
    paintVideoScanFooter();
    renderVideoScanModal();
    if (typeof syncActivity === "function") syncActivity();
    if (typeof renderJobs === "function" && state.system) renderJobs(state.system);
}

function reloadVideoAfterScan(media, quiet) {
    if (media === "sets") {
        state.video.stale.sets = true;
        if (state.media === "sets") loadVideo("sets", { keepScroll: true, quiet: !!quiet });
        return;
    }
    if (media === "movies") {
        state.video.stale.movies = true;
        state.video.stale.sets = true;
    } else if (media === "tv" || media === "episodes" || media === "seasons") {
        state.video.stale.tv = true;
    }
    const showing = (scanKind() === media || ((media === "episodes" || media === "seasons") && state.media === "tv")) && state.media !== "music";
    if (!showing) return;
    if (quiet && (state.media === "movies" || state.media === "tv")) {
        refreshVideoChanges(state.media);
        return;
    }
    loadVideo(state.media, { keepScroll: true, quiet: !!quiet }).then(() => {
        if (media === "tv" || media === "episodes") refreshOpenShows([...state.video.showDetails.keys()]);
    });
}

// A scan can change what the open item shows, such as the subtitle files found next to it or its media info. The
// list is reloaded above; this reads the open movie or episode again in place, so it does not have to be left and
// opened again. It waits when something in the pane is being typed into.
function refreshOpenAfterScan(media) {
    const center = document.getElementById("video-center");
    const active = document.activeElement;
    if (!center || (active && center.contains(active) && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName))) return null;
    if (media === "movies" && state.media === "movies" && state.video.movieId) {
        holdCenterScroll();
        return openMovie(state.video.movieId, true);
    }
    const selected = state.video.tvSel || {};
    if ((media === "tv" || media === "episodes" || media === "seasons") && state.media === "tv" && selected.type === "episode") {
        holdCenterScroll();
        return openEpisode(selected.id, true);
    }
    return null;
}

function paintVideoScanFooter() {
    if (state.media === "sets") return paintSetScanFooter();
    if (scanKind() === "music") return;
    const footer = document.getElementById("dock-scan");
    if (!footer) return;
    const scan = videoScanFor(scanKind());
    const own = (scan.status === "running" || scan.status === "paused") && scan.media === scanKind() && !scan.interrupt;
    if (!own && state.scan && state.scan.status === "running") return;
    const cancel = document.getElementById("dock-cancel");
    if (cancel) cancel.classList.toggle("hidden", !own);
    if (own) {
        const counts = scan.total ? ` ${scan.processed || 0}/${scan.total}` : "";
        footer.title = `Scan progress: ${scan.message || "Scanning"}${counts}`;
    } else if (scan.status === "failed") {
        footer.title = scan.message || "The last scan failed.";
    } else {
        footer.title = "Open the scan engine";
    }
}

function paintVideoScanSteps(scan) {
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    const fill = cfg.scan_fill_missing !== false;
    const trailers = scan.media === "tv" ? !!cfg.scan_download_tv_trailers : !!cfg.scan_download_trailers;
    const order = ["walk"].concat(fill ? ["lookup"] : []).concat(trailers ? ["trailers"] : []).concat(["nfo"]);
    const phase = scan.phase === "read" ? "walk" : scan.phase;
    const current = order.indexOf(phase);
    document.querySelectorAll("#video-scan-steps span").forEach((step) => {
        const index = order.indexOf(step.dataset.phase);
        const shown = index >= 0;
        step.classList.toggle("hidden", !shown);
        if (!shown) {
            step.classList.remove("done", "active");
            return;
        }
        const isTrailers = step.dataset.phase === "trailers";
        // trailers_alongside: trailers thread runs in parallel with lookup/read.
        // They aren't done until trailers_done=true, even if the scan has moved past
        // the "trailers" phase slot (e.g. into "nfo").
        const trailersDoneEarly = isTrailers && !!scan.trailers_done && (scan.phase === "lookup" || scan.phase === "read");
        const trailerDone = isTrailers && !!scan.trailers_done && !trailersDoneEarly;
        const trailerLive = isTrailers && (!!scan.trailers_alongside || trailersDoneEarly) && !scan.trailers_done;
        // When trailers run alongside, don't use phase advancement to mark them done —
        // only trailers_done (or scan completion) counts.
        const phaseAdvancedDone = current > index && current >= 0 && !(isTrailers && !!scan.trailers_alongside && !scan.trailers_done);
        step.classList.toggle("done", scan.status === "completed" || trailerDone || phaseAdvancedDone);
        step.classList.toggle("active", scan.status === "running" && (current === index || trailerLive) && !trailerDone);
    });
}

function videoModalScan() {
    const focus = state.videoScanFocus || (scanKind() === "tv" ? "tv" : "movies");
    const scan = videoScanFor(focus);
    const running = (scan.status === "running" || scan.status === "paused") && scan.media === focus;
    return { scan, focus, running };
}

function paintSetScanFooter() {
    const footer = document.getElementById("dock-scan");
    if (!footer) return;
    const scrape = state.videoScrape || {};
    const scan = state.videoScan || {};
    const own = scrape.status === "running" && scrape.media === "sets";
    const movieScan = scan.status === "running" && scan.media === "movies";
    const cancel = document.getElementById("dock-cancel");
    // A movie scan owns the dock Cancel button. Hiding it here made the button flash on each poll.
    if (cancel && !movieScan) cancel.classList.toggle("hidden", !own);
    if (own) {
        const counts = scrape.total ? ` ${scrape.processed || 0}/${scrape.total}` : "";
        footer.title = `Scan progress: ${scrape.message || "Scanning movie sets"}${counts}`;
    } else if (movieScan) {
        const counts = scan.total ? ` ${scan.processed || 0}/${scan.total}` : "";
        footer.title = `Scan progress: ${scan.message || "Scanning"}${counts}`;
    } else {
        footer.title = "Open the scan engine";
    }
}

const FILE_SCAN_COPY = {
    intro: "A scan reads .nfo files and local artwork, then probes the video files. When Download missing metadata and artwork during a scan is on, it looks up the enabled fields and images. Overwrite metadata and Overwrite artwork in Settings decide whether an existing value is replaced.",
    remove: "Items are removed only when their folder was read to the end. A folder that is empty or not mounted keeps its items.",
    incremental: "A deep scan of the new and changed files. Those files are probed and looked up again.",
    full: "Reads every file and retries a probe that failed. It looks up a file that is new, changed, or missing an enabled field or image. A file that already has those, and has not changed, is left alone.",
    deep: "Rescans and reprobes the file or mount, then downloads metadata and artwork again for every item. This takes a long time on a big library.",
};
const SET_SCAN_COPY = {
    intro: "A movie set scan loads metadata and artwork for the sets from TMDB. It does not walk movie files.",
    remove: "",
    incremental: "Fills sets that are still missing a plot, an id, or a poster.",
    full: "Refreshes every set and keeps text and artwork that are already there.",
    deep: "Replaces every set with fresh metadata and artwork. This takes a long time.",
};

function applyScanCopy(sets) {
    const copy = sets ? SET_SCAN_COPY : FILE_SCAN_COPY;
    const intro = document.getElementById("video-scan-intro");
    const remove = document.getElementById("video-scan-remove");
    if (intro) intro.textContent = copy.intro;
    if (remove) {
        remove.textContent = copy.remove;
        remove.classList.toggle("hidden", !copy.remove);
    }
    document.querySelectorAll("#video-scan-modal .scan-mode-note").forEach((note) => {
        const mode = note.closest(".scan-mode") && note.closest(".scan-mode").querySelector("input");
        if (mode && copy[mode.value]) note.textContent = copy[mode.value];
    });
    document.getElementById("video-scan-steps").classList.toggle("hidden", !!sets);
    const verbose = document.getElementById("video-scan-verbose-row");
    if (verbose) verbose.classList.toggle("hidden", !!sets);
}

function renderSetScanModal() {
    const scrape = state.videoScrape || {};
    const running = scrape.status === "running" && scrape.media === "sets";
    const mode = running ? (state.setScanMode || "full") : selectedScanMode("video-scan-mode");
    applyScanCopy(true);
    paintScanHeading("video-scan-title", "sets", scanEngineTitle("sets", mode));
    const savedSets = (state.videoScans && state.videoScans.sets) || {};
    const relevant = scrape.media === "sets"
        ? scrape
        : (savedSets.media === "sets" && (savedSets.log || (savedSets.status && savedSets.status !== "idle"))
            ? savedSets
            : { status: "idle", message: "", log: "" });
    paintScanMeters("video-scan", relevant);
    const status = document.getElementById("video-scan-status");
    const tones = { running: "is-running", completed: "is-done", failed: "is-failed", cancelled: "is-stopped" };
    status.className = `scan-status ${running ? tones.running : (tones[relevant.status] || "")}`;
    const wait = !running ? scanWaitNote("sets") : "";
    keepText(status, running
        ? [scrape.message, scrape.current].filter(Boolean).join(" · ")
        : (wait || (relevant.status && relevant.status !== "idle" ? relevant.message || relevant.status : "Ready to scan.")));
    const logNode = document.getElementById("video-scan-log");
    const text = relevant.log || relevant.message || "Idle.";
    setLogText(logNode, text);
    document.querySelectorAll("input[name='video-scan-mode']").forEach((input) => {
        if (running) input.checked = input.value === mode;
        input.disabled = running;
    });
    applyScanModeChoices("video-scan-mode", "sets", running);
    const start = document.getElementById("video-scan-start");
    const queue = !running && (((state.scan || {}).status === "running") || ((state.videoScan || {}).status === "running") || videoScrapeRunning() || (state.scanQueue || []).length > 0);
    start.disabled = false;
    start.classList.toggle("is-cancel", running);
    start.textContent = running ? "Cancel scan" : (queue ? "Queue scan" : "Start scan");
    start.dataset.action = running ? "video-scan-cancel" : "video-scan-start";
    paintScanClock("video-scan-clock", scrape.media === "sets" ? scrape : {});
    armScanClock();
}

function renderVideoScanModal() {
    const modal = document.getElementById("video-scan-modal");
    if (!modal || modal.classList.contains("hidden")) return;
    if (state.videoScanFocus === "sets") return renderSetScanModal();
    applyScanCopy(false);
    const view = videoModalScan();
    const scan = view.scan;
    const running = view.running;
    const paused = scan.status === "paused";
    paintVideoScanSteps(running ? scan : { status: "idle", message: "" });
    paintScanHeading("video-scan-title", view.focus, scanEngineTitle(view.focus, running ? scan.mode : selectedScanMode("video-scan-mode"), false, running ? scan.origin : ""));
    const target = document.getElementById("video-scan-target");
    if (target) {
        const roots = running ? (scan.roots || []) : [];
        const root = roots.length === 1 ? roots[0] : (running ? "" : currentScanRoot());
        target.textContent = root || `All ${FOLDER_TYPE_LABELS[view.focus].toLowerCase()} folders`;
    }
    paintScanMeters("video-scan", scan);
    const status = document.getElementById("video-scan-status");
    const counts = scan.total ? `${scan.processed || 0}/${scan.total}` : "";
    const tones = { running: "is-running", paused: "is-running", completed: "is-done", failed: "is-failed", cancelled: "is-stopped" };
    status.className = `scan-status ${tones[scan.status] || ""}`;
    const wait = !running ? scanWaitNote(view.focus) : "";
    keepText(status, running
        ? [paused ? "Paused" : "Running", scan.message, counts].filter(Boolean).join(" · ")
        : (wait || (scan.status && scan.status !== "idle" ? scan.message || scan.status : "Ready to scan.")));
    const logNode = document.getElementById("video-scan-log");
    setLogText(logNode, scan.log || scan.message || "Idle.");
    document.querySelectorAll("input[name='video-scan-mode']").forEach((input) => {
        if (running) input.checked = input.value === (scan.mode || "incremental");
        input.disabled = running;
    });
    applyScanModeChoices("video-scan-mode", view.focus, running);
    const verbose = document.getElementById("video-scan-verbose");
    if (verbose) verbose.disabled = running;
    const start = document.getElementById("video-scan-start");
    const queue = !running && (((state.scan || {}).status === "running") || ((state.videoScan || {}).status === "running") || (state.scanQueue || []).length > 0);
    start.disabled = running && state.videoStopping;
    start.classList.toggle("is-cancel", running);
    start.textContent = running ? (state.videoStopping ? "Stopping…" : "Cancel scan") : (queue ? "Queue scan" : "Start scan");
    start.dataset.action = running ? "video-scan-cancel" : "video-scan-start";
    const apply = document.getElementById("video-apply-match");
    const waiting = Number((state.videoPending || {})[view.focus] || 0);
    if (apply) {
        apply.classList.toggle("hidden", running || waiting < 1 || view.focus === "sets");
        apply.textContent = waiting === 1 ? "Apply match" : `Apply match (${waiting})`;
    }
    paintScanClock("video-scan-clock", scan);
    armScanClock();
}

function clearVideoScanLog() {
    const focus = state.videoScanFocus || "movies";
    const node = document.getElementById("video-scan-log");
    if (node) {
        node.textContent = "Idle.";
        node.scrollTop = 0;
    }
    if (focus === "sets") {
        if (state.videoScans && state.videoScans.sets) state.videoScans.sets.log = "";
        if (state.videoScrape && state.videoScrape.media === "sets") state.videoScrape.log = "";
    } else {
        if (state.videoScans && state.videoScans[focus]) state.videoScans[focus].log = "";
        if (state.videoScan && state.videoScan.media === focus) state.videoScan.log = "";
    }
}


// The same results window the music scan uses. Movies and shows have no "looked up" list, so the first
// box lists files the scan could not place, then read failures, then empty folders.
function showVideoScanResults(scan) {
    const modal = document.getElementById("scan-results-modal");
    if (!modal || !scan) return;
    const result = scan.result && typeof scan.result === "object" ? scan.result : {};
    const name = scan.media === "tv" ? "TV scan" : "Movie scan";
    const unmatched = Array.isArray(result.unmatched) ? result.unmatched : [];
    const failures = (Array.isArray(result.failures) ? result.failures : []).map((item) => (item && typeof item === "object" ? `${item.path}: ${item.error}` : String(item)));
    const empty = Array.isArray(result.empty) ? result.empty : [];
    const counts = {
        unmatched: Number.isInteger(result.unmatched_count) ? result.unmatched_count : unmatched.length,
        failures: Number.isInteger(result.failure_count) ? result.failure_count : failures.length,
        empty: Number.isInteger(result.empty_count) ? result.empty_count : empty.length,
    };
    const set = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
    const fill = (id, lines, none) => {
        const node = document.getElementById(id);
        if (!node) return;
        node.textContent = lines.length ? lines.join("\n") : none;
        node.classList.toggle("is-empty", !lines.length);
    };
    set("scan-results-title", scan.status === "failed" ? `${name} failed` : scan.status === "cancelled" ? `${name} stopped` : `${name} results`);
    const summary = document.getElementById("scan-results-summary");
    if (summary) {
        summary.className = `scan-status ${scan.status === "failed" ? "is-failed" : scan.status === "cancelled" ? "is-stopped" : "is-done"}`;
        summary.textContent = scan.message || (scan.status === "completed" ? "The library index was updated." : "");
    }
    set("scan-results-lookups-title", `${scan.media === "tv" ? "Files without an episode number" : "Files not placed"} (${counts.unmatched})`);
    fill("scan-results-lookups", unmatched, "None.");
    set("scan-results-failures-title", `Failures (${counts.failures})`);
    fill("scan-results-failures", failures, "No failures.");
    set("scan-results-empty-title", `Empty folders (${counts.empty})`);
    fill("scan-results-empty", empty, "No empty folders.");
    const clipped = counts.unmatched > unmatched.length || counts.failures > failures.length || counts.empty > empty.length;
    set("scan-results-note", clipped
        ? "The window shows the first part of each list. The scan log has the rest."
        : "These lines are kept in the scan log.");
    state.jobs = state.jobs || {};
    state.jobs["video-scan-results"] = { label: name, job: scan };
    modal.querySelectorAll("[data-job]").forEach((button) => { button.dataset.job = "video-scan-results"; });
    modal.classList.remove("hidden");
}
