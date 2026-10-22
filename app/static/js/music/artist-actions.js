async function fetchLyrics() {
    if (!state.album) {
        notify("Open an album before fetching lyrics.", "info");
        return;
    }
    const data = await api(`/api/albums/${state.album.album.id}/lyrics`, { method: "POST", body: {} });
    notify(`Lyrics written ${data.written}, instrumental skips ${data.skipped_instrumental}, missing ${data.missing}.`, "info");
    await selectAlbum(state.album.album.id, true);
}

function processLabel(status) {
    return status === "PROCESSED" ? "Set to unprocessed" : "Mark processed";
}

function processButtonClass(status) {
    return status === "PROCESSED" ? "btn-ghost" : "btn-process";
}

function nextProcessStatus(status) {
    return status === "PROCESSED" ? "new" : "processed";
}

function ignoreLabel(status) {
    return status === "IGNORED" ? "Stop ignoring" : "Ignore";
}

function nextIgnoreStatus(status) {
    return status === "IGNORED" ? "new" : "ignored";
}

function lockLabel(locked) {
    return locked ? "Unlock" : "Lock";
}

async function lockLibraryRows(kind, ids, locked) {
    const data = await api("/api/library/lock", { method: "POST", body: { kind, ids, locked: !!locked } });
    const updated = new Set(data.updated || []);
    if (kind === "artist") {
        for (const row of state.artists || []) if (updated.has(row.id)) row.locked = !!locked;
        if (state.artistDetail && state.artistDetail.artist && updated.has(state.artistDetail.artist.id)) state.artistDetail.artist.locked = !!locked;
        if (state.album && state.album.artist && updated.has(state.album.artist.id)) state.album.artist.locked = !!locked;
    } else {
        for (const artist of state.artists || []) {
            for (const album of artist.albums || []) if (updated.has(album.id)) album.locked = !!locked;
        }
        if (state.album && updated.has(state.album.album.id)) state.album.album.locked = !!locked;
    }
    renderTree();
    if (state.center === "artist" && typeof renderArtist === "function") renderArtist();
    if (state.center === "album" && typeof renderAlbum === "function") renderAlbum();
    const noun = kind === "artist" ? "artist" : "album";
    const count = updated.size;
    notify(`${count} ${noun}${count === 1 ? "" : "s"} ${locked ? "locked" : "unlocked"}.`, "info", { undo: () => lockLibraryRows(kind, [...updated], !locked) });
}

function currentArtistStatus() {
    if (state.center === "artist" && state.artistDetail && state.artistDetail.artist) return state.artistDetail.artist.status;
    if (state.album && state.album.artist) return state.album.artist.status;
    return "";
}

async function mark(kind, id, status) {
    if (!id) return;
    const next = status || "processed";
    await api(`/api/${kind}/${id}/mark`, { method: "POST", body: { status: next } });
    if (kind === "artists") paintArtistStatus([id], next);
    else paintAlbumStatus([id], next);
    if (next === "new") notify(kind === "artists" ? "Artist set to unprocessed." : "Album set to unprocessed.", "info");
    else if (kind === "artists") notify("Artist marked as processed. Its albums are unchanged.", "info");
    else notify("Marked as processed.", "info");
}

async function scrapeArtist() {
    const data = await api(`/api/artists/${state.artistId}/scrape`, { method: "POST", body: {} });
    applyScrapedArtist(data);
}

async function openArtistManualSearch() {
    if (!state.artistId) throw new Error("Open an artist first.");
    const name = (state.artistDetail && state.artistDetail.artist && state.artistDetail.artist.name) || "";
    const input = document.getElementById("artist-search-query");
    if (input) input.value = name;
    const body = document.getElementById("artist-search-body");
    if (body) body.innerHTML = `<p class="muted">Searching…</p>`;
    document.getElementById("artist-search-modal").classList.remove("hidden");
    await runArtistMetadataSearch();
}

async function runArtistMetadataSearch() {
    if (!state.artistId) throw new Error("Open an artist first.");
    const input = document.getElementById("artist-search-query");
    const query = input ? input.value.trim() : "";
    const body = document.getElementById("artist-search-body");
    if (body) body.innerHTML = `<p class="muted">Searching…</p>`;
    const data = await api(`/api/artists/${state.artistId}/search`, { method: "POST", body: { query } });
    if (input && data.query && input.value.trim() === query) input.value = data.query;
    const choices = data.choices || [];
    if (!body) return;
    body.innerHTML = choices.length
        ? choices.map(artistChoiceButton).join("")
        : `<p>No MusicBrainz artists found for that search.</p>`;
}

function artistChoiceButton(item, action) {
    const bits = [item.type, item.country, item.begin, item.disambiguation].filter(Boolean);
    return `<button type="button" class="candidate" data-action="${escapeHtml(action || "pick-artist-meta")}" data-mbid="${escapeHtml(item.id)}">
        <span class="candidate-copy"><strong>${escapeHtml(item.name || "Unknown")}</strong><br><small>${escapeHtml(bits.join(" · ") || item.id)}</small></span>
    </button>`;
}

function openAddArtist() {
    const input = document.getElementById("add-artist-query");
    const body = document.getElementById("add-artist-body");
    if (input) input.value = "";
    if (body) body.innerHTML = `<p class="muted">Type an artist name, then choose a MusicBrainz result.</p>`;
    document.getElementById("add-artist-modal").classList.remove("hidden");
    if (input) input.focus();
}

async function searchAddArtist() {
    const input = document.getElementById("add-artist-query");
    const query = input ? input.value.trim() : "";
    const body = document.getElementById("add-artist-body");
    if (!query) throw new Error("Type an artist name.");
    if (body) body.innerHTML = `<p class="muted">Searching…</p>`;
    const data = await api("/api/library/artist-search", { method: "POST", body: { query } });
    if (input && data.query && input.value.trim() === query) input.value = data.query;
    const choices = data.choices || [];
    if (!body) return;
    body.innerHTML = choices.length
        ? choices.map((item) => artistChoiceButton(item, "pick-add-artist")).join("")
        : `<p>No MusicBrainz artists found for that search.</p>`;
}

async function addChosenArtist(mbid) {
    if (!mbid) throw new Error("That result has no MusicBrainz id.");
    const data = await api("/api/library/artists", { method: "POST", body: { mbid } });
    document.getElementById("add-artist-modal").classList.add("hidden");
    await loadLibrary();
    if (data.artist_id) await selectArtist(data.artist_id);
    const warnings = (data.warnings || []).filter(Boolean);
    const extra = warnings.length ? ` ${warnings.join(" ")}` : "";
    notify(`${data.message || "Artist added."}${extra}`, warnings.length ? "warning" : "info");
}

async function pickArtistMetadata(mbid) {
    if (!mbid) throw new Error("That result has no MusicBrainz id.");
    const data = await api(`/api/artists/${state.artistId}/scrape`, { method: "POST", body: { mbid } });
    document.getElementById("artist-search-modal").classList.add("hidden");
    applyScrapedArtist(data, ["musicbrainz_artist_id"]);
}

function applyScrapedArtist(data, replaceKeys) {
    if (data.biography) {
        state.bioEditing = true;
        state.bioDraft = data.biography;
        if (state.artistId) state.bioDrafts[state.artistId] = state.bioDraft;
        noteArtistChanges(state.artistId, state.bioDraft !== storedBiography());
    }
    renderCenter();
    const filled = applyArtistFields(data.fields || {}, replaceKeys);
    const sources = (data.sources || []).filter(Boolean).join(", ");
    const who = data.artist_name ? ` for ${data.artist_name}` : "";
    const from = data.biography_source
        ? ` The biography is from ${data.biography_source}.`
        : (sources ? ` Sources: ${sources}.` : "");
    if (data.biography && filled) notify(`Loaded a biography and ${filled} empty field${filled === 1 ? "" : "s"}${who}.${from} Save artist.nfo to keep them.`, "info");
    else if (data.biography) notify(`Biography loaded${who}.${from} Save it if you want to keep it.`, "info");
    else if (filled) notify(`Filled ${filled} empty field${filled === 1 ? "" : "s"}${who}.${from} Save artist.nfo to keep them.`, "info");
    else notify(`Nothing new${who}.${from} Fields you already filled were left as they are.`, "info");
}

function applyArtistFields(fields, replaceKeys) {
    const host = document.getElementById("editor-artist-nfo");
    if (!host || !fields || !host.querySelector("[data-nfo]")) return 0;
    const replace = new Set(replaceKeys || []);
    let filled = 0;
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        if (input.type === "checkbox") return;
        const value = fields[input.dataset.nfo];
        if (value == null || String(value).trim() === "") return;
        const next = String(value);
        const current = String(input.value || "").trim();
        if (current && !replace.has(input.dataset.nfo)) return;
        if (current === next) return;
        input.value = next;
        filled += 1;
    });
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        if (input.dataset.nfo !== "type" || input.type === "checkbox") return;
        const value = fields.type;
        if (value == null || String(value).trim() === "") return;
        const next = String(value);
        if (String(input.value || "").trim() === next) return;
        input.value = next;
        filled += 1;
    });
    const incoming = Array.isArray(fields.genres) ? fields.genres : [];
    const editor = host.querySelector(".genre-editor");
    if (!editor || !incoming.length) return filled;
    const current = [...editor.querySelectorAll("[data-genre]")].map((node) => node.dataset.genre || "");
    const names = incoming.map((name) => String(name || "").trim()).filter((name) => name && !/^\d+$/.test(name));
    const same = current.length === names.length && current.every((name, index) => name.toLowerCase() === names[index].toLowerCase());
    if (same) return filled;
    editor.innerHTML = "";
    incoming.forEach((name) => {
        const label = String(name || "").trim();
        if (!label || /^\d+$/.test(label)) return;
        const chip = document.createElement("span");
        chip.className = "genre-chip";
        chip.innerHTML = `<span data-genre="${escapeHtml(label)}">${escapeHtml(label)}</span><button type="button" class="genre-remove" data-action="remove-genre" aria-label="Remove ${escapeHtml(label)}">×</button>`;
        editor.appendChild(chip);
        filled += 1;
    });
    return filled;
}

async function downloadArtistArt() {
    if (!state.artistId) throw new Error("Open an artist before downloading artwork.");
    const data = await api(`/api/artists/${state.artistId}/artwork/deploy-missing`, { method: "POST", body: {} });
    if (!data.started) throw new Error("An artist artwork download is already running.");
    state.missingArtistArtSeen = "running";
    state.working = true;
    schedulePoll(300);
    notify("Downloading missing artist artwork.", "info");
}

async function writeArtistNfo() {
    await api(`/api/artists/${state.artistId}/nfo`, { method: "POST", body: {} });
    notify("Artist NFO written.", "info");
    if (state.artistId) await selectArtist(state.artistId);
}
