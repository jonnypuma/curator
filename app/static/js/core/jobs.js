function jobStamp(job) {
    const started = Date.parse((job && job.started_at) || "");
    const finished = Date.parse((job && job.finished_at) || "");
    const left = Number.isFinite(started) ? started : 0;
    const right = Number.isFinite(finished) ? finished : 0;
    return Math.max(left, right);
}

function jobIsRunning(job) {
    const status = (job && job.status) || "";
    return status === "running" || status === "paused" || status === "loading" || status === "applying";
}

function jobIsLive(job) {
    const status = (job && job.status) || "";
    return jobIsRunning(job) || status === "queued" || status === "waiting";
}

function jobLane(entry) {
    const key = String((entry && entry.key) || "");
    const kind = (entry && entry.job && entry.job.kind) || "";
    if (entry && entry.lane) return entry.lane;
    if (key === "video-scrape" || /scrape/i.test(entry.label || "")) return "Scrape";
    if (key === "scan" || key === "video-scan" || key === "video-scan-other" || key.startsWith("scan-queue-")) return "Scan";
    if (key === "batch") return "Batch";
    if (key === "lookup") return "Lookup";
    if (key === "file-job") return "Files";
    if (key === "backup") return "Backup";
    if (kind.indexOf("kodi") === 0) return "Library";
    if (isArrKind(kind)) return "ARR";
    return "Job";
}

function isArrKind(kind) {
    return /^(lidarr|radarr|sonarr)/.test(String(kind || ""));
}

function renderJobs(data) {
    const host = document.getElementById("job-list");
    state.jobs = {};
    const scan = data.scan || {};
    const batch = data.batch || {};
    const lookup = data.lookup || {};
    const video = visibleVideoJob(state.videoScan, data.video_scan);
    const scrape = visibleVideoJob(state.videoScrape, data.video_scrape);
    const entries = [];
    if (jobIsLive(scan)) entries.push({ key: "scan", label: "Music", job: scan, media: "music", lane: "Scan" });
    if (video && jobIsLive(video)) {
        entries.push({
            key: "video-scan",
            label: scanJobLabel(videoScanMedia(video)),
            job: video,
            media: videoScanMedia(video),
            lane: "Scan",
        });
    }
    const parked = state.videoPaused;
    if (parked && parked.media && (!video || video.media !== parked.media)) {
        entries.push({
            key: "video-scan-paused",
            label: scanJobLabel(parked.media),
            job: parked,
            media: parked.media,
            lane: "Scan",
        });
    }
    if (scrape && !scrape.embedded && jobIsLive(scrape)) {
        entries.push({
            key: "video-scrape",
            label: withoutLaneWord(scrapeJobLabel(scrape), "scrape"),
            job: scrape,
            media: scrape.media || "movies",
            lane: "Scrape",
        });
    }
    (data.scan_queue || []).forEach((item, index) => {
        if (item.kind === "move") {
            entries.push({
                key: `scan-queue-${index}`,
                label: item.label || "Move",
                lane: "Job",
                job: { status: "queued", message: "Waiting until the library is free" },
            });
            return;
        }
        const scrapeWait = item.kind === "scrape";
        const sets = !scrapeWait && (item.media === "sets" || item.kind === "sets");
        const media = item.media === "tv" ? "tv" : (item.media === "movies" ? "movies" : (sets || item.media === "sets" ? "sets" : "music"));
        const mode = item.mode === "full" ? "Full" : (item.mode === "deep" ? "Deep" : "Incremental");
        const label = scrapeWait
            ? withoutLaneWord(item.label || (media === "sets" ? "Movie set scrape" : media === "tv" ? "TV scrape" : "Movie scrape"), "scrape")
            : (sets ? "Movie sets" : (media === "tv" ? "TV shows" : (media === "movies" ? "Movies" : "Music")));
        const named = (item.titles || [])[0] || "";
        entries.push({
            key: `scan-queue-${index}`,
            label,
            media,
            lane: scrapeWait || sets ? "Scrape" : "Scan",
            job: { status: "queued", message: named ? `Waiting for ${named}` : (scrapeWait || sets ? `Waiting for ${label}` : `Waiting for a ${mode.toLowerCase()} scan`) },
        });
    });
    const fileJob = data.file_job;
    if (fileJob && jobIsLive(fileJob)) {
        entries.push({ key: "file-job", label: fileJobLabel(fileJob.op), job: fileJob, lane: "Files" });
    }
    if (jobIsLive(lookup)) entries.push({ key: "lookup", label: "Find metadata", job: lookup, lane: "Lookup" });
    if (jobIsLive(batch)) entries.push({ key: "batch", label: "Batch", job: batch, lane: "Batch" });
    const backup = data.backup || {};
    if (jobIsLive(backup)) {
        const label = backup.kind === "import" ? "Music import" : backup.kind === "restore" ? "Database restore" : "Database backup";
        entries.push({ key: "backup", label, job: backup, lane: "Backup" });
    }
    (data.work || []).forEach((job, index) => {
        if (!jobIsLive(job)) return;
        const kind = job.kind || "";
        const lane = kind.indexOf("kodi") === 0 ? "Library" : isArrKind(kind) ? "ARR" : "Job";
        entries.push({ key: `work-${job.id || index}`, label: jobLabel(kind), job, lane });
    });
    const queue = (typeof live !== "undefined" && live.queue) || {};
    (queue.arr || []).forEach((item) => {
        entries.push({
            key: `arr-queue-${item.id || item.title || "arr"}`,
            label: item.title || "ARR",
            lane: "ARR",
            job: { status: item.status || "queued", message: item.where || "", kind: item.kind || item.source || "arr" },
        });
    });
    const imports = Number(queue.queued_items_count) || 0;
    if (queue.running || imports) {
        const titles = (queue.queued_titles || []).filter(Boolean).slice(0, 4).join(", ");
        entries.push({
            key: "webhook-queue",
            label: "Webhook queue",
            lane: "Webhook",
            job: {
                status: queue.running ? "running" : "queued",
                message: queue.message || titles || (imports ? `${imports} waiting` : "Waiting"),
                kind: "webhook",
            },
        });
    }
    entries.forEach((entry) => rememberJob(entry.key, entry.label, entry.job));
    const drawer = document.getElementById("job-drawer");
    const drawerTop = drawer ? drawer.scrollTop : 0;
    const nearTop = drawerTop < 8;
    const listHeight = host ? host.scrollHeight : 0;
    const logPlaces = [];
    if (host) {
        host.querySelectorAll("[data-job-log]").forEach((log) => {
            logPlaces.push({
                key: log.dataset.jobLog,
                top: log.scrollTop,
                height: log.scrollHeight,
                atTop: log.scrollTop < 8,
            });
        });
    }
    const running = entries.filter((entry) => jobIsRunning(entry.job));
    const waiting = entries.filter((entry) => !jobIsRunning(entry.job));
    const group = (title, list) => list.length ? `<h3 class="job-group">${title}</h3>${list.map((entry) => jobRow(entry.label, entry.job, entry.key, entry.media, entry.lane)).join("")}` : "";
    const rows = `${group("Running", running)}${group("Waiting", waiting)}`;
    replaceHtml(host, rows || `<p class="muted">Nothing is running.</p>`);
    logPlaces.forEach((place) => {
        const log = host && host.querySelector(`[data-job-log="${CSS.escape(place.key)}"]`);
        if (!log) return;
        const growth = log.scrollHeight - place.height;
        log.scrollTop = place.atTop ? 0 : place.top + Math.max(0, growth);
    });
    if (drawer) {
        const growth = host ? host.scrollHeight - listHeight : 0;
        if (state.jobsReveal || nearTop) drawer.scrollTop = 0;
        else drawer.scrollTop = drawerTop + Math.max(0, growth);
        state.jobsReveal = false;
    }
    const heading = document.getElementById("job-heading");
    if (heading) heading.textContent = entries.length ? `Jobs (${running.length})` : "Jobs";
    const button = document.querySelector("[data-action='toggle-jobs']");
    const active = runningJobCount(data);
    if (button) {
        const label = active ? `Jobs (${active})` : "Jobs";
        button.title = label;
        button.setAttribute("aria-label", label);
        button.classList.toggle("is-live", active > 0);
    }
    const badge = document.getElementById("jobs-count");
    if (badge) {
        badge.textContent = String(active);
        badge.classList.toggle("hidden", !active);
    }
}

function currentJobMedia() {
    if (state.media === "movies" || state.media === "sets" || state.media === "tv") return state.media;
    return "music";
}

function videoScanMedia(scan) {
    if (!scan) return "movies";
    if (scan.media === "tv" || scan.media === "sets" || scan.media === "movies") return scan.media;
    return "movies";
}

function scanJobLabel(media) {
    if (media === "tv") return "TV shows";
    if (media === "movies") return "Movies";
    if (media === "sets") return "Movie sets";
    return "Music";
}

function withoutLaneWord(label, word) {
    const text = String(label || "");
    const suffix = ` ${word}`;
    return text.toLowerCase().endsWith(suffix) ? text.slice(0, -suffix.length) : text;
}

function currentScanEntry(here, music, video, scrape) {
    if (here === "music") return { key: "scan", label: "Music", job: music, media: "music" };
    if (here === "sets") {
        const setJob = scrape && (scrape.media === "sets" || !scrape.media) ? scrape : null;
        return {
            key: setJob ? "video-scrape" : "video-scan",
            label: "Movie sets",
            job: setJob || { status: "idle", message: "Idle" },
            media: "sets",
        };
    }
    const job = video && videoScanMedia(video) === here ? video : { status: "idle", message: "Idle" };
    return { key: "video-scan", label: scanJobLabel(here), job, media: here };
}

function visibleVideoJob(live, incoming) {
    const chosen = (live && live.status && live.status !== "idle") ? live : incoming;
    if (!chosen || chosen.embedded || !chosen.status || chosen.status === "idle") return null;
    return chosen;
}

function scrapeJobLabel(scrape) {
    if (scrape.media === "episodes") return scrape.art_only ? "Episode artwork" : "Episode scrape";
    if (scrape.media === "seasons") return scrape.art_only ? "Season artwork" : "Season scrape";
    const name = scrape.media === "tv" ? "TV" : (scrape.media === "sets" ? "Movie set" : "Movie");
    return scrape.art_only ? `${name} artwork` : `${name} scrape`;
}

function runningJobCount(data) {
    let count = 0;
    if (data.scan && data.scan.status === "running") count += 1;
    if ((state.videoScan && state.videoScan.status === "running") || (data.video_scan && data.video_scan.status === "running")) count += 1;
    if (state.videoPaused && state.videoPaused.media) count += 1;
    const scrape = state.videoScrape && state.videoScrape.status === "running" ? state.videoScrape : data.video_scrape;
    if (scrape && scrape.status === "running" && !scrape.embedded) count += 1;
    count += (data.scan_queue || []).length;
    if (data.backup && (data.backup.status === "running" || data.backup.status === "waiting")) count += 1;
    if (data.batch && data.batch.status === "running") count += 1;
    const lookup = (data.lookup && data.lookup.status) || "idle";
    if (lookup === "running" || lookup === "applying" || lookup === "loading") count += 1;
    if (data.file_job && data.file_job.status === "running") count += 1;
    count += (data.work || []).filter((job) => job.status === "running" || job.status === "queued").length;
    return count;
}

function rememberJob(key, label, job) {
    state.jobs[key] = { label, job: job || {} };
}

function fileJobLabel(op) {
    return { move: "Move", rename: "Rename", subtitles: "Subtitles", extras: "Extras", trailers: "Trailers" }[op] || "File job";
}

function jobQueueTab(key, lane, job) {
    const kind = String((job && job.kind) || "");
    const id = String(key || "");
    if (id.startsWith("scan-queue-")) return "scan";
    if (id.startsWith("arr-queue-") || lane === "ARR" || kind.indexOf("lidarr") === 0 || kind === "radarr" || kind === "sonarr") return "arr";
    if (id.startsWith("webhook-queue") || lane === "Webhook") return "webhook";
    if (lane === "Library" || kind.indexOf("kodi") === 0) return "library";
    return "";
}

function jobLabel(kind) {
    return {
        fingerprint: "Fingerprint",
        lyrics: "Lyrics",
        replaygain: "ReplayGain",
        audit: "Audit",
        artwork: "Artwork lookup",
        "missing-art": "Album artwork",
        "missing-artist-art": "Artist artwork",
        "lidarr-search": "Lidarr search",
        "radarr-add": "Add to Radarr",
        "sonarr-add": "Add to Sonarr",
        "kodi-video": "Kodi video",
        "kodi-music": "Kodi music",
        "sub-ocr": "Subtitle OCR",
        "sub-preview": "Video preview",
        "sub-auto": "Automatic subtitle sync",
        "sub-sync": "Subtitle sync",
        "sub-download": "Subtitle download",
        "episode-split": "Episode split",
    }[kind] || kind || "Job";
}

function jobRow(label, job, key, media, lane) {
    const running = job.status === "running" || job.status === "loading" || job.status === "applying";
    const waiting = job.status === "queued" || job.status === "waiting";
    const queueTab = jobQueueTab(key, lane, job);
    const scrapeJob = !queueTab && (key === "video-scrape" || (String(key || "").startsWith("scan-queue-") && lane === "Scrape"));
    const scanJob = !queueTab && !scrapeJob && (key === "scan" || key === "video-scan" || key === "video-scan-paused" || key === "video-scan-other" || (String(key || "").startsWith("scan-queue-") && lane === "Scan"));
    const counts = job.total ? `${job.processed || 0}/${job.total}` : "";
    const message = job.message || "";
    const detail = waiting ? (message || "Waiting") : (message && (!counts || message.includes(counts)) ? message : [counts, message].filter(Boolean).join(" · "));
    const log = jobLogHtml(job.log || "", key);
    const body = `<span class="job-copy"><span class="job-name"><span class="job-lane">${escapeHtml(lane || jobLane({ key, job, label }))}</span> ${escapeHtml(label)}</span><span class="job-detail">${escapeHtml(detail)}</span></span>`;
    const open = queueTab
        ? ` data-action="open-queue" data-tab="${escapeHtml(queueTab)}" title="Open the queue"`
        : (scrapeJob
            ? ` data-action="open-scrape" title="Open the scrape"`
            : (scanJob ? ` data-action="open-scan" data-scan-media="${escapeHtml(media || "music")}" title="Open the scan engine"` : ""));
    const scanEngine = scrapeJob
        ? `<button type="button" class="btn-ghost" data-action="open-scrape">Open scrape</button>`
        : (scanJob ? `<button type="button" class="btn-ghost" data-action="open-scan" data-scan-media="${escapeHtml(media || "music")}">${scanEngineIcon(media || "music")}Scan engine</button>` : "");
    const tools = `<div class="job-actions">${scanEngine}<button type="button" class="btn-ghost" data-action="copy-job" data-job="${escapeHtml(key)}">Copy</button><button type="button" class="btn-ghost" data-action="export-job" data-job="${escapeHtml(key)}">Export JSON</button></div>`;
    const bar = running && job.total ? scanJobBar(job) : "";
    return `<div class="job-row${running ? " is-running" : ""}"${open}>${body}</div>${bar}${log}${tools}`;
}

function jobLineClass(line) {
    if (line.startsWith("Working —")) return "is-working";
    if (line.startsWith("Saved —") || line.startsWith("Found —")) return "is-saved";
    if (line.startsWith("Failed —") || line.startsWith("Failed:")) return "is-failed";
    if (line.startsWith("No artwork —") || line.startsWith("No release —")) return "is-missing";
    if (line.startsWith("Queued —") || line.startsWith("Already complete —") || /^\d+ still queued/.test(line)) return "is-queued";
    return "";
}

function jobLogHtml(text, key) {
    const lines = String(text || "").split("\n").filter((line) => line.trim()).reverse();
    if (!lines.length) return "";
    return `<div class="job-log" data-job-log="${escapeHtml(key || "")}">${lines.map((line) => {
        const kind = jobLineClass(line);
        return `<div class="job-line${kind ? ` ${kind}` : ""}">${escapeHtml(line)}</div>`;
    }).join("")}</div>`;
}

function jobStatusText(key) {
    const entry = state.jobs[key] || { label: key || "Job", job: {} };
    const job = entry.job || {};
    const counts = job.total ? `${job.processed || 0}/${job.total}` : "";
    const head = [entry.label, job.status || "idle", job.message || "", counts].filter(Boolean).join(" · ");
    return job.log ? `${head}\n${job.log}` : head;
}

function copyPlainText(text) {
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
    area.setSelectionRange(0, area.value.length);
    let copied = false;
    try {
        copied = document.execCommand("copy");
    } catch (error) {
        copied = false;
    }
    area.remove();
    if (!copied) throw new Error("copy failed");
}

async function copyJob(key) {
    const text = jobStatusText(key);
    try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
        else copyPlainText(text);
        notify("Job status copied.", "info");
    } catch (error) {
        try {
            copyPlainText(text);
            notify("Job status copied.", "info");
        } catch (fallbackError) {
            notify("Could not copy the job status.", "warning");
        }
    }
}

function exportJob(key) {
    const entry = state.jobs[key] || { label: key || "Job", job: {} };
    const job = entry.job || {};
    const payload = {
        label: entry.label,
        status: job.status || "idle",
        message: job.message || "",
        phase: job.phase || null,
        mode: job.mode || null,
        processed: job.processed || 0,
        total: job.total || 0,
        log: job.log || "",
        result: job.result || null,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    link.href = url;
    link.download = `${String(entry.label || "job").toLowerCase().replace(/\s+/g, "-")}-${stamp}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function scanJobBar(job) {
    const width = job.total ? Math.round(100 * (job.processed || 0) / job.total) : 0;
    return `<div class="progress-bar-bg job-progress" role="progressbar" aria-valuenow="${width}" aria-valuemin="0" aria-valuemax="100"><div class="progress-bar-fill" style="width:${width}%"></div></div>`;
}

const SPECIAL_COUNTRIES = {
    XW: "Worldwide",
    XE: "Europe",
    XU: "Unknown country",
    XX: "Unknown country",
};
