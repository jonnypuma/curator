/**
 * Synced Lyrics Editor
 *
 * Opens when the user clicks #player-lyrics-edit (only visible when the
 * current track has lyrics_type === "lrc").  The editor lets the user:
 *   - Space         stamp the current audio playback position on the focused line
 *   - Shift+Space   stamp and move back one line
 *   - ↑ / ↓        navigate between lines
 *   - ← / →        nudge the focused line ±100 ms
 *   - Shift all     nudge every line by +-100 ms / +-1 s or a typed amount
 *   - Fit           mark anchors at the playhead and fit the lines (linear / piecewise / steps),
 *                   previewed live while the song plays
 *   - M             mark the selected line as an anchor at the playhead
 *   - Enter         edit the text of the selected line; Ctrl+Z / Undo steps back
 *   - Save          PUT /api/tracks/{id}/lyrics (the previous file is kept as .lrc.sync-backup)
 *   - Sync OK       saves, marks the lyrics Synced and closes
 *
 * The editor reuses the main #player <audio> element (full-playback mode).
 */

/* ---------- state -------------------------------------------------------- */
let _lrcLines = [];   // [{ ts: number|null, text: string }]  ts = ms
let _selectedIdx = 0;
let _trackId = null;
let _dirty = false;
// When true the editor is open and playback should drive line highlighting.
// Stamping a line temporarily pauses follow-mode for 2 s so the user can
// finish a stamp action without the cursor jumping away.
let _followPlayback = false;
let _followPauseUntil = 0;
let _base = [];       // timestamps without the pending anchor fit
let _anchors = [];    // [{ index, sub_ms, video_ms }]
let _undo = [];       // snapshots of _lrcLines
let _hasBackup = false;
let _synced = null;
let _findFrom = -1;

/* ---------- helpers ------------------------------------------------------- */

function _msToTimestamp(ms) {
    if (ms === null || ms === undefined || !Number.isFinite(ms)) return "[??:??.??]";
    const totalSec = Math.max(0, Math.floor(ms / 1000));
    const centis = Math.floor((Math.max(0, ms) % 1000) / 10);
    const minutes = Math.floor(totalSec / 60);
    const seconds = totalSec % 60;
    return `[${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(centis).padStart(2, "0")}]`;
}

function _timestampToMs(tag) {
    // [mm:ss.cc] or [mm:ss:cc]
    const m = tag.match(/\[(\d+):(\d+)[.:](\d+)\]/);
    if (!m) return null;
    const minutes = parseInt(m[1], 10);
    const seconds = parseInt(m[2], 10);
    const centis = parseInt(m[3], 10);
    return (minutes * 60 + seconds) * 1000 + centis * 10;
}

function _parseLrc(raw) {
    const lines = raw.split("\n");
    const result = [];
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        // metadata tags like [ar:…] — keep as non-timestamped lines
        const tsMatch = trimmed.match(/^(\[\d+:\d+[.:]\d+\])(.*)/);
        if (tsMatch) {
            const ts = _timestampToMs(tsMatch[1]);
            const text = tsMatch[2].trim();
            result.push({ ts, text });
        } else {
            result.push({ ts: null, text: trimmed });
        }
    }
    return result;
}

function _serializeLrc(lines, offsetMs) {
    return lines
        .map((line) => {
            if (line.ts === null) return line.text;
            const ms = Math.max(0, line.ts + (offsetMs || 0));
            return _msToTimestamp(ms) + line.text;
        })
        .join("\n") + "\n";
}

/* ---------- fit maths (mirrors curator/video/sub_sync.py) ------------------ */

function lrcPairs(anchors) {
    return (anchors || [])
        .filter((a) => Number.isFinite(a.sub_ms) && Number.isFinite(a.video_ms))
        .map((a) => [a.sub_ms, a.video_ms])
        .sort((p, q) => p[0] - q[0]);
}

function lrcLinear(pairs) {
    if (!pairs.length) return [1, 0];
    if (pairs.length === 1) return [1, pairs[0][1] - pairs[0][0]];
    const n = pairs.length;
    let sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (const [x, y] of pairs) { sx += x; sy += y; sxx += x * x; sxy += x * y; }
    const denom = n * sxx - sx * sx;
    if (denom === 0) { const last = pairs[n - 1]; return [1, last[1] - last[0]]; }
    const a = (n * sxy - sx * sy) / denom;
    return [a, (sy - a * sx) / n];
}

/** Segments [from, to, scale, offset] for the mode; one open-ended segment for linear. */
function lrcSegments(anchors, mode) {
    const pairs = lrcPairs(anchors);
    const inf = Infinity;
    if (!pairs.length) return [[-inf, inf, 1, 0]];
    if (mode === "steps") {
        return pairs.map(([x, y], i) => [i ? x : -inf, i + 1 < pairs.length ? pairs[i + 1][0] : inf, 1, y - x]);
    }
    if (mode === "piecewise" && pairs.length >= 2) {
        const out = [];
        for (let i = 0; i < pairs.length - 1; i++) {
            const [x1, y1] = pairs[i];
            const [x2, y2] = pairs[i + 1];
            const a = (y2 - y1) / Math.max(1, x2 - x1);
            out.push([i ? x1 : -inf, i < pairs.length - 2 ? x2 : inf, a, y1 - a * x1]);
        }
        return out;
    }
    const [a, b] = lrcLinear(pairs);
    return [[-inf, inf, a, b]];
}

function lrcFit(ms, segments) {
    for (const [from, to, a, b] of segments) {
        if (ms >= from && ms < to) return Math.max(0, Math.round(a * ms + b));
    }
    const last = segments[segments.length - 1];
    return Math.max(0, Math.round(last[2] * ms + last[3]));
}

/** "-1.5", "1.5s", "-300ms" -> milliseconds (a bare number is seconds); null when unreadable. */
function lrcParseShift(text) {
    const m = String(text || "").trim().toLowerCase().replace(",", ".").match(/^([+-]?\d*\.?\d+)\s*(ms|s)?$/);
    if (!m) return null;
    const value = parseFloat(m[1]);
    return Math.round(m[2] === "ms" ? value : value * 1000);
}

/* ---------- editing with undo ---------------------------------------------- */

function _pushUndo(lines) {
    _undo.push(lines.map((l) => ({ ...l })));
    if (_undo.length > 100) _undo.shift();
}

function _syncBase() { _base = _lrcLines.map((l) => l.ts); }

/** Show the pending anchor fit (or the plain lines when there are no anchors). */
function _preview() {
    if (!_anchors.length) {
        _lrcLines = _lrcLines.map((l, i) => ({ ...l, ts: _base[i] }));
    } else {
        const segs = lrcSegments(_anchors, _fitMode());
        _lrcLines = _lrcLines.map((l, i) => ({ ...l, ts: _base[i] === null ? null : lrcFit(_base[i], segs) }));
    }
    _dirty = true;
    _updateDirty();
    _renderLines();
    _renderAnchors();
}

function _fitMode() {
    const el = document.getElementById("lyrics-fit-mode");
    return (el && el.value) || "linear";
}

/** Bake the previewed fit into the lines so a direct edit starts from what is shown. */
function _commitFit() {
    if (!_anchors.length) return;
    _pushUndo(_lrcLines.map((l, i) => ({ ...l, ts: _base[i] })));
    _anchors = [];
    _syncBase();
    _renderAnchors();
}

/** Every direct change goes through here: commit a pending fit, remember the state, change. */
function _edit(fn) {
    _commitFit();
    _pushUndo(_lrcLines);
    fn();
    _syncBase();
    _dirty = true;
    _updateDirty();
    _updateTools();
}

function undoLyrics() {
    if (_anchors.length) {           // cancel the pending fit first
        _anchors = [];
        _preview();
        _updateTools();
        return;
    }
    const prev = _undo.pop();
    if (!prev) return;
    _lrcLines = prev;
    _syncBase();
    _dirty = true;
    _updateDirty();
    _renderLines();
    _updateTools();
}

function shiftAllLyrics(deltaMs) {
    if (!Number.isFinite(deltaMs) || deltaMs === 0) return;
    _edit(() => {
        _lrcLines = _lrcLines.map((l) => (l.ts === null ? l : { ...l, ts: Math.max(0, l.ts + deltaMs) }));
    });
    _followPauseUntil = Date.now() + 2000;
    _renderLines();
}

function markLyricsAnchor() {
    const line = _lrcLines[_selectedIdx];
    if (!line || _base[_selectedIdx] === null) return;
    const entry = { index: _selectedIdx, sub_ms: _base[_selectedIdx], video_ms: _playerMs() };
    _anchors = _anchors.filter((a) => a.index !== _selectedIdx).concat(entry);
    _followPauseUntil = Date.now() + 2000;
    _preview();
    _updateTools();
}

function _renderAnchors() {
    const host = document.getElementById("lyrics-anchors");
    if (!host) return;
    host.innerHTML = _anchors
        .slice()
        .sort((a, b) => a.sub_ms - b.sub_ms)
        .map((a) => {
            const text = (_lrcLines[a.index] && _lrcLines[a.index].text) || "";
            const delta = a.video_ms - a.sub_ms;
            const sign = delta >= 0 ? "+" : "\u2212";
            return `<span class="lrc-anchor" title="${escapeHtml(text)}">${escapeHtml(_msToTimestamp(a.sub_ms))} \u2192 ${escapeHtml(_msToTimestamp(a.video_ms))} (${sign}${(Math.abs(delta) / 1000).toFixed(2)} s) <button type="button" data-lrc="anchor-remove" data-index="${a.index}" aria-label="Remove anchor">\u00d7</button></span>`;
        })
        .join("");
}

function _updateTools() {
    const set = (id, on) => { const el = document.getElementById(id); if (el) el.disabled = !on; };
    set("lyrics-fit-apply", _anchors.length > 0);
    set("lyrics-fit-clear", _anchors.length > 0);
    set("lyrics-undo", _anchors.length > 0 || _undo.length > 0);
    set("lyrics-restore", _hasBackup);
    const statusEl = document.getElementById("lyrics-editor-status");
    if (statusEl && !statusEl.dataset.busy) {
        statusEl.textContent = _synced ? `\u2713 Synced ${_synced}` : "";
    }
}

function findLyricsLine() {
    const input = document.getElementById("lyrics-find");
    const needle = ((input && input.value) || "").trim().toLowerCase();
    const host = document.getElementById("lyrics-lines");
    if (host) host.querySelectorAll(".lrc-match").forEach((r) => r.classList.remove("lrc-match"));
    if (!needle || !_lrcLines.length) return;
    for (let step = 1; step <= _lrcLines.length; step++) {
        const i = (_selectedIdx + step) % _lrcLines.length;
        if ((_lrcLines[i].text || "").toLowerCase().includes(needle)) {
            _setSelected(i);
            _followPauseUntil = Date.now() + 4000;
            const row = host && host.querySelector(`.lrc-row[data-idx="${i}"]`);
            if (row) row.classList.add("lrc-match");
            return;
        }
    }
}

function editLyricsText(idx) {
    const host = document.getElementById("lyrics-lines");
    const row = host && host.querySelector(`.lrc-row[data-idx="${idx}"]`);
    const line = _lrcLines[idx];
    if (!row || !line) return;
    const span = row.querySelector(".lrc-text");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "lrc-text-input";
    input.value = line.text || "";
    span.replaceWith(input);
    input.focus();
    input.select();
    let done = false;
    const finish = (save) => {
        if (done) return;
        done = true;
        const value = input.value;
        if (save && value !== line.text) {
            _edit(() => { _lrcLines[idx] = { ..._lrcLines[idx], text: value }; });
        }
        _renderLines();
        if (host) host.focus();
    };
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); finish(true); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
}

/* ---------- render -------------------------------------------------------- */

function _renderLines() {
    const host = document.getElementById("lyrics-lines");
    if (!host) return;
    host.innerHTML = _lrcLines
        .map((line, i) => {
            const ts = line.ts !== null ? _msToTimestamp(line.ts) : "<no time>";
            const tsClass = line.ts !== null ? "lrc-ts" : "lrc-ts lrc-ts-empty";
            const sel = (i === _selectedIdx ? " lrc-selected" : "") + (_anchors.some((a) => a.index === i) ? " lrc-anchored" : "");
            return `<div class="lrc-row${sel}" data-idx="${i}" role="option" aria-selected="${i === _selectedIdx}" tabindex="-1">
                <span class="${tsClass}">${escapeHtml(ts)}</span>
                <span class="lrc-text">${escapeHtml(line.text || "")}</span>
            </div>`;
        })
        .join("");
}

function _scrollToSelected() {
    const host = document.getElementById("lyrics-lines");
    if (!host) return;
    const row = host.querySelector(".lrc-row.lrc-selected");
    if (row) row.scrollIntoView({ block: "nearest" });
}

function _setSelected(idx) {
    _selectedIdx = Math.max(0, Math.min(_lrcLines.length - 1, idx));
    // update DOM without full re-render
    const host = document.getElementById("lyrics-lines");
    if (!host) return;
    host.querySelectorAll(".lrc-row").forEach((row, i) => {
        const sel = i === _selectedIdx;
        row.classList.toggle("lrc-selected", sel);
        row.setAttribute("aria-selected", sel ? "true" : "false");
    });
    _scrollToSelected();
}

function _paintTs(idx) {
    const host = document.getElementById("lyrics-lines");
    const row = host && host.querySelector(`.lrc-row[data-idx="${idx}"]`);
    const tsSpan = row && row.querySelector(".lrc-ts");
    if (tsSpan) {
        tsSpan.className = "lrc-ts";
        tsSpan.textContent = _msToTimestamp(_lrcLines[idx].ts);
    }
}

function _stampLine(idx, ms) {
    if (idx < 0 || idx >= _lrcLines.length) return;
    _edit(() => { _lrcLines[idx] = { ..._lrcLines[idx], ts: Math.round(ms) }; });
    _paintTs(idx);
}

function _nudgeLine(idx, deltaMs) {
    if (idx < 0 || idx >= _lrcLines.length) return;
    if (_lrcLines[idx].ts === null) return;
    _edit(() => { _lrcLines[idx] = { ..._lrcLines[idx], ts: Math.max(0, _lrcLines[idx].ts + deltaMs) }; });
    // Pause follow-mode so the cursor doesn't jump away while nudging
    _followPauseUntil = Date.now() + 2000;
    _paintTs(idx);
}

/* ---------- dirty-state indicator ---------------------------------------- */

function _updateDirty() {
    const btn = document.getElementById("lyrics-save-btn");
    const titleEl = document.getElementById("lyrics-editor-title");
    if (btn) btn.classList.toggle("is-dirty", !!_dirty);
    if (titleEl) {
        titleEl.dataset.dirty = _dirty ? "1" : "";
    }
}

/* ---------- audio helpers ------------------------------------------------- */

function _playerMs() {
    const audio = document.getElementById("player");
    if (!audio) return 0;
    return Math.round((audio.currentTime || 0) * 1000);
}

/* ---------- playback-follow ----------------------------------------------- */

/**
 * Return the index of the last lrc line whose timestamp is <= posMs.
 * Lines with ts === null are skipped.  Returns -1 if nothing matches yet.
 */
function _lrcLineAtMs(posMs) {
    let best = -1;
    for (let i = 0; i < _lrcLines.length; i++) {
        const ts = _lrcLines[i].ts;
        if (ts !== null && ts <= posMs) best = i;
    }
    return best;
}

function _onTimeUpdate() {
    if (!_followPlayback) return;
    if (Date.now() < _followPauseUntil) return;
    const modal = document.getElementById("lyrics-editor-modal");
    if (!modal || modal.classList.contains("hidden")) return;

    const ms = _playerMs();
    const idx = _lrcLineAtMs(ms);
    if (idx >= 0 && idx !== _selectedIdx) {
        _setSelected(idx);
    }
}

/* ---------- open / close -------------------------------------------------- */

async function openLyricsEditor() {
    const track = currentTrack && currentTrack();
    if (!track || track.lyrics_type !== "lrc") return;

    _trackId = track.id;
    _dirty = false;
    _updateDirty();

    const statusEl = document.getElementById("lyrics-editor-status");
    if (statusEl) statusEl.textContent = "Loading…";

    // Ensure the player is in full-playback mode so we can stamp at any position
    if (typeof state !== "undefined" && !state.fullPlayback) {
        state.fullPlayback = true;
        // re-render the span button if needed
        const spanBtn = document.getElementById("player-span");
        if (spanBtn) spanBtn.setAttribute("aria-pressed", "true");
    }

    // Ensure the player audio is loaded for this track
    const audio = document.getElementById("player");
    if (audio && audio.dataset.track !== track.id) {
        audio.src = `/api/tracks/${track.id}/audio`;
        audio.dataset.track = track.id;
        audio.dataset.mode = "full";
        audio.load();
    }

    try {
        const data = await api(`/api/tracks/${track.id}/lyrics`);
        _lrcLines = _parseLrc(data.lyrics || "");
        _selectedIdx = 0;
        _syncBase();
        _anchors = [];
        _undo = [];
        _hasBackup = !!data.has_backup;
        _synced = data.synced || null;
    } catch (err) {
        if (statusEl) statusEl.textContent = err.message || "Could not load lyrics.";
        return;
    }

    if (statusEl) statusEl.textContent = "";
    _updateTools();
    _renderAnchors();
    _renderLines();
    _scrollToSelected();

    _followPlayback = true;
    _followPauseUntil = 0;

    const modal = document.getElementById("lyrics-editor-modal");
    if (modal) {
        modal.classList.remove("hidden");
        const host = document.getElementById("lyrics-lines");
        if (host) host.focus();
    }
}

function _closeLyricsEditor() {
    _followPlayback = false;
    const modal = document.getElementById("lyrics-editor-modal");
    if (modal) modal.classList.add("hidden");
    _lrcLines = [];
    _base = [];
    _anchors = [];
    _undo = [];
    _trackId = null;
    _dirty = false;
    _updateDirty();
}

/* ---------- save ---------------------------------------------------------- */

async function saveLyricsEditor() {
    if (!_trackId) return false;
    _commitFit();
    const content = _serializeLrc(_lrcLines, 0);
    const statusEl = document.getElementById("lyrics-editor-status");
    if (statusEl) { statusEl.dataset.busy = "1"; statusEl.textContent = "Saving\u2026"; }
    try {
        const res = await api(`/api/tracks/${_trackId}/lyrics`, { method: "PUT", body: { lyrics: content } });
        _hasBackup = !!(res && res.has_backup);
        _synced = null;               // the file changed, so an earlier Synced mark no longer holds
        _dirty = false;
        _updateDirty();
        if (statusEl) { delete statusEl.dataset.busy; statusEl.textContent = "Saved."; }
        setTimeout(() => { if (statusEl && statusEl.textContent === "Saved.") _updateTools(); }, 2000);
        _updateTools();
        return true;
    } catch (err) {
        if (statusEl) { delete statusEl.dataset.busy; statusEl.textContent = err.message || "Save failed."; }
        return false;
    }
}

/** Sync OK: save what is shown, mark the lyrics Synced and close. */
async function lyricsSyncOk() {
    if (!_trackId) return;
    const id = _trackId;
    if (!(await saveLyricsEditor())) return;
    try {
        await api(`/api/tracks/${id}/lyrics/synced`, { method: "POST", body: {} });
    } catch (err) {
        const statusEl = document.getElementById("lyrics-editor-status");
        if (statusEl) statusEl.textContent = err.message || "Could not mark as synced.";
        return;
    }
    _closeLyricsEditor();
}

async function restoreLyricsBackup() {
    if (!_trackId || !_hasBackup) return;
    if (_dirty && !confirm("Discard the unsaved changes and put back the lyrics from before the last save?")) return;
    try {
        const res = await api(`/api/tracks/${_trackId}/lyrics/revert`, { method: "POST", body: {} });
        _lrcLines = _parseLrc(res.lyrics || "");
        _selectedIdx = 0;
        _syncBase();
        _anchors = [];
        _undo = [];
        _hasBackup = false;
        _synced = null;
        _dirty = false;
        _updateDirty();
        _renderAnchors();
        _renderLines();
        _updateTools();
    } catch (err) {
        const statusEl = document.getElementById("lyrics-editor-status");
        if (statusEl) statusEl.textContent = err.message || "Could not restore.";
    }
}

/* ---------- toolbar actions ---------------------------------------------------- */

function _onLyricsToolClick(event) {
    const el = event.target.closest("[data-lrc]");
    if (!el) return;
    const act = el.dataset.lrc;
    if (act === "shift") shiftAllLyrics(parseInt(el.dataset.ms, 10));
    else if (act === "shift-typed") {
        const input = document.getElementById("lyrics-shift");
        const ms = lrcParseShift(input && input.value);
        if (ms === null) { if (input) input.focus(); return; }
        shiftAllLyrics(ms);
        if (input) input.value = "";
    }
    else if (act === "anchor") markLyricsAnchor();
    else if (act === "anchor-remove") {
        _anchors = _anchors.filter((a) => a.index !== parseInt(el.dataset.index, 10));
        _preview();
        _updateTools();
    }
    else if (act === "fit-clear") { _anchors = []; _preview(); _updateTools(); }
    else if (act === "fit-apply") { _commitFit(); _renderLines(); _updateTools(); }
    else if (act === "undo") undoLyrics();
    else if (act === "restore") restoreLyricsBackup();
    else if (act === "find") findLyricsLine();
    else if (act === "synced") lyricsSyncOk();
}

/* ---------- keyboard handler inside the modal ----------------------------- */

function _onLyricsKey(event) {
    const modal = document.getElementById("lyrics-editor-modal");
    if (!modal || modal.classList.contains("hidden")) return;

    // Don't hijack real input fields.
    // Rows inside the listbox have tabindex="-1" and are divs — those are fine.
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        const ms = _playerMs();
        _stampLine(_selectedIdx, ms);
        // Pause follow-mode briefly so the cursor doesn't snap back
        _followPauseUntil = Date.now() + 2000;
        if (event.shiftKey) {
            _setSelected(_selectedIdx - 1);
        } else {
            _setSelected(_selectedIdx + 1);
        }
        return;
    }

    if (event.key === "ArrowDown") {
        event.preventDefault();
        _setSelected(_selectedIdx + 1);
        return;
    }
    if (event.key === "ArrowUp") {
        event.preventDefault();
        _setSelected(_selectedIdx - 1);
        return;
    }
    if (event.key === "ArrowLeft") {
        event.preventDefault();
        _nudgeLine(_selectedIdx, -100);
        const _lh = document.getElementById("lyrics-lines");
        if (_lh && document.activeElement !== _lh) _lh.focus();
        return;
    }
    if (event.key === "ArrowRight") {
        event.preventDefault();
        _nudgeLine(_selectedIdx, 100);
        // Return focus to the listbox so subsequent keys keep working
        const _lh = document.getElementById("lyrics-lines");
        if (_lh && document.activeElement !== _lh) _lh.focus();
        return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undoLyrics();
        return;
    }
    if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === "m") {
        event.preventDefault();
        markLyricsAnchor();
        return;
    }
    if (event.key === "Enter" && tag !== "BUTTON") {
        event.preventDefault();
        editLyricsText(_selectedIdx);
        return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault();
        saveLyricsEditor();
    }
}

/* ---------- update button visibility ------------------------------------- */

/**
 * Call this whenever the selected track changes.
 * Shows the lyrics-edit button only if the track has an .lrc file.
 */
function updateLyricsEditButton() {
    const btn = document.getElementById("player-lyrics-edit");
    if (!btn) return;
    const track = currentTrack && currentTrack();
    const hasLrc = track && track.lyrics_type === "lrc";
    btn.classList.toggle("hidden", !hasLrc);
}

/* ---------- wire up ------------------------------------------------------- */

function initLyricsEditor() {
    // Row click to select
    const host = document.getElementById("lyrics-lines");
    if (host) {
        host.addEventListener("click", (e) => {
            const row = e.target.closest(".lrc-row");
            if (row) _setSelected(parseInt(row.dataset.idx, 10));
        });
        host.addEventListener("dblclick", (e) => {
            const row = e.target.closest(".lrc-row");
            if (!row) return;
            const idx = parseInt(row.dataset.idx, 10);
            const line = _lrcLines[idx];
            if (line && line.ts !== null) {
                const audio = document.getElementById("player");
                if (audio) {
                    audio.currentTime = line.ts / 1000;
                    audio.play().catch(() => {});
                }
            }
        });
    }

    const modal = document.getElementById("lyrics-editor-modal");
    if (modal) modal.addEventListener("click", _onLyricsToolClick);
    const mode = document.getElementById("lyrics-fit-mode");
    if (mode) mode.addEventListener("change", () => { if (_anchors.length) _preview(); });
    const find = document.getElementById("lyrics-find");
    if (find) find.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findLyricsLine(); } });
    const shift = document.getElementById("lyrics-shift");
    if (shift) shift.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); const b = document.querySelector('[data-lrc="shift-typed"]'); if (b) b.click(); }
    });

    // Save button
    const saveBtn = document.getElementById("lyrics-save-btn");
    if (saveBtn) saveBtn.addEventListener("click", saveLyricsEditor);

    // Keyboard events on the modal (capture phase so they fire before global handlers)
    document.addEventListener("keydown", _onLyricsKey, true);

    // Follow playback position — update highlighted line as audio plays
    const _audio = document.getElementById("player");
    if (_audio) _audio.addEventListener("timeupdate", _onTimeUpdate);

    // Action dispatch
    if (typeof events !== "undefined" && events) {
        // handled via global data-action="lyrics-edit" in events.js dispatcher
    }
}

document.addEventListener("DOMContentLoaded", initLyricsEditor);
