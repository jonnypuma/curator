// Sync external subtitles against the video. Same two-pane layout as the split modal,
// using the same video streaming endpoint. The right pane is a scrolling cue list where
// the user picks a line, scrubs the video to the correct time, and clicks "Mark" to make
// that line an anchor. One anchor applies a constant offset; two or more anchors apply a
// linear fit, so framerate drift between subtitle source and video can be fixed too. Live
// preview via a WebVTT track driven by /api/v1/subs/preview-track.
//
// Picture subtitles (VobSub .idx+.sub, PGS .sup) open the same modal. They first need an OCR
// pass (background job on the server, cached) so the lines can be read and picked; Save then
// rewrites only their timing, and Export SRT writes the recognised text as a text subtitle.

const subSyncState = {
    path: "",
    video: "",
    format: "",
    duration: 0,
    cues: [],
    anchors: [],         // [{index, sub_ms, video_ms}]
    selected: null,      // cue index (1-based)
    hasBackup: false,
    previewUrl: "",
    trackEl: null,
    poller: 0,
    search: "",          // quick-search filter against cue text (case-insensitive)
    mode: "linear",      // "linear" (least-squares) or "piecewise" (one segment per anchor pair)
    edits: {},           // cue index -> edited text (preserved across repaints)
    editing: null,       // cue index currently being edited inline
    image: false,        // VobSub / PGS picture subtitle
    ocr: null,           // server OCR status for picture subtitles
    ocrTimer: 0,         // status poller while OCR runs
    streams: [],         // VobSub language streams in the .idx
    auto: null,          // automatic sync (alass): {available, state, error, result, applied}
    autoTimer: 0,
    autoMode: "fine",
    ocrForce: false,     // next Run OCR throws the cached text away
};

function msToClock(ms) {
    const v = Math.max(0, Math.round(ms || 0));
    const h = Math.floor(v / 3600000);
    const m = Math.floor((v % 3600000) / 60000);
    const s = Math.floor((v % 60000) / 1000);
    const ms3 = v % 1000;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(ms3).padStart(3, "0")}`;
}

function msToClockShort(ms) {
    return msToClock(ms).replace(/^00:/, "");
}

function subSyncClose() {
    const modal = document.getElementById("sub-sync-modal");
    const video = document.getElementById("sub-sync-video");
    if (video) {
        video.pause();
        video.removeAttribute("src");
        video.load();
    }
    if (subSyncState.previewUrl) {
        try { URL.revokeObjectURL(subSyncState.previewUrl); } catch (_) {}
        subSyncState.previewUrl = "";
    }
    clearInterval(subSyncState.poller);
    subSyncState.poller = 0;
    stopSubSyncOcrPoll();
    stopSubSyncAutoPoll();
    stopSubSyncVideoPoll();
    if (modal) modal.classList.add("hidden");
}

async function finishSubSync() {
    const videoPath = subSyncState.video;
    const subPath = subSyncState.path;
    subSyncClose();
    if (subPath) {
        try {
            await api("/api/v1/subs/synced", { method: "POST", body: { path: subPath } });
            // Show it at once in the Subtitles table; a reload of the pane shows the stored status.
            document.querySelectorAll(".sub-sync-btn[data-sub-path]").forEach((button) => {
                if (button.dataset.subPath !== subPath || button.parentElement.querySelector(".sub-synced")) return;
                button.insertAdjacentHTML("afterend", syncedBadge("just now"));
            });
        } catch (error) {
            notify(error.message || "Could not save the synced status.", "error");
        }
    }
    if (!videoPath) return;
    try {
        const out = await api("/api/v1/subs/video-discard", { method: "POST", body: { path: videoPath } });
        if (out && out.freed) notify("Marked as synced. Deleted the temporary preview copy of the video.", "success");
        else notify("Marked as synced.", "success");
    } catch (error) {
        notify(error.message || "Could not delete the preview copy.", "error");
    }
}

async function openSubSync(action) {
    const subPath = action && action.dataset ? action.dataset.subPath : "";
    const videoPath = action && action.dataset ? action.dataset.videoPath : "";
    if (!subPath || !videoPath) return;
    const modal = document.getElementById("sub-sync-modal");
    const body = document.getElementById("sub-sync-body");
    const video = document.getElementById("sub-sync-video");
    const timecode = document.getElementById("sub-sync-timecode");
    if (!modal || !body || !video) return;
    subSyncState.path = subPath;
    subSyncState.video = videoPath;
    subSyncState.anchors = [];
    subSyncState.selected = null;
    subSyncState.hasBackup = false;
    subSyncState.edits = {};
    subSyncState.streams = [];
    subSyncState.editing = null;
    subSyncState.mode = "linear";
    subSyncState.search = "";
    subSyncState.image = false;
    subSyncState.ocr = null;
    subSyncState.ocrForce = false;
    subSyncState.auto = null;
    stopSubSyncOcrPoll();
    stopSubSyncAutoPoll();
    body.innerHTML = `<p class="muted">Loading subtitles&hellip;</p>`;
    modal.classList.remove("hidden");
    video.removeAttribute("src");
    video.load();
    prepareSubSyncVideo(videoPath);
    loadSubSyncAuto();
    if (timecode) timecode.textContent = "0:00:00.000";
    try {
        const data = await api(`/api/v1/subs?path=${encodeURIComponent(subPath)}`);
        applySubSyncData(data);
        if (subSyncState.image && !(subSyncState.ocr && subSyncState.ocr.state === "done")) {
            paintSubSyncOcr();
            attachSubSyncVideo();
            const ocr = subSyncState.ocr || {};
            if (ocr.state === "running") startSubSyncOcrPoll();
            // Nothing useful can be done with the pictures until they are read, so just start
            // (an earlier, cancelled run resumes). An error is left on screen for the user.
            else if (ocr.state === "needed" && ocr.tesseract !== false) startSubSyncOcr();
            return;
        }
        paintSubSync();
        attachSubSyncVideo();
        refreshSubSyncPreview();
    } catch (error) {
        body.innerHTML = `<p class="scan-status is-failed">${escapeHtml(error.message || "Could not read the subtitle file.")}</p>`;
    }
}

// ---------- the video ------------------------------------------------------------------

let subSyncVideoTimer = 0;

function _setVideoNote(text, failed) {
    const note = document.getElementById("sub-sync-video-note");
    if (!note) return;
    note.textContent = text || "";
    note.classList.toggle("hidden", !text);
    note.classList.toggle("is-failed", !!failed);
}

function stopSubSyncVideoPoll() {
    clearInterval(subSyncVideoTimer);
    subSyncVideoTimer = 0;
}

// Browsers cannot play every file a library holds (XviD AVI, AC-3/DTS audio, HEVC...). The server
// says whether the file plays as it is; if not, it builds a small H.264 copy once and caches it.
async function prepareSubSyncVideo(videoPath) {
    stopSubSyncVideoPoll();
    const video = document.getElementById("sub-sync-video");
    if (!video) return;
    const apply = (state) => {
        if (subSyncState.video !== videoPath) return true;
        if (state.state === "ready") {
            _setVideoNote("");
            video.src = state.url;
            video.load();
            return true;
        }
        if (state.state === "error") {
            _setVideoNote(`The video could not be prepared for playing: ${state.error || "ffmpeg failed"}`, true);
            return true;
        }
        _setVideoNote(`Your browser cannot play ${state.reason || "this video"}, so a small copy is being prepared (${state.percent || 0}%). It is made once and reused.`);
        return false;
    };
    try {
        const state = await api("/api/v1/subs/video", { method: "POST", body: { path: videoPath } });
        if (apply(state)) return;
    } catch (error) {
        _setVideoNote(error.message || "The video could not be prepared.", true);
        return;
    }
    subSyncVideoTimer = setInterval(async () => {
        if (subSyncState.video !== videoPath) { stopSubSyncVideoPoll(); return; }
        try {
            const state = await api(`/api/v1/subs/video-status?path=${encodeURIComponent(videoPath)}`);
            if (apply(state)) stopSubSyncVideoPoll();
        } catch (_) { /* try again on the next tick */ }
    }, 2000);
}

function applySubSyncData(data) {
    subSyncState.format = data.format;
    subSyncState.duration = data.duration_ms || 0;
    subSyncState.cues = data.cues || [];
    subSyncState.hasBackup = !!data.has_backup;
    subSyncState.image = !!data.image;
    subSyncState.ocr = data.ocr || null;
    if (data.streams) subSyncState.streams = data.streams;
}

// ---------- picture subtitles: OCR ---------------------------------------------------

function stopSubSyncOcrPoll() {
    clearInterval(subSyncState.ocrTimer);
    subSyncState.ocrTimer = 0;
}

function _ocrPercent(ocr) {
    const total = (ocr && ocr.total) || 0;
    return total ? Math.min(100, Math.round(((ocr.done || 0) * 100) / total)) : 0;
}

function paintSubSyncOcr() {
    const body = document.getElementById("sub-sync-body");
    if (!body) return;
    const ocr = subSyncState.ocr || {};
    const running = ocr.state === "running";
    const done = ocr.done || 0;
    const total = ocr.total || 0;
    const kind = subSyncState.format === "pgs" ? "PGS (.sup)" : "VobSub (.idx + .sub)";
    const langs = ocr.langs || [];
    const options = langs.map((lang) => `<option value="${escapeHtml(lang)}"${lang === ocr.lang ? " selected" : ""}>${escapeHtml(lang)}</option>`).join("");
    const resume = done > 0 && done < total && !subSyncState.ocrForce;
    const runLabel = subSyncState.ocrForce ? "Redo OCR" : resume ? `Resume OCR (${done} of ${total} done)` : "Run OCR";
    const missing = ocr.tesseract === false
        ? `<p class="scan-status is-failed">tesseract is not installed in this container, so picture subtitles cannot be read. Rebuild the image (the Dockerfile now includes it) and open this again.</p>`
        : "";
    const error = ocr.state === "error" && ocr.error ? `<p class="scan-status is-failed">${escapeHtml(ocr.error)}</p>` : "";
    const note = ocr.lang_note ? `<p class="muted">${escapeHtml(ocr.lang_note)}.</p>` : "";
    const back = subSyncState.cues.length && !running
        ? `<button type="button" class="btn-ghost" data-action="sub-sync-ocr-back">Back to the lines</button>` : "";
    body.innerHTML = `<div class="sub-sync-ocr">
        <h3>Picture subtitle &middot; ${escapeHtml(kind)}</h3>
        <p>This subtitle is stored as pictures, so its lines have to be recognised (OCR) before you can search them or pick anchors.
        That is done once and remembered. Saving a sync only rewrites the timing &mdash; the pictures stay exactly as they are.</p>
        ${missing}${error}${note}
        <div class="sub-sync-ocr-row">
            <label class="sub-sync-ocr-lang">Language
                <select id="sub-sync-ocr-lang" ${running || !langs.length ? "disabled" : ""}>${options}</select>
            </label>
            ${running
                ? `<button type="button" class="btn-ghost" data-action="sub-sync-ocr-cancel">Cancel</button>`
                : `<button type="button" data-action="sub-sync-ocr-start" ${ocr.tesseract === false ? "disabled" : ""}>${escapeHtml(runLabel)}</button>`}
            ${back}
        </div>
        <div class="sub-sync-ocr-bar" aria-hidden="true"><span id="sub-sync-ocr-fill" style="width:${_ocrPercent(ocr)}%"></span></div>
        <p class="muted" id="sub-sync-ocr-text">${escapeHtml(_ocrText(ocr))}</p>
        ${subSyncAutoHtml()}
    </div>`;
}

function _ocrText(ocr) {
    const done = ocr.done || 0;
    const total = ocr.total || 0;
    if (ocr.state === "running") return `Recognising ${done} of ${total} pictures (${_ocrPercent(ocr)}%). This keeps running if you close this window.`;
    if (total) return `${total} pictures found${done ? `, ${done} already recognised` : ""}. A full episode usually takes a few minutes.`;
    return "";
}

function updateSubSyncOcrProgress() {
    const fill = document.getElementById("sub-sync-ocr-fill");
    const text = document.getElementById("sub-sync-ocr-text");
    if (!fill || !text) return paintSubSyncOcr();
    const ocr = subSyncState.ocr || {};
    fill.style.width = `${_ocrPercent(ocr)}%`;
    text.textContent = _ocrText(ocr);
}

async function startSubSyncOcr() {
    const select = document.getElementById("sub-sync-ocr-lang");
    try {
        const status = await api("/api/v1/subs/ocr", {
            method: "POST",
            body: { path: subSyncState.path, lang: select ? select.value : "", force: !!subSyncState.ocrForce },
        });
        subSyncState.ocrForce = false;
        subSyncState.ocr = status;
        paintSubSyncOcr();
        startSubSyncOcrPoll();
    } catch (error) {
        notify(error.message || "Could not start OCR.", "error");
    }
}

async function cancelSubSyncOcr() {
    try {
        subSyncState.ocr = await api("/api/v1/subs/ocr-cancel", { method: "POST", body: { path: subSyncState.path } });
        updateSubSyncOcrProgress();
    } catch (error) {
        notify(error.message || "Could not cancel OCR.", "error");
    }
}

function startSubSyncOcrPoll() {
    stopSubSyncOcrPoll();
    const path = subSyncState.path;
    subSyncState.ocrTimer = setInterval(async () => {
        if (subSyncState.path !== path) { stopSubSyncOcrPoll(); return; }
        try {
            const status = await api(`/api/v1/subs/ocr-status?path=${encodeURIComponent(path)}`);
            if (subSyncState.path !== path) return;
            subSyncState.ocr = status;
            if (status.state === "running") { updateSubSyncOcrProgress(); return; }
            stopSubSyncOcrPoll();
            if (status.state === "done") await finishSubSyncOcr();
            else paintSubSyncOcr();
        } catch (_) { /* a missed poll is fine, the next one catches up */ }
    }, 1500);
}

async function finishSubSyncOcr() {
    try {
        const data = await api(`/api/v1/subs?path=${encodeURIComponent(subSyncState.path)}`);
        applySubSyncData(data);
        subSyncState.anchors = [];
        subSyncState.selected = null;
        paintSubSync();
        refreshSubSyncPreview();
        notify(`Recognised ${subSyncState.cues.length} lines.`, "success");
    } catch (error) {
        notify(error.message || "Could not load the recognised lines.", "error");
    }
}

async function exportSubSyncSrt(overwrite) {
    try {
        const data = await api("/api/v1/subs/export-srt", {
            method: "POST",
            body: {
                path: subSyncState.path,
                anchors: subSyncState.anchors.map((a) => ({ sub_ms: a.sub_ms, video_ms: a.video_ms })),
                mode: subSyncState.mode,
                cue_edits: _subSyncEditsArray(),
                overwrite: !!overwrite,
            },
        });
        notify(`Wrote ${data.name} (${data.cues} lines).`, "success");
    } catch (error) {
        if (error.status === 409 && /already exists/i.test(error.message || "")) {
            askDanger(
                "Replace the existing SRT?",
                `${error.message}. Replacing keeps the old one as a .sync-backup next to it.`,
                "Replace",
                () => exportSubSyncSrt(true),
                false,
            );
            return;
        }
        notify(error.message || "Export failed.", "error");
    }
}

function attachSubSyncVideo() {
    const video = document.getElementById("sub-sync-video");
    const timecode = document.getElementById("sub-sync-timecode");
    if (!video) return;
    video.ontimeupdate = () => {
        if (!timecode) return;
        timecode.textContent = msToClock((video.currentTime || 0) * 1000);
    };
    clearInterval(subSyncState.poller);
    subSyncState.poller = setInterval(() => {
        if (!timecode) return;
        timecode.textContent = msToClock((video.currentTime || 0) * 1000);
    }, 250);
}

function subSyncHeader() {
    const anchors = subSyncState.anchors.length;
    let mode = "No sync yet";
    let detail = "Pick a cue, scrub the video to where it should appear, press Mark.";
    if (subSyncState.mode === "steps" && anchors >= 1) {
        mode = `Stepwise fit (automatic): ${anchors} stretch${anchors === 1 ? "" : "es"}, each with its own offset`;
        detail = "Check a few lines at the start, middle and end against the video, then Save. Marking more anchors keeps the stretches; Reset anchors starts over.";
    } else if (anchors === 1) {
        const first = subSyncState.anchors[0];
        const delta = first.video_ms - first.sub_ms;
        mode = `Constant offset: ${delta >= 0 ? "+" : "−"}${msToClockShort(Math.abs(delta))}`;
        detail = "Add one more anchor near the end to also catch framerate drift.";
    } else if (anchors >= 2) {
        const sorted = subSyncState.anchors.slice().sort((a, b) => a.sub_ms - b.sub_ms);
        const [first, last] = [sorted[0], sorted[sorted.length - 1]];
        if (subSyncState.mode === "piecewise") {
            mode = `Piecewise fit: ${sorted.length - 1} segment${sorted.length - 1 === 1 ? "" : "s"} (each anchor pair gets its own slope and offset)`;
            detail = "Useful for files whose drift resets between anchors — commercials removed, concatenated reels, etc.";
        } else {
            const scale = (last.video_ms - first.video_ms) / Math.max(1, last.sub_ms - first.sub_ms);
            const offset = first.video_ms - scale * first.sub_ms;
            mode = `Linear fit: scale ×${scale.toFixed(5)}, offset ${offset >= 0 ? "+" : "−"}${msToClockShort(Math.abs(offset))}`;
            if (anchors >= 3) {
                const middles = sorted.slice(1, -1);
                const worst = middles.reduce((acc, a) => {
                    const fitted = scale * a.sub_ms + offset;
                    const drift = Math.abs(fitted - a.video_ms);
                    return drift > acc ? drift : acc;
                }, 0);
                detail = `Middle anchor drift: ${Math.round(worst)} ms (anything over 500 ms suggests the file was re-cut — try the Piecewise toggle below).`;
            } else {
                detail = "Add a third anchor somewhere in the middle to verify there is no drift between anchors.";
            }
        }
    }
    const hint = framerateHint();
    const banner = hint ? `<p class="scan-status is-warning">${escapeHtml(hint)}</p>` : "";
    const image = subSyncState.image;
    const canSave = anchors >= 1 || (!image && Object.keys(subSyncState.edits).length > 0);
    const canRevert = subSyncState.hasBackup;
    const imageNote = image
        ? `<p class="muted sub-sync-detail">Picture subtitle: Save retimes the pictures in place and they stay pictures. Edited text is only used by Export SRT. A fit that stretches time moves when each picture appears, but every picture keeps its own length on screen.</p>${subSyncStreamNote()}`
        : "";
    const shiftRow = `<div class="sub-sync-shift">
            <span class="muted">Shift all lines</span>
            <button type="button" class="btn-ghost" data-action="sub-sync-nudge" data-ms="-1000">−1 s</button>
            <button type="button" class="btn-ghost" data-action="sub-sync-nudge" data-ms="-100">−100 ms</button>
            <button type="button" class="btn-ghost" data-action="sub-sync-nudge" data-ms="100">+100 ms</button>
            <button type="button" class="btn-ghost" data-action="sub-sync-nudge" data-ms="1000">+1 s</button>
            <input id="sub-sync-shift" type="text" inputmode="decimal" placeholder="+2.5 s" size="7" autocomplete="off" spellcheck="false" title="Seconds, or add ms for milliseconds: +2.5, -0.3, 250ms">
            <button type="button" class="btn-ghost" data-action="sub-sync-shift-apply">Shift</button>
        </div>`;
    const imageButtons = image
        ? `<button type="button" class="btn-ghost" data-action="sub-sync-export-srt" ${subSyncState.cues.length ? "" : "disabled"} title="Write the recognised text, with the current anchors and your edits, as a .srt next to this subtitle">Export SRT</button>
            <button type="button" class="btn-ghost" data-action="sub-sync-ocr-redo" title="Recognise the pictures again, for example with another language">Redo OCR</button>`
        : "";
    return `<div class="sub-sync-head">
        <p class="sub-sync-mode"><strong>${escapeHtml(mode)}</strong></p>
        <p class="muted sub-sync-detail">${escapeHtml(detail)}</p>
        ${banner}
        ${imageNote}
        ${shiftRow}
        ${subSyncAutoHtml()}
        <div class="sub-sync-actions">
            <button type="button" class="btn-ghost" data-action="sub-sync-save" ${canSave ? "" : "disabled"}>Save</button>
            <button type="button" class="btn-ghost" data-action="sub-sync-reset" ${anchors ? "" : "disabled"}>Reset anchors</button>
            <button type="button" class="btn-ghost btn-remove" data-action="sub-sync-revert" ${canRevert ? "" : "disabled"}>Revert to backup</button>
            ${imageButtons}
            <label class="choice sub-sync-mode-toggle${anchors >= 2 ? "" : " is-disabled"}" title="${anchors >= 2 ? "Fit each anchor pair separately. Needed when the file was re-cut between anchors." : "Needs at least two anchors."}">
                <input type="checkbox" id="sub-sync-mode-check" ${subSyncState.mode === "piecewise" ? "checked" : ""} ${anchors >= 2 ? "" : "disabled"}> Piecewise
            </label>
            <span class="muted sub-sync-path" title="${escapeHtml(subSyncState.path)}">${escapeHtml(subSyncState.path.split(/[\\/]/).pop() || "")}</span>
        </div>
    </div>`;
}

// ---------- automatic sync (alass) ------------------------------------------------------

function stopSubSyncAutoPoll() {
    clearInterval(subSyncState.autoTimer);
    subSyncState.autoTimer = 0;
}

function subSyncAutoHtml() {
    const auto = subSyncState.auto;
    if (!auto || !auto.available) return "";
    const running = auto.state === "running";
    let note = "";
    if (running) note = "Listening to the video and matching its speech to the subtitle. This can take a few minutes, and it keeps running if you close this window.";
    else if (auto.state === "error") note = auto.error || "Automatic sync failed.";
    else if (auto.applied) note = auto.applied;
    const mode = subSyncState.autoMode;
    return `<div class="sub-sync-auto">
        <button type="button" class="btn-auto-sync" data-action="sub-sync-auto-start" ${running ? "disabled" : ""} title="Match the subtitle to the speech in the video (alass). Nothing is written until you press Save.">Sync automatically</button>
        <select id="sub-sync-auto-mode" ${running ? "disabled" : ""} title="Fine-tune only accepts small corrections, so a subtitle that is already in sync cannot be thrown off. The other two accept any size; Allow cuts finds a separate shift for each stretch.">
            <option value="fine" ${mode === "fine" ? "selected" : ""}>Fine-tune (up to 5 s)</option>
            <option value="shift" ${mode === "shift" ? "selected" : ""}>One shift, any size</option>
            <option value="cuts" ${mode === "cuts" ? "selected" : ""}>Allow cuts, any size</option>
        </select>
        ${running ? `<button type="button" class="btn-ghost" data-action="sub-sync-auto-cancel">Cancel</button>` : ""}
        <span class="muted ${auto.state === "error" ? "is-failed" : ""}" id="sub-sync-auto-note">${escapeHtml(note)}</span>
    </div>`;
}

function repaintSubSyncAuto() {
    const now = document.querySelector("#sub-sync-body .sub-sync-auto");
    if (!now) return;
    now.outerHTML = subSyncAutoHtml();
    bindSubSyncAutoSelect();
}

function bindSubSyncAutoSelect() {
    const select = document.getElementById("sub-sync-auto-mode");
    if (select) select.addEventListener("change", (ev) => { subSyncState.autoMode = ev.target.value; });
}

async function loadSubSyncAuto() {
    try {
        const status = await api(`/api/v1/subs/auto-status?path=${encodeURIComponent(subSyncState.path)}`);
        subSyncState.auto = { ...status, applied: "" };
        if (status.state === "running") startSubSyncAutoPoll();
        repaintSubSyncAuto();
        if (document.querySelector("#sub-sync-body .sub-sync-head")) repaintSubSyncHeader();
        else if (subSyncState.image && !subSyncState.cues.length && document.querySelector("#sub-sync-body .sub-sync-ocr")) paintSubSyncOcr();
    } catch (_) {
        subSyncState.auto = null;
    }
}

async function startSubSyncAuto() {
    const select = document.getElementById("sub-sync-auto-mode");
    if (select) subSyncState.autoMode = select.value;
    try {
        const status = await api("/api/v1/subs/auto", {
            method: "POST",
            body: { path: subSyncState.path, video: subSyncState.video, mode: subSyncState.autoMode },
        });
        subSyncState.auto = { ...status, applied: "" };
        startSubSyncAutoPoll();
    } catch (error) {
        subSyncState.auto = { ...(subSyncState.auto || { available: true }), state: "error", error: error.message || "Automatic sync could not start." };
    }
    repaintSubSyncAuto();
}

async function cancelSubSyncAuto() {
    try {
        const status = await api("/api/v1/subs/auto-cancel", { method: "POST", body: { path: subSyncState.path } });
        subSyncState.auto = { ...subSyncState.auto, ...status, applied: "" };
    } catch (_) { /* the poll shows the real state */ }
    repaintSubSyncAuto();
}

function startSubSyncAutoPoll() {
    stopSubSyncAutoPoll();
    subSyncState.autoTimer = setInterval(async () => {
        try {
            const status = await api(`/api/v1/subs/auto-status?path=${encodeURIComponent(subSyncState.path)}`);
            if (status.state === "running") return;
            stopSubSyncAutoPoll();
            subSyncState.auto = { ...status, applied: "" };
            if (status.state === "done" && status.result) applySubSyncAutoResult(status.result);
            else repaintSubSyncAuto();
        } catch (_) { /* keep polling */ }
    }, 2000);
}

function applySubSyncAutoResult(result) {
    // A subtitle that is already right should come back almost untouched. Say so instead of
    // moving it, and never apply a large move in fine-tune mode.
    if (result.rejected || result.unchanged) {
        subSyncState.auto.applied = result.rejected
            ? `alass suggests moving lines by up to ${(result.max_shift_ms / 1000).toFixed(1)} s. That is more than a subtitle that is nearly right needs, so nothing was changed. If this subtitle really is that far off, choose "One shift, any size".`
            : "The subtitle already matches the speech (alass found under 0.1 s of difference). Nothing was changed.";
        if (subSyncState.image && !subSyncState.cues.length) paintSubSyncOcr(); else repaintSubSyncAuto();
        return;
    }
    subSyncState.anchors = (result.anchors || []).map((a) => ({ index: a.index, sub_ms: a.sub_ms, video_ms: Math.max(0, a.video_ms) }));
    subSyncState.mode = result.mode === "steps" ? "steps" : "linear";
    const first = subSyncState.anchors[0];
    let text;
    if (result.mode === "steps") text = `Found ${result.segments} stretches with different offsets.`;
    else if (subSyncState.anchors.length > 1) text = "Found a steady drift (a different frame rate).";
    else text = first ? `Found one offset: ${first.video_ms - first.sub_ms >= 0 ? "+" : "−"}${msToClockShort(Math.abs(first.video_ms - first.sub_ms))}.` : "Nothing to change.";
    subSyncState.auto.applied = `${text} Check it against the video, then Save.`;
    subSyncState.selected = null;
    if (subSyncState.image && !subSyncState.cues.length) {
        paintSubSyncOcr();
    } else {
        paintSubSync();
        refreshSubSyncPreview();
    }
}

function subSyncStreamNote() {
    const streams = subSyncState.streams || [];
    if (streams.length < 2) return "";
    const names = streams.map((st) => st.id || `#${st.index}`).join(", ");
    return `<p class="muted sub-sync-detail">This .idx holds ${streams.length} language streams (${escapeHtml(names)}). Only the first is read and shown here; Save retimes every stream by the same amount.</p>`;
}

// "+2.5", "-0.3", "1,5", "250ms", "−1s" -> milliseconds, or null when it is not a number.
function parseSubSyncShift(text) {
    const m = String(text || "").trim().replace("\u2212", "-").replace(",", ".").match(/^([+-]?)\s*(\d+(?:\.\d+)?|\.\d+)\s*(ms|s)?$/i);
    if (!m) return null;
    let value = parseFloat(m[2]);
    value = (m[3] || "s").toLowerCase() === "ms" ? value : value * 1000;
    return Math.round(m[1] === "-" ? -value : value);
}

function nudgeSubSync(deltaMs) {
    const delta = Math.round(Number(deltaMs) || 0);
    if (!delta || !subSyncState.cues.length) return;
    if (subSyncState.anchors.length) {
        subSyncState.anchors.forEach((a) => { a.video_ms += delta; });
    } else {
        const cue = subSyncState.cues.find((c) => c.index === subSyncState.selected) || subSyncState.cues[0];
        subSyncState.anchors.push({ index: cue.index, sub_ms: cue.start_ms, video_ms: Math.max(0, cue.start_ms + delta) });
    }
    repaintSubSyncHeader();
    paintSubSyncList();
    syncMarkButton();
    refreshSubSyncPreview();
}

function applySubSyncShift() {
    const input = document.getElementById("sub-sync-shift");
    if (!input) return;
    const ms = parseSubSyncShift(input.value);
    if (ms === null) {
        input.classList.add("is-invalid");
        return;
    }
    nudgeSubSync(ms);
}

function framerateHint() {
    // The subtitle's apparent duration vs the video's reported duration. More than ~2% off
    // is almost always a different-framerate copy (23.976 vs 25, PAL vs NTSC).
    const video = document.getElementById("sub-sync-video");
    const vdur = video && isFinite(video.duration) ? video.duration * 1000 : 0;
    const sdur = subSyncState.duration;
    if (!vdur || !sdur) return "";
    const diff = Math.abs(vdur - sdur) / vdur;
    if (diff < 0.02) return "";
    return `The subtitle file ends about ${Math.round(diff * 100)}% ${sdur > vdur ? "later" : "earlier"} than the video. It looks like it was made for a different-framerate release — mark an anchor near the start AND near the end.`;
}

function paintSubSync() {
    const body = document.getElementById("sub-sync-body");
    if (!body) return;
    // The search bar lives in its own container that we never innerHTML away, so typing
    // never loses focus. Everything else - header, action buttons, list - repaints normally.
    body.innerHTML = `
        <div id="sub-sync-header-slot">${subSyncHeader()}</div>
        <div class="sub-sync-search-wrap">
            <input id="sub-sync-search" type="search" placeholder="Search cue text..." autocomplete="off" spellcheck="false" value="${escapeHtml(subSyncState.search || "")}">
            <span class="muted sub-sync-search-count" id="sub-sync-search-count"></span>
        </div>
        <div class="sub-sync-list" id="sub-sync-list"></div>
    `;
    const input = document.getElementById("sub-sync-search");
    if (input) {
        input.addEventListener("input", (ev) => updateSubSyncSearch(ev.target.value));
    }
    const check = document.getElementById("sub-sync-mode-check");
    if (check) check.addEventListener("change", (ev) => toggleSubSyncMode(!!ev.target.checked));
    bindSubSyncShiftKey();
    bindSubSyncAutoSelect();
    paintSubSyncList();
    syncMarkButton();
}

function bindSubSyncShiftKey() {
    const input = document.getElementById("sub-sync-shift");
    if (input) input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); applySubSyncShift(); } });
}

function repaintSubSyncHeader() {
    const slot = document.getElementById("sub-sync-header-slot");
    if (slot) slot.innerHTML = subSyncHeader();
    bindSubSyncShiftKey();
    bindSubSyncAutoSelect();
    const check = document.getElementById("sub-sync-mode-check");
    if (check) check.addEventListener("change", (ev) => toggleSubSyncMode(!!ev.target.checked));
}

function _subSyncVisibleCues() {
    const q = (subSyncState.search || "").trim().toLowerCase();
    if (!q) return { cues: subSyncState.cues, query: "" };
    const visible = subSyncState.cues.filter((cue) => String(cue.text || "").toLowerCase().includes(q));
    return { cues: visible, query: q };
}

function _highlight(text, q) {
    const safe = escapeHtml(text || "");
    if (!q) return safe;
    const needle = escapeHtml(q);
    // escapeHtml output is literal, so needle characters still match literally. Build a
    // regex that is case-insensitive and escapes any regex metacharacters in the needle.
    const pattern = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    try {
        return safe.replace(new RegExp(pattern, "gi"), (m) => `<mark>${m}</mark>`);
    } catch (_) {
        return safe;
    }
}

function paintSubSyncList() {
    const list = document.getElementById("sub-sync-list");
    const counter = document.getElementById("sub-sync-search-count");
    if (!list) return;
    const { cues, query } = _subSyncVisibleCues();
    const anchorByCue = new Map(subSyncState.anchors.map((a) => [a.index, a]));
    if (counter) {
        if (query) counter.textContent = `${cues.length} / ${subSyncState.cues.length} cues`;
        else counter.textContent = `${subSyncState.cues.length} cues`;
    }
    if (!cues.length) {
        list.innerHTML = `<p class="muted sub-sync-empty">No cues match "${escapeHtml(query)}".</p>`;
        return;
    }
    list.innerHTML = cues.map((cue) => {
        const isAnchor = anchorByCue.has(cue.index);
        const anchor = anchorByCue.get(cue.index);
        const sel = subSyncState.selected === cue.index ? " is-selected" : "";
        const anchorBadge = isAnchor
            ? `<span class="sub-sync-anchor-badge" title="Anchored at video time ${msToClock(anchor.video_ms)}">⚓ ${msToClock(anchor.video_ms)}</span>`
            : "";
        const edited = Object.prototype.hasOwnProperty.call(subSyncState.edits, cue.index);
        const displayText = edited ? subSyncState.edits[cue.index] : (cue.text || "");
        const editing = subSyncState.editing === cue.index;
        const textCell = editing
            ? `<textarea class="sub-sync-edit" data-cue-index="${cue.index}" rows="${Math.max(1, (displayText.match(/\n/g) || []).length + 1)}">${escapeHtml(displayText)}</textarea>`
            : `<span class="sub-sync-text${edited ? " is-edited" : ""}" title="${edited ? "Edited — click Edit again to change, Revert resets the file" : ""}">${_highlight(displayText, query)}</span>`;
        const editControl = editing
            ? `<button type="button" class="btn-ghost sub-sync-edit-btn" data-action="sub-sync-text-done" data-cue-index="${cue.index}" title="Save this edit">Done</button>`
            : `<button type="button" class="btn-ghost sub-sync-edit-btn" data-action="sub-sync-text-edit" data-cue-index="${cue.index}" title="Edit this cue text">Edit</button>`;
        return `<div class="sub-sync-row${sel}${isAnchor ? " is-anchor" : ""}${edited ? " is-edited-row" : ""}" data-cue-index="${cue.index}" data-sub-ms="${cue.start_ms}">
            <button type="button" class="sub-sync-time" data-action="sub-sync-seek" data-ms="${cue.start_ms}" title="Seek the video here">${msToClockShort(cue.start_ms)}</button>
            ${textCell}
            ${anchorBadge}
            ${editControl}
            <button type="button" class="btn-ghost sub-sync-anchor-btn" data-action="sub-sync-toggle-anchor" data-cue-index="${cue.index}">${isAnchor ? "Un-anchor" : "Pick"}</button>
        </div>`;
    }).join("");
    // When a row is in edit mode, focus the textarea so the user can type straight away.
    if (subSyncState.editing != null) {
        const t = list.querySelector(`textarea[data-cue-index="${subSyncState.editing}"]`);
        if (t) { t.focus(); t.select(); }
    }
}

function updateSubSyncSearch(value) {
    subSyncState.search = String(value || "");
    paintSubSyncList();
}

function startSubSyncEdit(index) {
    const num = Number(index);
    const cue = subSyncState.cues.find((c) => c.index === num);
    if (!cue) return;
    // Seed the edits map with the current text so cancelling leaves nothing dangling.
    if (!Object.prototype.hasOwnProperty.call(subSyncState.edits, num)) {
        subSyncState.edits[num] = cue.text || "";
    }
    subSyncState.editing = num;
    subSyncState.selected = num;
    paintSubSyncList();
    syncMarkButton();
}

function finishSubSyncEdit(index) {
    const num = Number(index);
    const list = document.getElementById("sub-sync-list");
    const t = list ? list.querySelector(`textarea[data-cue-index="${num}"]`) : null;
    if (t) {
        const original = (subSyncState.cues.find((c) => c.index === num) || {}).text || "";
        const value = t.value;
        if (value === original) delete subSyncState.edits[num];
        else subSyncState.edits[num] = value;
    }
    subSyncState.editing = null;
    paintSubSyncList();
    refreshSubSyncPreview();
}

function toggleSubSyncMode(checked) {
    subSyncState.mode = checked ? "piecewise" : "linear";
    repaintSubSyncHeader();
    paintSubSyncList();
    refreshSubSyncPreview();
}

function syncMarkButton() {
    const btn = document.getElementById("sub-sync-mark-btn");
    const note = document.getElementById("sub-sync-mark-note");
    if (!btn) return;
    btn.disabled = subSyncState.selected == null;
    if (!note) return;
    if (subSyncState.selected == null) {
        note.textContent = "Select a cue, scrub to where it should be, then press Mark.";
    } else {
        const cue = subSyncState.cues.find((c) => c.index === subSyncState.selected);
        note.textContent = cue ? `Will anchor cue #${cue.index} (${msToClockShort(cue.start_ms)}): “${(cue.text || "").slice(0, 60)}”` : "";
    }
}

function selectSubSyncCue(index) {
    subSyncState.selected = Number(index) || null;
    document.querySelectorAll("#sub-sync-list .sub-sync-row").forEach((row) => {
        row.classList.toggle("is-selected", Number(row.dataset.cueIndex) === subSyncState.selected);
    });
    const current = document.querySelector(`#sub-sync-list .sub-sync-row.is-selected`);
    if (current) current.scrollIntoView({ block: "nearest" });
    syncMarkButton();
}

function toggleSubSyncAnchor(index) {
    const num = Number(index);
    const existing = subSyncState.anchors.findIndex((a) => a.index === num);
    if (existing >= 0) {
        subSyncState.anchors.splice(existing, 1);
    } else {
        const cue = subSyncState.cues.find((c) => c.index === num);
        if (!cue) return;
        const video = document.getElementById("sub-sync-video");
        const videoMs = Math.round(((video && video.currentTime) || 0) * 1000);
        subSyncState.anchors.push({ index: num, sub_ms: cue.start_ms, video_ms: videoMs });
    }
    subSyncState.selected = num;
    repaintSubSyncHeader();
    paintSubSyncList();
    syncMarkButton();
    refreshSubSyncPreview();
}

function markSubSyncAnchor() {
    if (subSyncState.selected == null) return;
    const cue = subSyncState.cues.find((c) => c.index === subSyncState.selected);
    if (!cue) return;
    const video = document.getElementById("sub-sync-video");
    const videoMs = Math.round(((video && video.currentTime) || 0) * 1000);
    const existing = subSyncState.anchors.findIndex((a) => a.index === cue.index);
    if (existing >= 0) subSyncState.anchors[existing].video_ms = videoMs;
    else subSyncState.anchors.push({ index: cue.index, sub_ms: cue.start_ms, video_ms: videoMs });
    repaintSubSyncHeader();
    paintSubSyncList();
    syncMarkButton();
    refreshSubSyncPreview();
}

async function refreshSubSyncPreview() {
    const video = document.getElementById("sub-sync-video");
    if (!video) return;
    // Remove any <track> we previously added.
    [...video.querySelectorAll("track[data-sub-sync]")].forEach((t) => t.remove());
    // Also release the previous blob so we don't leak object URLs.
    if (subSyncState.previewUrl) {
        try { URL.revokeObjectURL(subSyncState.previewUrl); } catch (_) {}
        subSyncState.previewUrl = "";
    }
    try {
        const res = await fetch(`/api/v1/subs/preview-track`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                path: subSyncState.path,
                anchors: subSyncState.anchors,
                mode: subSyncState.mode,
                cue_edits: _subSyncEditsArray(),
            }),
        });
        if (!res.ok) return;
        const vtt = await res.text();
        const blob = new Blob([vtt], { type: "text/vtt" });
        subSyncState.previewUrl = URL.createObjectURL(blob);
        const track = document.createElement("track");
        track.kind = "subtitles";
        track.label = "Preview";
        track.srclang = "und";
        track.src = subSyncState.previewUrl;
        track.default = true;
        track.setAttribute("data-sub-sync", "1");
        video.appendChild(track);
        // Force the newly-added track on; browsers often default new tracks to disabled.
        setTimeout(() => {
            [...video.textTracks].forEach((t) => { t.mode = t.label === "Preview" ? "showing" : "disabled"; });
        }, 50);
    } catch (_) {}
}

function _subSyncEditsArray() {
    return Object.entries(subSyncState.edits).map(([index, text]) => ({ index: Number(index), text: String(text) }));
}

async function saveSubSync() {
    const editCount = Object.keys(subSyncState.edits).length;
    if (!subSyncState.anchors.length && (subSyncState.image || !editCount)) return;
    try {
        const data = await api("/api/v1/subs/sync", {
            method: "POST",
            body: {
                path: subSyncState.path,
                anchors: subSyncState.anchors.map((a) => ({ sub_ms: a.sub_ms, video_ms: a.video_ms })),
                mode: subSyncState.mode,
                cue_edits: subSyncState.image ? [] : _subSyncEditsArray(),
            },
        });
        subSyncState.cues = data.cues || subSyncState.cues;
        subSyncState.hasBackup = !!data.has_backup;
        // Anchors still identify by subtitle time, so after save the sub times have changed:
        // move each anchor's sub_ms to the new start_ms of that cue index.
        const indexToCue = new Map((data.cues || []).map((c) => [c.index, c]));
        subSyncState.anchors = subSyncState.anchors.map((a) => {
            const cue = indexToCue.get(a.index);
            return cue ? { index: a.index, sub_ms: cue.start_ms, video_ms: cue.start_ms } : a;
        });
        paintSubSync();
        refreshSubSyncPreview();
        if (!subSyncState.image) {          // picture subtitles keep edits for Export SRT
            subSyncState.edits = {};
            subSyncState.editing = null;
        }
        notify(`Saved. Previous timings kept as ${subSyncState.path.split(/[\\/]/).pop()}.sync-backup.`, "success");
    } catch (error) {
        notify(error.message || "Save failed.", "error");
    }
}

async function revertSubSync() {
    try {
        const data = await api("/api/v1/subs/revert", { method: "POST", body: { path: subSyncState.path } });
        subSyncState.cues = data.cues || [];
        subSyncState.anchors = [];
        subSyncState.hasBackup = false;
        paintSubSync();
        refreshSubSyncPreview();
        notify("Reverted to the backup.", "info");
    } catch (error) {
        notify(error.message || "Revert failed.", "error");
    }
}

function resetSubSyncAnchors() {
    subSyncState.anchors = [];
    if (subSyncState.mode === "steps") subSyncState.mode = "linear";
    paintSubSync();
    refreshSubSyncPreview();
}

// Routing hooks: these names are picked up by the dispatcher in events.js
const SUB_SYNC_ACTIONS = {
    "sub-sync-open": (action) => openSubSync(action),
    "sub-sync-mark": () => markSubSyncAnchor(),
    "sub-sync-toggle-anchor": (action) => toggleSubSyncAnchor(action.dataset.cueIndex),
    "sub-sync-seek": (action) => {
        const video = document.getElementById("sub-sync-video");
        if (video) video.currentTime = (Number(action.dataset.ms) || 0) / 1000;
    },
    "sub-sync-auto-start": () => startSubSyncAuto(),
    "sub-sync-auto-cancel": () => cancelSubSyncAuto(),
    "sub-sync-done": () => finishSubSync(),
    "sub-sync-nudge": (action) => nudgeSubSync(action.dataset.ms),
    "sub-sync-shift-apply": () => applySubSyncShift(),
    "sub-sync-save": () => saveSubSync(),
    "sub-sync-reset": () => resetSubSyncAnchors(),
    "sub-sync-revert": () => revertSubSync(),
    "sub-sync-text-edit": (action) => startSubSyncEdit(action.dataset.cueIndex),
    "sub-sync-text-done": (action) => finishSubSyncEdit(action.dataset.cueIndex),
    "sub-sync-ocr-start": () => startSubSyncOcr(),
    "sub-sync-ocr-cancel": () => cancelSubSyncOcr(),
    "sub-sync-ocr-redo": () => {
        subSyncState.ocrForce = true;
        subSyncState.ocr = { ...(subSyncState.ocr || {}), state: "needed", done: 0 };
        paintSubSyncOcr();
    },
    "sub-sync-ocr-back": () => {
        subSyncState.ocrForce = false;
        subSyncState.ocr = { ...(subSyncState.ocr || {}), state: "done" };
        paintSubSync();
    },
    "sub-sync-export-srt": () => exportSubSyncSrt(false),
};
