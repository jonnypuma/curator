function renderSidecar(track, album, artist) {
    const lyrics = lyricsLabel(track);
    return `<div class="sidecar-row">
        ${nfoLink("album", album)}
        <span class="${lyrics !== "—" ? "lyrics" : "bad"}">${escapeHtml(lyrics === "—" ? "No lyrics file" : lyrics)}</span>
    </div>
    <p class="muted">NFO files are written into the music folder. Lyrics use the mode chosen in Settings.</p>
    <p class="mono" style="word-break:break-all">${escapeHtml(album.path || "")}</p>
    <p class="mono" style="word-break:break-all">${escapeHtml(track.file_path || "")}</p>`;
}

function renderPreview(track) {
    const bar = document.getElementById("track-preview");
    if (!bar) return;
    if (!track) {
        bar.innerHTML = `<span>No track selected</span><span></span>`;
        return;
    }
    const spec = [formatRate(track.sample_rate), track.bit_depth ? `${track.bit_depth}-bit` : "", track.bitrate ? `${track.bitrate} kbps` : ""].filter(Boolean).join(" · ");
    bar.innerHTML = `<span>Selected: <strong>${escapeHtml(String(track.track_number || 0).padStart(2, "0"))} ${escapeHtml(track.title || "")}</strong></span><span><span class="ok">${escapeHtml((track.file_format || "").toUpperCase())}</span> ${escapeHtml(spec)}</span>`;
}

function currentTrack() {
    if (!state.album || !state.trackId || state.center !== "album") return null;
    return state.album.tracks.find((track) => track.id === state.trackId) || null;
}

function proposalFor(trackId) {
    if (!state.proposal) return null;
    return (state.proposal.tracks || []).find((track) => track.id === trackId) || null;
}

function fieldValue(track, key) {
    if (TAG_KEYS[key]) return (track.tags || {})[TAG_KEYS[key]] || "";
    const value = track[key];
    return value === null || value === undefined ? "" : value;
}

function stashProposal() {
    if (!state.proposal || !state.trackId) return;
    const proposed = proposalFor(state.trackId);
    if (!proposed) return;
    document.querySelectorAll("[data-proposed]").forEach((input) => {
        proposed[input.dataset.proposed] = input.value;
    });
    if (state.album && state.pending[state.album.album.id]) {
        setPending(state.album.album.id, state.pending[state.album.album.id]);
    }
}

async function saveTags() {
    if (state.proposal && state.album && (state.proposal.tracks || []).length) {
        await saveProposedTags();
        return;
    }
    const chosen = selectedTracks();
    if (chosen.length > 1) {
        const fields = {};
        document.querySelectorAll("[data-bulk]").forEach((input) => {
            if (input.dataset.touched === "1" && input.value.trim()) fields[input.dataset.bulk] = input.value;
        });
        await api("/api/tracks/bulk", { method: "POST", body: { track_ids: chosen.map((track) => track.id), fields } });
        chosen.forEach((track) => { delete state.tagDrafts[track.id]; });
        state.bulkDirtyAlbum = "";
        if (state.album) {
            await selectAlbum(state.album.album.id, true);
            noteAlbumChanges(state.album.album.id, state.album.tracks);
        }
        notify("Shared tags saved.", "info");
        showUndo("Album saved");
        return;
    }
    const track = currentTrack();
    if (!track) return;
    if (!libraryWritable(state.album.album.path)) {
        notify("This music folder is mounted read-only.", "error");
        return;
    }
    const body = { extra: {} };
    document.querySelectorAll("[data-field]").forEach((input) => { body[input.dataset.field] = input.value; });
    document.querySelectorAll("[data-extra]").forEach((input) => { body.extra[input.dataset.extra] = input.value; });
    const data = await api(`/api/tracks/${track.id}`, { method: "PUT", body });
    if (data.warnings && data.warnings.length) notify(data.warnings.join(" "), "warning");
    else notify("Tags saved.", "info");
    showUndo("Album saved");
    delete state.tagDrafts[data.track.id];
    state.trackId = data.track.id;
    await selectAlbum(state.album.album.id, true);
    clearMatchIfTagsMatch();
    noteAlbumChanges(state.album.album.id, state.album.tracks);
}

function proposedTagBody(local, proposed) {
    const body = { extra: {} };
    let changed = false;
    for (const [key] of FIELDS) {
        const current = String(fieldValue(local, key) ?? "");
        const next = String(proposed[key] ?? "");
        if (current === next) continue;
        changed = true;
        if (DIFF_EXTRA.has(key)) body.extra[key] = next;
        else body[key] = next;
    }
    return changed ? body : null;
}

function proposalTagsMatch() {
    if (!state.proposal || !state.album) return false;
    const locals = new Map((state.album.tracks || []).map((track) => [track.id, track]));
    return (state.proposal.tracks || []).every((proposed) => {
        const local = locals.get(proposed.id);
        return local && !proposedTagBody(local, proposed);
    });
}

function clearMatchIfTagsMatch() {
    if (!state.album || !state.proposal || !proposalTagsMatch()) return;
    const albumId = state.album.album.id;
    setPending(albumId, null);
    state.proposal = null;
    renderTree();
    renderAlbum();
    renderEditor();
}

async function saveProposedTags() {
    commitOpenDiffEdit();
    stashProposal();
    const album = state.album;
    const proposal = state.proposal;
    if (!album || !proposal) return;
    if (!libraryWritable(album.album.path)) {
        notify("This music folder is mounted read-only.", "error");
        return;
    }
    const locals = new Map((album.tracks || []).map((track) => [track.id, track]));
    const edits = [];
    for (const proposed of proposal.tracks || []) {
        const local = locals.get(proposed.id);
        if (!local) continue;
        const fields = proposedTagBody(local, proposed);
        if (!fields) continue;
        edits.push({ id: proposed.id, fields });
    }
    let saved = 0;
    if (edits.length) {
        const data = await api("/api/tracks/save", { method: "POST", body: { tracks: edits } });
        edits.forEach((item) => { delete state.tagDrafts[item.id]; });
        saved = edits.length;
        if (data.warnings && data.warnings.length) notify(data.warnings.join(" "), "warning");
    }
    const albumId = album.album.id;
    await selectAlbum(albumId, true);
    clearMatchIfTagsMatch();
    noteAlbumChanges(albumId, state.album.tracks);
    notify(saved ? "Tags saved." : "Tags already match.", "info");
    if (saved) showUndo("Album saved");
}

async function findMetadata() {
    if (!state.album) {
        notify("Open an album before running AcoustID match.", "info");
        return;
    }
    const scanActions = document.getElementById("match-scan-actions");
    if (scanActions) scanActions.classList.add("hidden");
    document.getElementById("match-modal").classList.remove("is-prompt");
    document.getElementById("match-title").textContent = "MusicBrainz releases";
    document.getElementById("match-modal").classList.remove("hidden");
    const albumId = state.album.album.id;
    const reviewTask = api(`/api/albums/${albumId}/review`, { method: "POST", body: {} }).then((data) => {
        if (!state.album || state.album.album.id !== albumId) return;
        state.album = data;
        renderAlbum();
        renderEditor();
        if (data.review_found) notify("Album review saved.", "info");
    }).catch((error) => notify(error.message || "The album review could not be looked up.", "warning"));
    await searchReleases(albumId, null, false);
    await reviewTask;
}

async function searchAgain() {
    const artistInput = document.getElementById("match-query-artist");
    const titleInput = document.getElementById("match-query-title");
    const artist = artistInput ? artistInput.value.trim() : "";
    const title = titleInput ? titleInput.value.trim() : "";
    if (!artist && !title) {
        notify("Enter an artist or an album title.", "info");
        return;
    }
    const prompting = document.getElementById("match-modal").classList.contains("is-prompt");
    const albumId = prompting ? state.scanPromptAlbum : (state.album && state.album.album.id);
    if (!albumId) return;
    await searchReleases(albumId, { artist, title }, prompting);
}

async function searchReleases(albumId, query, prompting) {
    const host = document.getElementById("match-body");
    const shown = query || albumSearchQuery(albumId);
    const label = prompting ? (state.scanPromptLabel || "") : "";
    host.innerHTML = `${prompting ? scanReleaseSubject(albumId, label, shown) : localMatchSubject(shown)}<p class="muted">Looking up MusicBrainz and Deezer…</p>`;
    const body = query ? { force: true, artist: query.artist || "", title: query.title || "" } : {};
    try {
        const data = await api(`/api/albums/${albumId}/match`, { method: "POST", body });
        paintReleaseSearch(albumId, data, prompting, label);
    } catch (error) {
        const failed = prompting ? scanReleaseSubject(albumId, label, shown) : localMatchSubject(shown);
        host.innerHTML = `${failed}<p>${escapeHtml(error.message)}</p>`;
    }
}

function albumSearchQuery(albumId) {
    if (state.matchQuery && state.matchAlbumId === albumId) return state.matchQuery;
    if (state.album && state.album.album.id === albumId) {
        return {
            artist: (state.album.artist && state.album.artist.name) || "",
            title: state.album.album.title || "",
        };
    }
    return { artist: "", title: "" };
}

function paintReleaseSearch(albumId, data, prompting, label) {
    const host = document.getElementById("match-body");
    const search = data || {};
    state.candidates = search.candidates || [];
    state.localTracks = search.local_tracks || [];
    state.deezer = search.deezer;
    state.matchAlbumId = albumId;
    state.matchPath = search.path || state.matchPath || (state.album && state.album.album.id === albumId ? state.album.album.path : "") || "";
    state.matchQuery = search.query || albumSearchQuery(albumId);
    state.compareOpen.delete(albumId);
    if (state.candidates[0]) state.compareFocus[albumId] = state.candidates[0].release_id;
    rememberSearchComparison(albumId, state.localTracks, state.candidates);
    const action = prompting ? "choose-scan-release" : "pick-release";
    const subject = prompting
        ? scanReleaseSubject(albumId, label, state.matchQuery)
        : localMatchSubject(state.matchQuery);
    const note = search.deezer && search.deezer.available
        ? `<p class="muted">Deezer agrees with ${search.deezer.matches}/${search.deezer.total} local titles${search.deezer.title ? ` (${escapeHtml(search.deezer.title)})` : ""}.</p>`
        : "";
    const acoustid = search.acoustid && search.acoustid.skipped && search.acoustid.reason
        ? `<p class="muted">${escapeHtml(search.acoustid.reason)}</p>`
        : "";
    const empty = prompting
        ? `<p>No MusicBrainz releases found. Change the artist or album, or skip this album to continue the scan.</p>`
        : `<p>No MusicBrainz releases found.</p>`;
    const results = state.candidates.length
        ? state.candidates.map((item) => releaseCandidateButton(item, action)).join("")
        : empty;
    host.innerHTML = `${subject}${note}${acoustid}${results}`;
}

function matchQueryForm(query) {
    const artist = query && query.artist != null ? query.artist : "";
    const title = query && query.title != null ? query.title : "";
    return `<form class="match-query" id="match-query">
        <label>Artist <input id="match-query-artist" value="${escapeHtml(artist)}" autocomplete="off"></label>
        <label>Album <input id="match-query-title" value="${escapeHtml(title)}" autocomplete="off"></label>
        <button type="button" data-action="search-again">Search again</button>
    </form>
    <p class="muted match-query-note">Search again uses these names and skips a stored MusicBrainz id.</p>`;
}

function folderName(path) {
    const value = String(path || "").replace(/[\\/]+$/, "");
    const parts = value.split(/[\\/]/);
    return parts[parts.length - 1] || value;
}

function localMatchSubject(query) {
    const album = state.album && state.album.album;
    if (!album) return "";
    const tracks = state.album.tracks || [];
    const facts = [
        album.release_year || "",
        album.edition || "",
        countryLabel(album.country),
        `${tracks.length || album.total_tracks || 0} tracks`,
        album.catalog || "",
        album.label || "",
        releaseTypeLabel(album.type || "album"),
    ].filter(Boolean).join(" · ");
    const names = query || { artist: (state.album.artist && state.album.artist.name) || "", title: album.title || "" };
    return `<div class="compare-subject">
        <span class="compare-kicker">Comparing these results to</span>
        <span class="compare-folder">${escapeHtml(folderName(album.path))}</span>
        <span class="compare-line">${escapeHtml(album.title || "")}</span>
        <span class="compare-line muted">${escapeHtml(facts)}</span>
        <button type="button" class="compare-hint" data-action="show-files" data-files-album="${escapeHtml(album.id)}">Show files on disk</button>
    </div>
    ${matchQueryForm(names)}
    <div class="compare-files hidden" data-compare-panel="${escapeHtml(album.id)}"></div>`;
}

function matchPercent(item) {
    const value = Number(item && item.match_percent);
    if (!Number.isFinite(value)) return null;
    return Math.max(0, Math.min(100, Math.round(value)));
}

function matchBadge(percent) {
    if (percent == null) return { icon: "", klass: "" };
    if (percent >= 100) return { icon: "📀", klass: " is-gold" };
    return { icon: "💿", klass: " is-silver" };
}

function candidateScore(item) {
    const percent = matchPercent(item);
    if (percent == null) return "";
    const badge = matchBadge(percent);
    const gold = percent >= 100;
    const title = gold ? "100% match. Click to compare files." : `${percent}% match. Click to compare files.`;
    const icon = badge.icon ? `<span class="match-icon" aria-hidden="true">${badge.icon}</span>` : "";
    return `<span class="candidate-score${badge.klass}" title="${title}">${icon}<strong>${percent}%</strong></span>`;
}

function rememberSearchComparison(albumId, localTracks, candidates) {
    (candidates || []).forEach((item) => {
        if (!(item.tracks || []).length) return;
        state.compareCache[`${albumId}:${item.release_id}`] = {
            local_tracks: localTracks || [],
            tracks: item.tracks,
            match_percent: item.match_percent,
            title: item.title || "",
        };
    });
}

function focusCandidate(releaseId) {
    const album = state.album && state.album.album;
    if (!album || !releaseId) return;
    state.compareFocus[album.id] = releaseId;
    return runAction(() => showReleaseFiles(album.id), "Comparing tracks…");
}

async function loadLookupComparison(albumId) {
    if (!albumId) return;
    state.compareOpen.add(albumId);
    const row = document.querySelector(`#lookup-list [data-lookup-album="${CSS.escape(albumId)}"]`);
    const select = row && row.querySelector("[data-lookup-choice]");
    if (!state.compareFocus[albumId] && select) state.compareFocus[albumId] = select.value || "";
    const panel = row && row.querySelector("[data-compare-panel]");
    if (panel) panel.classList.remove("hidden");
    try {
        await ensureCompare(albumId);
    } catch (error) {
        if (panel) panel.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function comparePanel(albumId) {
    const lookup = document.getElementById("lookup-modal");
    const lookupOpen = lookup && !lookup.classList.contains("hidden");
    if (lookupOpen) {
        const panel = document.querySelector(`#lookup-list [data-compare-panel="${CSS.escape(albumId)}"]`);
        if (panel) return panel;
    }
    return document.querySelector(`[data-compare-panel="${CSS.escape(albumId)}"]`);
}

async function showReleaseFiles(albumId) {
    if (!albumId) return;
    const lookup = document.getElementById("lookup-modal");
    const lookupOpen = lookup && !lookup.classList.contains("hidden");
    if (lookupOpen && document.querySelector(`#lookup-list [data-lookup-album="${CSS.escape(albumId)}"]`)) {
        return loadLookupComparison(albumId);
    }
    if (!state.compareFocus[albumId]) {
        const select = document.querySelector(`[data-lookup-choice="${CSS.escape(albumId)}"]`);
        const first = state.matchAlbumId === albumId && state.candidates[0] ? state.candidates[0].release_id : "";
        state.compareFocus[albumId] = (select && select.value) || first || "";
    }
    state.filesAlbumId = albumId;
    const modal = document.getElementById("files-modal");
    const host = document.getElementById("files-body");
    modal.classList.remove("hidden");
    host.innerHTML = `<p class="muted">Loading files…</p>`;
    if (state.compareFocus[albumId]) await ensureCompare(albumId, { paint: false });
    await paintFilesModal(albumId);
}

async function paintFilesModal(albumId) {
    const host = document.getElementById("files-body");
    if (!host || state.filesAlbumId !== albumId) return;
    let tracks = state.matchAlbumId === albumId ? [...(state.localTracks || [])] : [];
    let folder = state.matchAlbumId === albumId ? (state.matchPath || "") : "";
    if (!tracks.length || !folder) {
        const data = await api(`/api/albums/${albumId}`);
        if (!tracks.length) {
            tracks = (data.tracks || []).map((track) => ({
                disc_number: track.disc_number,
                track_number: track.track_number,
                title: track.title,
                duration_seconds: track.duration_seconds,
                file_name: folderName(track.file_path),
            }));
        }
        if (!folder && data.album) folder = data.album.path || "";
    }
    const releaseId = state.compareFocus[albumId];
    const cached = releaseId ? state.compareCache[`${albumId}:${releaseId}`] : null;
    const choices = state.matchAlbumId === albumId ? state.candidates : [];
    const options = choices.map((item) => {
        const percent = matchPercent(item);
        const badge = matchBadge(percent);
        const selected = item.release_id === releaseId ? " selected" : "";
        const mark = percent != null ? `${badge.icon ? `${badge.icon} ` : ""}${percent}% · ` : "";
        return `<option value="${escapeHtml(item.release_id)}"${selected}>${escapeHtml(`${mark}${item.title || "Release"}`)}</option>`;
    }).join("");
    const picker = options
        ? `<label class="compare-picker">Release <select data-compare-release="1" data-album="${escapeHtml(albumId)}">${options}</select></label>`
        : "";
    const percent = matchPercent(cached);
    const badge = matchBadge(percent);
    const banner = !cached || percent == null
        ? ""
        : `<p class="compare-note">${badge.icon ? `${badge.icon} ` : ""}${percent}% match${cached.title ? ` · ${escapeHtml(cached.title)}` : ""}</p>`;
    const comparison = cached
        ? `${banner}${compareTable(tracks.length ? tracks : (cached.local_tracks || []), cached.tracks || [])}`
        : "";
    host.innerHTML = `<p class="file-path mono">${escapeHtml(folder || "Folder path is not stored")}</p>
        <p class="muted">These files are in the music folder mounted into the app.</p>
        ${fileListHtml(tracks)}
        ${picker}
        ${comparison}`;
}

function fileListHtml(tracks) {
    const local = [...(tracks || [])].sort(compareTrackOrder);
    if (!local.length) return `<p>No audio files are stored for this album.</p>`;
    const rows = local.map((track) => {
        const number = `${track.disc_number || 1}-${String(track.track_number || 0).padStart(2, "0")}`;
        return `<div class="file-row"><strong>${escapeHtml(number)}</strong><span>${escapeHtml(track.title || "Untitled")}</span><span class="muted tabular">${escapeHtml(formatDuration(track.duration_seconds))}</span><small>${escapeHtml(track.file_name || "")}</small></div>`;
    }).join("");
    return `<div class="file-list">${rows}</div>`;
}

async function toggleCompare(albumId) {
    if (!albumId) return;
    const panel = comparePanel(albumId);
    const toggle = document.querySelector(`[data-action="toggle-compare"][data-album="${CSS.escape(albumId)}"]`);
    if (!panel) return;
    if (state.compareOpen.has(albumId)) {
        state.compareOpen.delete(albumId);
        panel.classList.add("hidden");
        panel.innerHTML = "";
        if (toggle) toggle.classList.remove("is-open");
        return;
    }
    state.compareOpen.add(albumId);
    panel.classList.remove("hidden");
    if (toggle) toggle.classList.add("is-open");
    if (!state.compareFocus[albumId]) {
        const select = document.querySelector(`[data-lookup-choice="${CSS.escape(albumId)}"]`);
        const first = state.album && state.album.album.id === albumId && state.candidates[0] ? state.candidates[0].release_id : "";
        state.compareFocus[albumId] = (select && select.value) || first;
    }
    await ensureCompare(albumId);
}

async function ensureCompare(albumId, options) {
    const releaseId = state.compareFocus[albumId];
    const paint = !options || options.paint !== false;
    if (!albumId || !releaseId) {
        if (paint) paintCompare(albumId, "Choose a release to compare.");
        return;
    }
    const key = `${albumId}:${releaseId}`;
    if (!state.compareCache[key]) {
        if (paint) paintCompare(albumId, "Loading the release tracks…");
        const data = await api(`/api/albums/${albumId}/match`, {
            method: "POST",
            body: { release_id: releaseId, compare: true },
        });
        state.compareCache[key] = data;
        if (state.album && state.album.album.id === albumId && data.local_tracks) state.localTracks = data.local_tracks;
    }
    if (paint) paintCompare(albumId);
}

function paintCompare(albumId, message) {
    const panel = comparePanel(albumId);
    if (!panel || !state.compareOpen.has(albumId)) return;
    markComparedCandidate(albumId);
    if (message) {
        panel.innerHTML = `<p class="muted compare-note">${escapeHtml(message)}</p>`;
        return;
    }
    const releaseId = state.compareFocus[albumId];
    const cached = state.compareCache[`${albumId}:${releaseId}`];
    if (!cached) {
        panel.innerHTML = `<p class="muted compare-note">Loading the release tracks…</p>`;
        return;
    }
    const single = state.album && state.album.album.id === albumId;
    const options = single
        ? state.candidates.map((item) => {
            const percent = matchPercent(item);
            const badge = matchBadge(percent);
            const selected = item.release_id === releaseId ? " selected" : "";
            const mark = percent != null ? `${badge.icon ? `${badge.icon} ` : ""}${percent}% · ` : "";
            return `<option value="${escapeHtml(item.release_id)}"${selected}>${escapeHtml(`${mark}${item.title || "Release"}`)}</option>`;
        }).join("")
        : "";
    const picker = options
        ? `<label class="compare-picker">Release <select data-compare-release="1" data-album="${escapeHtml(albumId)}">${options}</select></label>`
        : "";
    const percent = matchPercent(cached);
    const badge = matchBadge(percent);
    const banner = percent == null
        ? ""
        : `<p class="compare-note">${badge.icon ? `${badge.icon} ` : ""}${percent}% match${cached.title ? ` · ${escapeHtml(cached.title)}` : ""}</p>`;
    const path = panel.dataset.folderPath
        ? `<p class="file-path mono">${escapeHtml(panel.dataset.folderPath)}</p>`
        : "";
    panel.innerHTML = `${path}${picker}${banner}${compareTable(cached.local_tracks || [], cached.tracks || [])}`;
}

function markComparedCandidate(albumId) {
    const releaseId = state.compareFocus[albumId];
    document.querySelectorAll("#match-body .candidate").forEach((button) => {
        button.classList.toggle("is-compared", button.dataset.release === releaseId);
    });
}

function compareTable(localTracks, remoteTracks) {
    const local = [...localTracks].sort(compareTrackOrder);
    const remote = [...remoteTracks].sort(compareTrackOrder);
    if (!local.length && !remote.length) return `<p class="muted compare-note">No tracks to compare.</p>`;
    const count = Math.max(local.length, remote.length);
    const rows = [];
    for (let index = 0; index < count; index += 1) {
        const left = local[index] || null;
        const right = remote[index] || null;
        rows.push(`<div class="compare-file-row${tracksDiffer(left, right) ? " is-diff" : ""}"><div>${compareTrackCell(left, true)}</div><div>${compareTrackCell(right, false)}</div></div>`);
    }
    return `<div class="compare-files-head"><span>Files on disk</span><span>Selected release</span></div>${rows.join("")}`;
}

function compareTrackOrder(left, right) {
    return (Number(left.disc_number) || 0) - (Number(right.disc_number) || 0)
        || (Number(left.track_number) || 0) - (Number(right.track_number) || 0)
        || String(left.title || "").localeCompare(String(right.title || ""));
}

function tracksDiffer(left, right) {
    if (!left || !right) return true;
    const localTitle = String(left.title || "").trim().toLowerCase().replace(/\s+/g, " ");
    const remoteTitle = String(right.title || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (localTitle !== remoteTitle) return true;
    const localDuration = Number(left.duration_seconds) || 0;
    const remoteDuration = Number(right.duration_seconds) || 0;
    if (localDuration && remoteDuration && Math.abs(localDuration - remoteDuration) > 2) return true;
    return false;
}

function compareTrackCell(track, local) {
    if (!track) return `<span class="compare-file-missing">${local ? "No local file" : "No release track"}</span>`;
    const number = `${String(track.disc_number || 1)}-${String(track.track_number || 0).padStart(2, "0")}`;
    const file = local && track.file_name ? `<small>${escapeHtml(track.file_name)}</small>` : "";
    return `<strong>${escapeHtml(number)}</strong> ${escapeHtml(track.title || "")} <span class="muted tabular">${escapeHtml(formatDuration(track.duration_seconds))}</span>${file}`;
}

async function pickRelease(releaseId) {
    const buttons = [...document.querySelectorAll("#match-body .candidate")];
    buttons.forEach((button) => {
        const picked = button.dataset.release === releaseId;
        button.classList.toggle("is-picked", picked);
        button.disabled = true;
        if (picked) {
            const status = button.querySelector(".candidate-status");
            if (status) status.textContent = "Loading this release…";
        }
    });
    let data;
    try {
        data = await api(`/api/albums/${state.album.album.id}/match`, { method: "POST", body: { release_id: releaseId } });
    } catch (error) {
        buttons.forEach((button) => {
            button.disabled = false;
            button.classList.remove("is-picked");
            const status = button.querySelector(".candidate-status");
            if (status) status.textContent = "";
        });
        throw error;
    }
    state.proposal = data.proposal;
    setPending(state.album.album.id, data.proposal);
    document.getElementById("match-modal").classList.add("hidden");
    renderTree();
    renderAlbum();
    renderEditor();
    notify("Review the proposed tags, then apply the match.", "info");
}

async function sendAlbumLibraryUpdate() {
    if (!state.album || !state.album.album) return;
    const data = await api(`/api/albums/${state.album.album.id}/library-update`, { method: "POST", body: {} });
    notify(data.message || "Library update queued.", "info");
}

async function applyMatch() {
    commitOpenDiffEdit();
    stashProposal();
    if (!state.proposal) return;
    notify("Applying the match…", "info");
    renderAlbum();
    const albumId = state.album.album.id;
    const data = await api(`/api/albums/${albumId}/apply`, { method: "POST", body: state.proposal });
    (state.proposal.tracks || []).forEach((track) => { delete state.tagDrafts[track.id]; });
    setPending(albumId, null);
    state.proposal = null;
    state.album = { album: data.album, artist: data.artist, tracks: data.tracks };
    if (data.warnings && data.warnings.length) notify(data.warnings.join(" "), "warning");
    else notify("Match applied.", "info");
    showUndo("Album saved");
    await loadLibrary();
    renderCenter();
    renderEditor();
}

function openPendingAlbums() {
    commitOpenDiffEdit();
    stashProposal();
    const ids = Object.keys(state.pending);
    if (!ids.length) {
        notify("No loaded matches are waiting.", "info");
        return;
    }
    const byId = new Map(visibleAlbums().map((row) => [row.album.id, row]));
    const rows = ids.map((id) => {
        const row = byId.get(id) || {};
        const proposal = state.pending[id] || {};
        const album = row.album || {};
        const artist = row.artist || {};
        const match = proposal.album_title || proposal.title || "";
        const tracks = (proposal.tracks || []).length;
        return `<tr data-pending-id="${escapeHtml(id)}">
            <td>${escapeHtml(artist.name || "")}</td>
            <td>${escapeHtml(album.title || id)}</td>
            <td>${escapeHtml(match)}${proposal.year ? ` (${escapeHtml(String(proposal.year))})` : ""}${tracks ? ` · ${tracks} tracks` : ""}</td>
            <td class="pending-match-actions"><button type="button" class="btn-ghost" data-action="pending-album-remove" title="Leave this album out of Apply all. Its loaded match stays.">Remove</button></td>
        </tr>`;
    }).join("");
    document.getElementById("pending-album-title").textContent = `Apply match (${ids.length})`;
    document.getElementById("pending-album-list").innerHTML = `<table class="data-table"><thead><tr><th>Artist</th><th>Album</th><th>Loaded match</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
    const confirm = document.querySelector("[data-action='apply-all-matches-confirm']");
    if (confirm) confirm.disabled = false;
    document.getElementById("pending-album-modal").classList.remove("hidden");
}

function pendingAlbumIds() {
    return [...document.querySelectorAll("#pending-album-list tr[data-pending-id]")].map((row) => row.dataset.pendingId);
}

function removePendingAlbumRow(button) {
    const row = button.closest("tr");
    if (row) row.remove();
    const left = pendingAlbumIds().length;
    document.getElementById("pending-album-title").textContent = left ? `Apply match (${left})` : "Apply match";
    const confirm = document.querySelector("[data-action='apply-all-matches-confirm']");
    if (confirm) confirm.disabled = !left;
}

async function applyAllMatches(only) {
    commitOpenDiffEdit();
    stashProposal();
    const ids = (only || Object.keys(state.pending)).filter((id) => state.pending[id]);
    if (!ids.length) return;
    let done = 0;
    const errors = [];
    for (const id of ids) {
        const proposal = state.pending[id];
        if (!proposal) continue;
        try {
            await api(`/api/albums/${id}/apply`, { method: "POST", body: proposal });
            setPending(id, null);
            if (state.album && state.album.album.id === id) state.proposal = null;
            (proposal.tracks || []).forEach((track) => { delete state.tagDrafts[track.id]; });
            done += 1;
        } catch (error) {
            errors.push(error.message);
        }
    }
    await loadLibrary();
    renderCenter();
    renderEditor();
    if (errors.length) notify(`Applied ${done}. ${errors[0]}`, "warning");
    else notify(`Applied ${done} ${done === 1 ? "match" : "matches"}.`, "info");
}
