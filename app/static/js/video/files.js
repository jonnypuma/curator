// File jobs: rename, subtitle clean-up, extras layout and trailer downloads.

const VIDEO_FILE_OPS = {
    rename: { title: "Rename files", verb: "Rename", note: "Files and folders are renamed from the patterns in Settings, Files. Sidecars (.nfo, artwork, subtitles) follow their video. Kodi is asked to clean and rescan afterwards." },
    extras: { title: "Organize extras", verb: "Move extras", note: "Extras inside a movie folder, or a show folder, are sorted into the layout chosen in Settings, Files. Episode files stay put. Movies that share a folder are left alone." },
    subtitles: { title: "Normalize subtitles", verb: "Normalize", note: "Text subtitles are converted to UTF-8 without BOM, sidecars are renamed to <video>.<language>[.forced][.sdh].<ext>, and duplicate subtitles are removed when that is switched on in Settings, Files." },
    trailers: { title: "Download trailers", verb: "Download", note: "The YouTube trailer found by the scraper is fetched with yt-dlp. A movie, show or season that already has a local trailer is skipped. Quality is the highest chosen in Settings, Files." },
    themes: { title: "Download theme songs", verb: "Download", note: "Searches YouTube for the official theme song and saves it as theme.mp3 in the movie or show folder. Folders that already have a theme file are skipped." },
    thumbs: { title: "Generate episode thumbnails", verb: "Generate", note: "Uses ffmpeg to sample a non-black frame from mid-episode and saves <episode>-thumb.jpg beside each video file that is missing a thumbnail." },
    move: { title: "Move", verb: "Move", note: "The folder is copied into the other library folder. The original is removed after the copy matches. Scans wait until the move finishes." },
};

// File jobs that show what they would change before they run (a dry run).
const VIDEO_PREVIEW_OPS = ["rename", "extras", "subtitles"];

function videoFilesRunning() {
    return (state.videoFiles || {}).status === "running";
}

async function openVideoFiles(op, target) {
    if (videoFilesRunning() && op !== (state.videoFiles || {}).op) {
        notify("Another file job is running. Wait for it to finish.", "error");
        return showVideoFilesModal();
    }
    state.videoFilesTarget = { op, kind: target.kind, ids: [...target.ids] };
    state.videoFilesQueue = [];
    state.videoFilesPreview = null;
    showVideoFilesModal();
    if (VIDEO_PREVIEW_OPS.includes(op)) {
        renderVideoFilesModal();
        try {
            state.videoFilesPreview = await api("/api/v1/files/preview", { method: "POST", body: { op, kind: target.kind, ids: target.ids } });
        } catch (error) {
            document.getElementById("video-files-modal").classList.add("hidden");
            throw error;
        }
    }
    renderVideoFilesModal();
}

async function openSelectionRename() {
    const groups = selectedVideoGroups().filter((group) => ["movie", "show", "season", "episode"].includes(group.kind));
    if (!groups.length) return;
    if (groups.length === 1) return openVideoFiles("rename", groups[0]);
    if (videoFilesRunning()) {
        notify("Another file job is running. Wait for it to finish.", "error");
        return showVideoFilesModal();
    }
    state.videoFilesTarget = { op: "rename", kind: groups[0].kind, ids: [...groups[0].ids] };
    state.videoFilesQueue = groups.slice(1).map((group) => ({ kind: group.kind, ids: [...group.ids] }));
    state.videoFilesPreview = null;
    showVideoFilesModal();
    try {
        const plans = [];
        let moves = 0;
        for (const group of groups) {
            const preview = await api("/api/v1/files/preview", { method: "POST", body: { op: "rename", kind: group.kind, ids: group.ids } });
            plans.push(...(preview.plans || []));
            moves += Number(preview.moves) || 0;
        }
        state.videoFilesPreview = { op: "rename", plans, moves };
    } catch (error) {
        document.getElementById("video-files-modal").classList.add("hidden");
        state.videoFilesQueue = [];
        throw error;
    }
    renderVideoFilesModal();
}

function showVideoFilesModal() {
    document.getElementById("video-files-modal").classList.remove("hidden");
    renderVideoFilesModal();
}

async function startVideoFiles() {
    const target = state.videoFilesTarget;
    if (!target) return;
    const data = await api("/api/v1/files/run", { method: "POST", body: { op: target.op, kind: target.kind, ids: target.ids } });
    applyVideoFiles(data.files || {});
    pollVideoFiles();
}

async function cancelVideoFiles() {
    if (!videoFilesRunning()) return;
    await api("/api/v1/files/cancel", { method: "POST", body: {} });
    notify("Stopping after the current item.", "info");
    pollVideoFiles();
}

async function pollVideoFiles() {
    const boot = typeof watchBoot === "function" ? watchBoot("files") : null;
    clearTimeout(state.videoFilesTimer);
    state.videoFilesTicket = (state.videoFilesTicket || 0) + 1;
    const ticket = state.videoFilesTicket;
    let data;
    try {
        try {
            data = await api("/api/v1/files/status");
        } catch (error) {
            return;
        }
        if (ticket !== state.videoFilesTicket) return;
        try {
            applyVideoFiles(data);
        } catch (err) {
            console.error("applyVideoFiles error", err);
        }
        if (videoFilesRunning()) state.videoFilesTimer = setTimeout(pollVideoFiles, 1500);
    } finally {
        if (boot) boot.done();
    }
}

function onVideoFilesLive(snapshot) {
    const wasRunning = videoFilesRunning();
    applyVideoFiles(snapshot || {});
    if (!wasRunning && videoFilesRunning()) pollVideoFiles();
}

function applyVideoFiles(job) {
    const previous = state.videoFiles || {};
    const log = job.log !== undefined ? job.log : previous.log;
    state.videoFiles = { ...job, log };
    if (previous.status === "running" && job.status !== "running") {
        const result = job.result || {};
        const failed = Number(result.failed) || 0;
        const queue = state.videoFilesQueue || [];
        if (queue.length && job.status === "done" && !failed && job.op === "rename") {
            const next = queue[0];
            state.videoFilesQueue = queue.slice(1);
            state.videoFilesTarget = { op: "rename", kind: next.kind, ids: next.ids };
            api("/api/v1/files/run", { method: "POST", body: state.videoFilesTarget })
                .then((data) => {
                    applyVideoFiles(data.files || {});
                    pollVideoFiles();
                })
                .catch((error) => notify(error.message, "error"));
            renderVideoFilesModal();
            return;
        }
        state.videoFilesQueue = [];
        notify(`${(VIDEO_FILE_OPS[job.op] || {}).title || "File job"}: ${Number(result.changed) || 0} changed, ${Number(result.skipped) || 0} unchanged${failed ? `, ${failed} failed` : ""}.`, failed ? "error" : "info");
        if (job.op === "move") {
            if (state.media === "music" && state.artistId && typeof selectArtist === "function") selectArtist(state.artistId);
            else {
                if (typeof renderVideoList === "function") renderVideoList();
                reloadOpenItem();
            }
        } else if (job.op === "rename" || job.op === "extras") {
            const plans = (state.videoFilesPreview || {}).plans || [];
            rewriteVideoPaths(plans.flatMap((plan) => plan.moves || []));
            reloadOpenItem();
        } else if (job.op === "subtitles" || job.op === "themes" || job.op === "thumbs") {
            reloadOpenItem();
        } else if (job.op === "trailers") {
            reloadOpenTrailer();
        }
        state.videoFilesPreview = false;
    }
    renderVideoFilesModal();
}

function videoFilesPreviewHtml(preview) {
    if (!preview) return `<p class="muted">Working out the changes…</p>`;
    if (!preview.plans.length) return `<p class="muted">Everything already matches. Nothing to do.</p>`;
    const short = (path) => escapeHtml(String(path).split("/").slice(-2).join("/"));
    return preview.plans.map((plan) => `<div class="vfiles-plan${plan.error ? " has-error" : ""}">
        <h4>${escapeHtml(plan.title)}</h4>
        ${plan.error ? `<p class="vfiles-error">${escapeHtml(plan.error)}</p>` : ""}
        <ul>${plan.moves.map((move) => `<li title="${escapeHtml(move.from)} → ${escapeHtml(move.to)}"><span class="vfiles-from">${short(move.from)}</span><span class="vfiles-to">${/^(Re-encode|Left alone|Remove|Duplicate)/.test(move.to) ? escapeHtml(move.to) : short(move.to)}${move.dir ? "/" : ""}</span></li>`).join("")}</ul>
    </div>`).join("");
}

function renderVideoFilesModal() {
    const modal = document.getElementById("video-files-modal");
    if (!modal || modal.classList.contains("hidden")) return;
    const job = state.videoFiles || {};
    const running = job.status === "running";
    const target = state.videoFilesTarget || { op: job.op || "rename", ids: [] };
    const op = running ? job.op : target.op;
    const info = VIDEO_FILE_OPS[op] || VIDEO_FILE_OPS.rename;
    document.getElementById("video-files-title").textContent = info.title;
    document.getElementById("video-files-note").textContent = info.note;
    const preview = document.getElementById("video-files-preview");
    const previewing = !running && VIDEO_PREVIEW_OPS.includes(op) && state.videoFilesPreview !== false;
    preview.classList.toggle("hidden", !previewing);
    if (previewing) replaceHtml(preview, videoFilesPreviewHtml(state.videoFilesPreview));
    const width = job.total ? Math.round(100 * (job.processed || 0) / job.total) : (job.status === "done" ? 100 : 0);
    document.getElementById("video-files-progress").style.width = `${width}%`;
    const status = document.getElementById("video-files-status");
    const tones = { running: "is-running", done: "is-done", failed: "is-failed", cancelled: "is-stopped" };
    status.className = `scan-status ${tones[job.status] || ""}`;
    keepText(status, running
        ? [job.message, job.current].filter(Boolean).join(" · ")
        : (job.status && job.status !== "idle" ? job.message || job.status : `${target.ids.length} item${target.ids.length === 1 ? "" : "s"} picked.`));
    setLogText(document.getElementById("video-files-log"), job.log || "Idle.");
    const start = document.getElementById("video-files-start");
    const plans = (state.videoFilesPreview || {}).plans || [];
    const previewOp = VIDEO_PREVIEW_OPS.includes(op);
    const nothing = previewOp && (state.videoFilesPreview === false || !plans.some((plan) => plan.moves.length && !plan.error));
    start.classList.toggle("is-cancel", running);
    start.textContent = running ? "Stop" : info.verb;
    start.dataset.action = running ? "video-files-cancel" : "video-files-start";
    start.disabled = !running && (nothing || !target.ids.length);
}

function reloadOpenItem() {
    if (state.media === "movies" && state.video.movieId) return openMovie(state.video.movieId);
    const selected = state.video.tvSel || {};
    if (selected.type === "show") return openShow(selected.id);
    if (selected.type === "season") return openSeason(selected.id, selected.show);
    if (selected.type === "episode") return openEpisode(selected.id);
    return null;
}

function reloadOpenTrailer() {
    if (state.media === "movies" && state.video.movieId) return openMovie(state.video.movieId);
    const selected = state.video.tvSel || {};
    if (selected.type === "season") return openSeason(selected.id, selected.show);
    if (selected.type === "show") return openShow(selected.id);
    return null;
}

function downloadTrailer(action) {
    return openVideoFiles("trailers", { kind: action.dataset.kind, ids: [action.dataset.id] });
}

const VIDEO_FILES_ACTIONS = {
    "video-files-start": () => runAction(startVideoFiles, "Starting…"),
    "video-files-cancel": () => runAction(cancelVideoFiles),
    "video-trailer-download": (action) => downloadTrailer(action),
    "video-files-run": (action) => openVideoFiles(action.dataset.op, { kind: action.dataset.kind, ids: [action.dataset.id] }),
    "video-move": (action) => openVideoMove(action.dataset.kind, [action.dataset.id]),
    "video-move-start": () => runAction(startVideoMove, "Moving…"),
};

function onVideoFilesAction(name, action) {
    const run = VIDEO_FILES_ACTIONS[name];
    if (!run) return false;
    run(action);
    return true;
}

function moveIdsFromSelection() {
    if (state.media === "movies") return [...selectionChecked("movie")];
    if (state.media !== "tv") return [];
    const ids = [];
    selectionChecked("tv").forEach((key) => {
        const text = String(key);
        const split = text.indexOf(":");
        if (split > 0 && text.slice(0, split) === "show") ids.push(text.slice(split + 1));
    });
    return ids;
}

function openBatchMove() {
    const ids = moveIdsFromSelection();
    if (!ids.length) return;
    const kind = state.media === "tv" ? "show" : "movie";
    return openVideoMove(kind, ids);
}

function openVideoMove(kind, ids) {
    if (kind !== "movie" && kind !== "show" && kind !== "artist") return;
    const media = kind === "movie" ? "movies" : kind === "show" ? "tv" : "music";
    state.videoMove = { media, kind, ids: (ids || []).filter(Boolean) };
    const modal = document.getElementById("video-move-modal");
    if (modal) modal.classList.remove("hidden");
    renderVideoMove();
    const select = document.getElementById("video-move-dest");
    if (select && !select.dataset.bound) {
        select.dataset.bound = "1";
        select.addEventListener("change", () => renderVideoMove());
    }
}

async function renderVideoMove() {
    const modal = document.getElementById("video-move-modal");
    const move = state.videoMove;
    if (!modal || modal.classList.contains("hidden") || !move) return;
    const paths = move.media === "tv" ? (state.tvPaths || []) : move.media === "music" ? (state.musicPaths || []) : (state.moviePaths || []);
    const select = document.getElementById("video-move-dest");
    const chosen = select.value;
    select.innerHTML = paths.map((path) => `<option value="${escapeHtml(path)}">${escapeHtml(path)}</option>`).join("");
    if (paths.includes(chosen)) select.value = chosen;
    const start = document.getElementById("video-move-start");
    const preview = document.getElementById("video-move-preview");
    const noun = move.kind === "show" ? "show" : move.kind === "artist" ? "artist" : "movie";
    document.getElementById("video-move-title").textContent = move.ids.length > 1 ? `Move ${move.ids.length} ${noun}s` : "Move";
    if (paths.length < 2) {
        preview.innerHTML = `<p class="muted">Add another library folder in Settings before moving.</p>`;
        start.disabled = true;
        return;
    }
    start.disabled = true;
    preview.innerHTML = `<p class="muted">Checking the folders…</p>`;
    const ticket = (state.videoMoveTicket = (state.videoMoveTicket || 0) + 1);
    const dest = select.value;
    try {
        const data = await api("/api/v1/move/preview", { method: "POST", body: { media: move.media, ids: move.ids, dest } });
        if (ticket !== state.videoMoveTicket) return;
        preview.innerHTML = movePreviewHtml(data);
        start.disabled = !data.moves;
        start.textContent = data.moves > 1 ? `Move (${data.moves})` : "Move";
    } catch (error) {
        if (ticket !== state.videoMoveTicket) return;
        preview.innerHTML = `<p class="vfiles-error">${escapeHtml(error.message)}</p>`;
        start.disabled = true;
    }
}

function movePreviewHtml(data) {
    const plans = data.plans || [];
    if (!plans.length) return `<p class="muted">Nothing to move.</p>`;
    const short = (path) => escapeHtml(String(path).split("/").slice(-2).join("/"));
    return plans.map((plan) => {
        const body = plan.error
            ? `<p class="vfiles-error">${escapeHtml(plan.error)}</p>`
            : plan.skipped
                ? `<p class="muted">Already in this folder.</p>`
                : `<ul class="vfiles-move">${(plan.moves || []).map((move) => `<li title="${escapeHtml(move.from)} → ${escapeHtml(move.to)}"><span class="vfiles-from">${short(move.from)}</span><span class="vfiles-arrow" aria-hidden="true">→</span><span class="vfiles-to">${short(move.to)}/</span></li>`).join("")}</ul>`;
        return `<div class="vfiles-plan${plan.error ? " has-error" : ""}"><h4>${escapeHtml(plan.title)}</h4>${body}</div>`;
    }).join("");
}

async function startVideoMove() {
    const move = state.videoMove;
    const dest = document.getElementById("video-move-dest");
    if (!move || !dest || !dest.value) return;
    const data = await api("/api/v1/move", { method: "POST", body: { media: move.media, ids: move.ids, dest: dest.value } });
    document.getElementById("video-move-modal").classList.add("hidden");
    notify(data.status === "queued" ? "Move queued. It starts when the current library job finishes." : "Move started. Scans wait until it finishes.", "info");
    if (typeof pollSystem === "function") pollSystem();
}
