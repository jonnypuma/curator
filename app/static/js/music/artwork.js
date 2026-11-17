async function openArtwork(subject, focus) {
    if (!state.artworkQueueOpening) {
        state.artworkQueue = null;
        state.artworkQueueTotal = 0;
    }
    const artistMode = subject === "artist";
    const albumId = state.album ? state.album.album.id : null;
    const artistId = state.artistId || (state.artistDetail && state.artistDetail.artist && state.artistDetail.artist.id) || (state.album && state.album.artist && state.album.artist.id);
    if (artistMode && !artistId) {
        notify("Open an artist before searching artist artwork.", "warning");
        return;
    }
    if (!artistMode && !albumId) {
        notify("Open an album before searching album artwork.", "warning");
        return;
    }
    state.artworkPick = null;
    state.artworkTarget = { subject: artistMode ? "artist" : "album", albumId: albumId || "", artistId: artistId || "" };
    const searchText = artistMode
        ? artworkArtistName()
        : artworkSearchText(state.album.album, state.album.artist && state.album.artist.name);
    const heading = artistMode
        ? "Artist artwork"
        : albumArtworkTitle(state.album.album, state.album.artist && state.album.artist.name);
    document.getElementById("artwork-title").textContent = artworkQueueHeading(heading);
    setArtworkSearch(true, searchText, artistMode ? "artist" : "album");
    const scanActions = document.getElementById("artwork-scan-actions");
    if (scanActions && !document.getElementById("artwork-modal").classList.contains("is-prompt")) scanActions.classList.add("hidden");
    document.getElementById("artwork-body").innerHTML = `<p class="muted">Looking up artwork…</p>`;
    showUndoArtwork(null);
    document.getElementById("art-zoom").classList.add("hidden");
    const currentUrl = currentArtUrl(artistMode ? "artistthumb" : "front", artistMode);
    revealCompare(
        document.getElementById("art-compare"),
        document.getElementById("compare-current"),
        document.getElementById("compare-candidate"),
        document.getElementById("compare-label"),
        currentUrl,
        currentUrl,
        "Compare"
    );
    if (typeof fitModalChrome === "function") fitModalChrome();
    document.getElementById("artwork-modal").classList.remove("hidden");
    state.activityLabel = "Loading artwork…";
    syncActivity();
    schedulePoll(400);
    const request = ++artworkLookupSerial;
    try {
        const data = artistMode
            ? await api(`/api/artists/${artistId}/artwork?harvest=1&q=${encodeURIComponent(searchText)}`)
            : await api(`/api/albums/${albumId}/artwork?harvest=1&scope=album&q=${encodeURIComponent(searchText)}`);
        if (request !== artworkLookupSerial) return;
        syncArtworkQuery(data, searchText);
        paintArtworkResults(data, artistMode);
        if (focus) {
            const node = document.getElementById(`asset-${focus}`);
            if (node) node.scrollIntoView({ block: "start" });
        }
    } catch (error) {
        if (request !== artworkLookupSerial) return;
        document.getElementById("artwork-body").innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    } finally {
        if (request === artworkLookupSerial) {
            state.activityLabel = "";
            syncActivity();
        }
    }
}

function downloadArtButton(id) {
    const icon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg>`;
    return `<button type="button" class="art-download-btn" data-action="select-art" data-art="${escapeHtml(id)}" title="Download and set this artwork" aria-label="Download and set this artwork">${icon}</button>`;
}

function zoomButton(action, extra) {
    const icon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/></svg>`;
    return `<button type="button" class="art-zoom-btn" data-action="${action}" ${extra || ""} title="Enlarge artwork" aria-label="Enlarge artwork">${icon}</button>`;
}

function uploadIcon() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V5"/><path d="m7 10 5-5 5 5"/><path d="M5 20h14"/></svg>`;
}

function trashIcon() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M8 7l1 13h6l1-13"/><path d="M10 11v6M14 11v6"/></svg>`;
}

function chooseArtworkFile(asset, subject) {
    const input = document.getElementById("artwork-file");
    if (!input || !asset) return;
    state.artUpload = { asset, subject: subject === "artist" ? "artist" : "album" };
    input.accept = asset === "booklet"
        ? "image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif,.pdf,application/pdf"
        : "image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif";
    input.value = "";
    input.click();
}

function uploadArtwork(file, target) {
    return keepTreeScroll(() => uploadArtworkNow(file, target));
}

async function uploadArtworkNow(file, target) {
    if (file.size > 25 * 1024 * 1024) throw new Error("Artwork files must be 25 MB or smaller");
    const artistMode = target.subject === "artist";
    const albumId = (state.artworkTarget && state.artworkTarget.albumId) || (state.album && state.album.album.id) || state.scanPromptAlbum;
    const artistId = (state.artworkTarget && state.artworkTarget.artistId) || state.artistId || (state.artistDetail && state.artistDetail.artist && state.artistDetail.artist.id) || (state.album && state.album.artist && state.album.artist.id);
    if (artistMode && !artistId) throw new Error("Open an artist before uploading artist artwork.");
    if (!artistMode && !albumId) throw new Error("Open an album before uploading album artwork.");
    const form = new FormData();
    form.append("file", file);
    form.append("asset_type", target.asset);
    const path = artistMode ? `/api/artists/${artistId}/artwork/upload` : `/api/albums/${albumId}/artwork/upload`;
    const response = await fetch(path, { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || response.statusText);
    notify("Artwork uploaded.", "info");
    await refreshArtworkModal();
    if (state.center === "artist" && state.artistId) await selectArtist(state.artistId);
    else if (state.album) await selectAlbum(state.album.album.id, true);
}

async function refreshArtworkModal(selected) {
    const modal = document.getElementById("artwork-modal");
    if (!modal || modal.classList.contains("hidden")) return;
    const target = state.artworkTarget || {};
    const artistMode = target.subject === "artist";
    const data = artistMode
        ? await api(`/api/artists/${target.artistId}/artwork`)
        : await api(`/api/albums/${target.albumId}/artwork`);
    paintArtworkResults(data, artistMode, selected);
}

function stripReleaseType(title) {
    return String(title || "").replace(/\s*\((album|single|ep|compilation|live)\)\s*$/i, "").trim();
}

function queryWithoutReleaseType(query) {
    const text = String(query || "").trim();
    const match = text.match(/^(.*?)\s+[-–—]\s+(.*)$/);
    if (!match) return stripReleaseType(text);
    return [match[1].trim(), stripReleaseType(match[2].trim())].filter(Boolean).join(" - ");
}

function selectedAlbumIds() {
    const chosen = albumActionIds();
    if (state.contextAlbumIds && state.contextAlbumIds.length) return chosen;
    const ids = [];
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => {
            if (chosen.includes(album.id)) ids.push(album.id);
        });
    });
    chosen.forEach((id) => {
        if (!ids.includes(id)) ids.push(id);
    });
    if (!ids.length && state.contextAlbum) ids.push(state.contextAlbum);
    return ids;
}

function artworkQueueHeading(title) {
    const total = state.artworkQueueTotal || 0;
    if (total < 2) return title;
    const left = (state.artworkQueue || []).length;
    return `${title} · ${total - left} of ${total}`;
}

async function startArtworkQueue(ids) {
    const list = (ids || []).filter(Boolean);
    if (!list.length) {
        notify("Select an album before looking up artwork.", "warning");
        return;
    }
    state.artworkQueueSubject = "album";
    state.artworkQueue = list.slice(1);
    state.artworkQueueTotal = list.length;
    await openQueuedArtwork(list[0]);
}

async function openQueuedArtwork(albumId) {
    if (!albumId) {
        state.artworkQueue = null;
        state.artworkQueueTotal = 0;
        state.artworkQueueSubject = "";
        return;
    }
    state.artworkQueueOpening = true;
    try {
        if (state.artworkQueueSubject === "artist") {
            if (state.artistId !== albumId) await selectArtist(albumId);
            await openArtwork("artist");
            return;
        }
        if (!state.album || state.album.album.id !== albumId) await selectAlbum(albumId);
        await openArtwork("album");
    } finally {
        state.artworkQueueOpening = false;
    }
}

function advanceArtworkQueue() {
    const next = (state.artworkQueue || []).shift();
    if (!next) {
        state.artworkQueue = null;
        state.artworkQueueTotal = 0;
        return;
    }
    openQueuedArtwork(next).catch((error) => notify(error.message, "error"));
}

function artworkSearchText(album, artistName) {
    const title = stripReleaseType(String((album && album.title) || "").trim());
    const name = String(artistName || "").trim();
    return [name, title].filter(Boolean).join(" - ");
}

function artworkArtistName() {
    if (state.center === "artist" && state.artistDetail && state.artistDetail.artist) return state.artistDetail.artist.name || "";
    if (state.album && state.album.artist) return state.album.artist.name || "";
    if (state.artistDetail && state.artistDetail.artist) return state.artistDetail.artist.name || "";
    return "";
}

function setArtworkSearch(visible, query, mode) {
    const bar = document.getElementById("artwork-search");
    const input = document.getElementById("artwork-query");
    if (!bar) return;
    bar.classList.toggle("hidden", !visible);
    if (input && mode) input.placeholder = mode === "artist" ? "Artist name" : "Artist - Album";
    if (visible && input && query != null && document.activeElement !== input) input.value = query;
}

function syncArtworkQuery(data, previous) {
    const input = document.getElementById("artwork-query");
    if (!input || !data || data.query == null) return;
    if (input.value !== previous) return;
    const artistMode = state.artworkTarget && state.artworkTarget.subject === "artist";
    input.value = artistMode ? String(data.query) : queryWithoutReleaseType(data.query);
}

function sameArtId(left, right) {
    return String(left || "").toLowerCase() === String(right || "").toLowerCase();
}

function withArtworkSelection(rows, selected) {
    const list = rows || [];
    if (!selected || !selected.id) return list;
    const id = String(selected.id);
    let type = selected.asset_type || "";
    if (!type) {
        const match = list.find((row) => sameArtId(row.id, id));
        type = (match && match.asset_type) || "";
    }
    return list.map((row) => {
        if (sameArtId(row.id, id)) return { ...row, is_selected: true };
        if (type && type !== "extrafanart" && (row.asset_type || "front") === type) return { ...row, is_selected: false };
        return row;
    });
}

function exclusiveArtRows(items, type, chosenId) {
    const rows = items || [];
    if (!rows.length || type === "extrafanart") return rows;
    const chosen = chosenId ? rows.find((row) => sameArtId(row.id, chosenId)) : null;
    const marked = rows.filter((row) => row.is_selected);
    if (!chosen && marked.length < 2) return rows;
    const keeper = chosen || marked[0];
    return rows.map((row) => {
        const on = sameArtId(row.id, keeper.id);
        return row.is_selected === on ? row : { ...row, is_selected: on };
    });
}

function paintArtworkResults(data, artistMode, selected) {
    const modal = document.getElementById("artwork-modal");
    const pick = selected || state.artworkPick || null;
    const source = pick
        ? {
            ...data,
            artist: withArtworkSelection(data.artist, pick),
            album: withArtworkSelection(data.album, pick),
        }
        : data;
    const warnings = (source.warnings || []).map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("");
    const prompt = modal && modal.classList.contains("is-prompt");
    const sections = artistMode
        ? artSection("Artist", source.artist || [], ARTIST_ART_TYPES, "artist")
        : artSection("Album", source.album || [], ALBUM_ART_TYPES, "album");
    const extra = artistMode
        ? ""
        : (prompt
            ? `<p class="muted">Choose images, then continue the scan. Skip leaves the current artwork in place.</p>`
            : `<h3 class="section-label" id="asset-lyrics">Lyrics</h3><p class="muted">Lyrics are fetched from LRCLIB into the music folder.</p><p><button type="button" data-action="lyrics">Fetch lyrics</button></p>`);
    document.getElementById("artwork-body").innerHTML = warnings + sections + extra;
    showUndoArtwork(source.undo);
    primeArtworkCompare();
}

function primeArtworkCompare() {
    const body = document.getElementById("artwork-body");
    if (!body) return;
    const artistMode = !!(state.artworkTarget && state.artworkTarget.subject === "artist");
    const asset = artistMode ? "artistthumb" : "front";
    const cards = [...body.querySelectorAll(".art-card")];
    const suggested = cards.find((item) => item.dataset.asset === asset && item.dataset.suggested === "1" && item.dataset.selected !== "1")
        || cards.find((item) => item.dataset.suggested === "1" && item.dataset.selected !== "1");
    if (suggested) {
        showCompare(suggested);
        return;
    }
    const current = cards.find((item) => item.dataset.asset === asset && item.dataset.selected === "1") || cards[0];
    if (current) showCompare(current);
}

async function searchArtwork() {
    const input = document.getElementById("artwork-query");
    const artistMode = state.artworkTarget && state.artworkTarget.subject === "artist";
    const raw = input ? input.value.trim() : "";
    const query = artistMode ? raw : queryWithoutReleaseType(raw);
    if (input) input.value = query;
    const previous = query;
    document.getElementById("artwork-body").innerHTML = `<p class="muted">Searching artwork…</p>`;
    schedulePoll(400);
    if (artistMode) {
        const artistId = (state.artworkTarget && state.artworkTarget.artistId) || state.artistId;
        if (!artistId) throw new Error("Open an artist before searching artwork.");
        const data = await api(`/api/artists/${artistId}/artwork?harvest=1&q=${encodeURIComponent(query)}`);
        syncArtworkQuery(data, previous);
        paintArtworkResults(data, true);
        return;
    }
    const albumId = (state.artworkTarget && state.artworkTarget.albumId) || (state.album && state.album.album.id);
    if (!albumId) throw new Error("Open an album before searching artwork.");
    const data = await api(`/api/albums/${albumId}/artwork?harvest=1&scope=album&q=${encodeURIComponent(query)}`);
    syncArtworkQuery(data, previous);
    paintArtworkResults(data, false);
}

function artGrouped(rows, names, subject, prefix) {
    return names.map((name) => {
        const group = ASSET_GROUPS.find(([title]) => title === name);
        if (!group) return "";
        const types = group[1].map(([key]) => key);
        const mine = (rows || []).filter((row) => types.includes(row.asset_type || "front"));
        return `<h3 class="asset-group">${escapeHtml(name)}</h3>${artSection("", mine, types, subject, prefix)}`;
    }).join("");
}

function artSection(title, rows, types, subject, idPrefix) {
    const groups = new Map();
    const prefix = idPrefix || "asset";
    (types || []).forEach((type) => groups.set(type, []));
    rows.forEach((row) => {
        const type = row.asset_type || "front";
        if (!groups.has(type)) groups.set(type, []);
        groups.get(type).push(row);
    });
    const heading = title ? `<h3 class="section-label">${escapeHtml(title)}</h3>` : "";
    if (!rows.length && !groups.size) return `${heading}<p class="muted">No images.</p>`;
    const chosenId = state.artworkPick && state.artworkPick.id;
    const blocks = [...groups.entries()].map(([type, grouped]) => {
        const items = exclusiveArtRows(grouped, type, chosenId);
        const cards = items.map((row) => {
            const classes = ["art-card", row.is_selected ? "selected" : "", row.suggested ? "suggested" : "", row.banned ? "is-banned" : ""].filter(Boolean).join(" ");
            // An online picture can be banned (never suggested, never picked automatically); a banned one can be unbanned.
            const online = /^https?:/i.test(String(row.source_url || ""));
            const ban = !online ? "" : row.banned
                ? `<button type="button" class="art-ban is-on" data-action="art-unban" data-art="${escapeHtml(row.id)}" title="Unban this picture: it can be suggested and picked again" aria-label="Unban this picture">${banIcon()}</button>`
                : `<button type="button" class="art-ban" data-action="art-ban" data-art="${escapeHtml(row.id)}" title="Ban this picture: never suggested, never picked automatically" aria-label="Ban this picture">${banIcon()}</button>`;
            const asset = row.asset_type || "front";
            const pickTitle = "Compare this artwork";
            return `<div class="${classes}" data-art="${escapeHtml(row.id)}" data-asset="${escapeHtml(asset)}" data-provider="${escapeHtml(row.source_provider || "")}" data-resolution="${escapeHtml(row.resolution || "")}" data-size="${row.file_size_bytes || ""}" data-suggested="${row.suggested ? "1" : ""}" data-reason="${escapeHtml(row.suggestion_reason || "")}" data-ondisk="${row.on_disk ? "1" : ""}" data-selected="${row.is_selected ? "1" : ""}" data-online="${online ? "1" : ""}" data-banned="${row.banned ? "1" : ""}">
                <div class="art-shot">
                    <label class="art-tick" title="Tick to download, ban or delete several images at once"><input type="checkbox" data-action="art-tick" aria-label="Tick this image"></label>
                    <button type="button" class="art-pick" data-action="highlight-art" data-art="${escapeHtml(row.id)}" title="${escapeHtml(pickTitle)}">
                        <img src="/api/artwork/${row.id}/preview?w=342" loading="lazy" alt="">
                    </button>
                    ${downloadArtButton(row.id)}
                    ${zoomButton("zoom-art", `data-art="${escapeHtml(row.id)}"`)}
                </div>
                <div class="art-meta-row">
                    <div class="art-meta" data-action="highlight-art" data-art="${escapeHtml(row.id)}">${artMetaHtml(row)}</div>
                    ${ban}
                    <button type="button" class="art-delete" data-action="delete-art" data-art="${escapeHtml(row.id)}" title="Remove this artwork from the database and disk" aria-label="Remove this artwork">${trashIcon()}</button>
                </div>
            </div>`;
        }).join("") || `<p class="muted">No ${escapeHtml(assetLabel(type))} candidates yet.</p>`;
        const heading = assetHeading(type);
        const who = subject === "artist" ? "artist" : "album";
        return `<div class="asset-type-head"><h3 class="section-label" id="${escapeHtml(prefix)}-${escapeHtml(type)}" title="${escapeHtml(heading.title)}">${escapeHtml(heading.text)}</h3><button type="button" class="btn-ghost art-upload" data-action="upload-art" data-asset="${escapeHtml(type)}" data-subject="${who}" title="Upload ${escapeHtml(heading.text)} from this computer" aria-label="Upload ${escapeHtml(heading.text)}">${uploadIcon()}<span>Upload</span></button></div><div class="art-grid">${cards}</div>`;
    }).join("");
    return `${heading}${blocks}`;
}

let artworkPanelSerial = 0;

async function renderArtworkPanel(kind) {
    const artistMode = kind === "artist";
    const host = document.getElementById(artistMode ? "editor-artist-art" : "editor-album-art");
    const expected = artistMode ? "artist-art" : "album-art";
    const id = artistMode
        ? state.artistId
        : (state.album && state.album.album && state.album.album.id);
    if (!host || state.inspector !== expected) return;
    if (!id) {
        host.innerHTML = `<p class="muted">Open ${artistMode ? "an artist" : "an album"} to see its artwork.</p>`;
        return;
    }
    const request = ++artworkPanelSerial;
    if (host.dataset.loadedFor !== id) host.innerHTML = `<p class="muted">Loading artwork…</p>`;
    try {
        const data = await api(artistMode ? `/api/artists/${id}/artwork` : `/api/albums/${id}/artwork`);
        const current = artistMode
            ? state.artistId
            : (state.album && state.album.album && state.album.album.id);
        if (request !== artworkPanelSerial || state.inspector !== expected || current !== id) return;
        host.dataset.loadedFor = id;
        host.innerHTML = artistMode
            ? artGrouped(data.artist || [], ["Artist artwork (Kodi)"], "artist", "artist-asset")
            : artGrouped(data.album || [], ["Album artwork (Kodi)", "Cover Art Archive extras"], "album", "album-asset");
    } catch (error) {
        if (request !== artworkPanelSerial) return;
        delete host.dataset.loadedFor;
        host.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function artCards(id, root) {
    const scope = root || document;
    return [...scope.querySelectorAll(".art-card")].filter((card) => sameArtId(card.dataset.art, id));
}

function artCardOnDisk(id) {
    const card = artCards(id)[0];
    return !!(card && card.dataset.ondisk === "1");
}

function downloadArt(id) {
    if (!id) return;
    const label = artCardOnDisk(id) ? "Selecting artwork…" : "Downloading artwork…";
    markArtDownloading(id, true, label);
    return runAction(() => selectArt(id), label).finally(() => markArtDownloading(id, false));
}

function markArtDownloading(id, busy, label) {
    artCards(id).forEach((card) => {
        card.classList.toggle("is-downloading", busy);
        const shot = card.querySelector(".art-shot") || card;
        let overlay = shot.querySelector(".art-busy");
        if (!busy) {
            if (overlay) overlay.remove();
            return;
        }
        if (overlay) return;
        overlay = document.createElement("div");
        overlay.className = "art-busy";
        overlay.innerHTML = `<span class="activity-spin" aria-hidden="true"></span><span>${escapeHtml(label || "Downloading artwork…")}</span>`;
        shot.appendChild(overlay);
    });
}

// Saving artwork repaints the open item. The library list must stay where the user scrolled it.
async function keepTreeScroll(work) {
    const root = document.getElementById("tree");
    const top = root && typeof treeScrollTop === "function" ? treeScrollTop(root) : 0;
    try {
        return await work();
    } finally {
        if (root && root.isConnected && top > 0 && typeof pinTreeScroll === "function") pinTreeScroll(root, top);
    }
}

function selectArt(id) {
    return keepTreeScroll(() => selectArtNow(id));
}

function deleteArt(id) {
    return keepTreeScroll(() => deleteArtNow(id));
}

async function selectArtNow(id) {
    const data = await api(`/api/artwork/${id}/select`, { method: "POST", body: {} });
    const artwork = data.artwork || { id };
    artwork.id = artwork.id || id;
    artwork.is_selected = true;
    state.artworkPick = { id: artwork.id, asset_type: artwork.asset_type || "" };
    markArtSelected(artwork);
    const pages = Number(artwork.booklet_pages) || 0;
    const saved = artwork.downloaded ? "Artwork downloaded." : "Artwork selected.";
    notify(pages > 1 ? `Saved ${pages} booklet pages.` : saved, "info");
    if (artwork.undo) showUndoArtwork({ asset_type: artwork.asset_type || "" });
    try {
        await refreshArtworkModal(artwork);
    } finally {
        markArtSelected(artwork);
    }
    state.artDirty = true;
    await refreshOpenArtwork();
    state.artDirty = false;
}

async function refreshOpenArtwork() {
    state.artStamp = Date.now();
    if (state.center === "artist" && state.artistId) {
        const id = state.artistId;
        const data = await api(`/api/artists/${id}`);
        if (state.center !== "artist" || state.artistId !== id || !data.artist) return;
        state.artistDetail = data;
        renderCenter();
        renderEditor();
        return;
    }
    if (state.album && state.album.album) {
        const id = state.album.album.id;
        const trackId = state.trackId;
        const data = await api(`/api/albums/${id}`);
        if (!state.album || !state.album.album || state.album.album.id !== id) return;
        state.album = data;
        state.trackId = trackId;
        renderAlbum();
        renderEditor();
    }
}

function highlightArt(id) {
    const modal = document.getElementById("artwork-modal");
    const modalOpen = modal && !modal.classList.contains("hidden");
    const card = (modalOpen && artCards(id, modal)[0]) || artCards(id)[0];
    if (!card) return;
    document.querySelectorAll(".art-card.is-compared").forEach((other) => other.classList.remove("is-compared"));
    card.classList.add("is-compared");
    showCompare(card);
}

async function deleteArtNow(id) {
    await api(`/api/artwork/${id}`, { method: "DELETE", body: {} });
    await refreshArtworkModal();
    notify("Artwork removed.", "info");
    if (state.center === "artist" && state.artistId) await selectArtist(state.artistId);
    else if (state.album) await selectAlbum(state.album.album.id, true);
}

function artMetaHtml(row) {
    const size = row.file_size_bytes ? formatBytes(Number(row.file_size_bytes)) : "";
    const reason = row.suggested && row.suggestion_reason ? ` (${escapeHtml(row.suggestion_reason)})` : "";
    return `${escapeHtml(assetLabel(row.asset_type))} · ${escapeHtml(row.source_provider || "")}<br>${escapeHtml(row.resolution || "unknown")} ${escapeHtml(size)}${row.suggested ? ` · Suggested${reason}` : ""}${row.is_selected ? " · Selected" : ""}${row.banned ? ` · <strong class="art-banned-note">Banned</strong>` : ""}${row.wrong_shape ? ` · <strong class="art-banned-note" title="Listed at the shape of another type: never suggested or picked automatically">Wrong shape</strong>` : ""}`;
}

function markArtSelected(row) {
    const id = String((row && row.id) || "");
    const cards = [...document.querySelectorAll(".art-card")].filter((card) => sameArtId(card.dataset.art, id));
    const picked = state.artworkPick && sameArtId(state.artworkPick.id, id) ? state.artworkPick.asset_type : "";
    const type = (row && row.asset_type) || (cards[0] && cards[0].dataset.asset) || picked || "";
    if (type && type !== "extrafanart") {
        document.querySelectorAll(".art-card").forEach((other) => {
            if ((other.dataset.asset || "") !== type || sameArtId(other.dataset.art, id)) return;
            other.dataset.selected = "";
            other.classList.remove("selected");
            paintArtMeta(other);
        });
    }
    if (!cards.length) return;
    cards.forEach((card) => {
        if (row.resolution) card.dataset.resolution = row.resolution;
        if (row.file_size_bytes) card.dataset.size = String(row.file_size_bytes);
        card.dataset.selected = "1";
        card.classList.add("selected");
        paintArtMeta(card);
    });
}

function paintArtMeta(card) {
    const meta = card.querySelector(".art-meta");
    if (!meta) return;
    meta.innerHTML = artMetaHtml({
        asset_type: card.dataset.asset,
        source_provider: card.dataset.provider,
        resolution: card.dataset.resolution,
        file_size_bytes: card.dataset.size,
        suggested: card.dataset.suggested === "1",
        suggestion_reason: card.dataset.reason || "",
        is_selected: card.dataset.selected === "1",
    });
}

function openImageZoom(src, caption) {
    state.fanartZoom = null;
    paintImageZoom(src, caption);
}

function paintImageZoom(src, caption) {
    const image = document.getElementById("art-zoom-image");
    const captionEl = document.getElementById("art-zoom-caption");
    const note = caption || "";
    captionEl.textContent = note;
    paintImageZoom.seq = (paintImageZoom.seq || 0) + 1;
    const token = String(paintImageZoom.seq);
    image.dataset.zoom = token;
    image.onload = () => {
        if (image.dataset.zoom !== token) return;
        const measured = image.naturalWidth && image.naturalHeight ? `${image.naturalWidth} × ${image.naturalHeight} px` : "";
        captionEl.textContent = [measured, note].filter(Boolean).join(" · ");
    };
    image.alt = "Enlarged artwork";
    image.src = "";
    image.src = src;
    const loupe = document.getElementById("loupe");
    if (loupe) loupe.classList.add("hidden");
    document.getElementById("art-zoom").classList.remove("hidden");
    syncFanartNav();
}

function closeArtZoom() {
    const zoom = document.getElementById("art-zoom");
    if (zoom) zoom.classList.add("hidden");
    state.fanartZoom = null;
    syncFanartNav();
}

function syncFanartNav() {
    const zoom = document.getElementById("art-zoom");
    const open = zoom && !zoom.classList.contains("hidden");
    const on = !!(open && state.fanartZoom && state.fanartZoom.total > 1);
    ["fanart-prev", "fanart-next"].forEach((id) => {
        const button = document.getElementById(id);
        if (button) button.classList.toggle("hidden", !on);
    });
}

function openFanartZoom(view, index) {
    const total = Math.max(1, Number(view.total) || 1);
    const next = ((index % total) + total) % total;
    state.fanartZoom = {
        id: view.id,
        index: next,
        total,
        name: view.name || "Artist",
        stamp: view.stamp,
    };
    const label = total > 1 ? `Fanart ${next + 1} / ${total}` : "Fanart";
    paintImageZoom(
        `/api/artists/${view.id}/fanart/${next}?t=${view.stamp}`,
        `${state.fanartZoom.name} · ${label}`,
    );
}

function stepFanart(delta) {
    const view = state.fanartZoom;
    if (!view || view.total < 2) return;
    openFanartZoom(view, view.index + delta);
}

function openArtZoom(id) {
    const card = artCards(id)[0];
    const meta = card && card.querySelector(".art-meta") ? card.querySelector(".art-meta").textContent.replace(/\s+/g, " ").trim() : "";
    openImageZoom(`/api/artwork/${encodeURIComponent(id)}/preview`, meta);
}

function openArtistThumbZoom() {
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    const stamp = artistArtStamp(artist);
    openImageZoom(
        `/api/artists/${artist.id}/art/artistthumb?t=${stamp}`,
        `${artist.name || "Artist"} · Artist thumb`,
    );
}

function openChipZoom(subject, type) {
    const labels = {
        artistthumb: "Artist thumb",
        fanart: "Fanart",
        clearlogo: "Clearlogo",
        banner: "Banner",
        landscape: "Landscape",
        front: "Front",
        back: "Back",
        discart: "Disc",
    };
    if (subject === "artist") {
        const artist = (state.artistDetail && state.artistDetail.artist) || (state.album && state.album.artist);
        if (!artist) return;
        const stamp = artistArtStamp(artist);
        if (type === "fanart") {
            openFanartZoom({
                id: artist.id,
                total: Number(artist.assets && artist.assets.fanart) || 1,
                name: artist.name || "Artist",
                stamp,
            }, 0);
            return;
        }
        openImageZoom(
            `/api/artists/${artist.id}/art/${encodeURIComponent(type)}?t=${stamp}`,
            `${artist.name || "Artist"} · ${labels[type] || type}`,
        );
        return;
    }
    const album = state.album && state.album.album;
    if (!album) return;
    openImageZoom(
        `/api/albums/${album.id}/art/${encodeURIComponent(type)}`,
        `${album.title || "Album"} · ${labels[type] || type}`,
    );
}

async function showAlbumNfoModal(albumId) {
    if (!albumId) return;
    try {
        const data = await api(`/api/albums/${albumId}/nfo`);
        openNfoModal(data, { subject: "album", id: albumId });
    } catch (error) {
        notify(error.message || "album.nfo could not be opened.", "error");
    }
}

async function showArtistNfoModal(artistId) {
    if (!artistId) return;
    try {
        const data = await api(`/api/artists/${artistId}/nfo`);
        openNfoModal(data, { subject: "artist", id: artistId });
    } catch (error) {
        notify(error.message || "artist.nfo could not be opened.", "error");
    }
}

function nfoBlank(value, missing) {
    const text = String(value || "").trim();
    return text || missing;
}

function paintNfoChanges(diff, stale, filename) {
    const note = document.getElementById("nfo-note");
    const box = document.getElementById("nfo-diff");
    const changes = (diff && diff.changes) || [];
    const write = document.getElementById("nfo-write");
    if (write) write.classList.toggle("hidden", !(state.nfoModal && (changes.length || stale)));
    if (!box) return;
    if (!changes.length) {
        box.classList.add("hidden");
        box.innerHTML = "";
        if (note) {
            const unread = ((diff && diff.notes) || [])[0] || "";
            note.textContent = unread || (stale ? "The database has changes that are not in this file." : "");
            note.classList.toggle("hidden", !note.textContent);
        }
        return;
    }
    if (note) note.classList.add("hidden");
    box.classList.remove("hidden");
    const fileLabel = filename || "File";
    box.innerHTML = `<div class="nfo-diff-head"><span></span><span></span><span>${escapeHtml(fileLabel)}</span><span>Database</span></div>${changes.map((row) => {
        const keep = row.field && row.kind && row.id
            ? `<button type="button" class="btn-ghost nfo-keep" data-action="nfo-keep-field" data-kind="${escapeHtml(row.kind)}" data-id="${escapeHtml(row.id)}" data-field="${escapeHtml(row.field)}"${row.from_kind ? ` data-from-kind="${escapeHtml(row.from_kind)}" data-from-id="${escapeHtml(row.from_id || "")}"` : ""}>Keep .nfo field</button>`
            : "";
        return `<div class="nfo-diff-row"><span>${keep}</span><span>${escapeHtml(row.label)}</span><span>${escapeHtml(nfoBlank(row.file, "not in the file"))}</span><span>${escapeHtml(nfoBlank(row.database, "not in the database"))}</span></div>`;
    }).join("")}`;
}

async function showNfo(subject) {
    const artist = (state.artistDetail && state.artistDetail.artist) || (state.album && state.album.artist);
    const album = state.album && state.album.album;
    const id = subject === "artist" ? artist && artist.id : album && album.id;
    if (!id) return;
    const path = subject === "artist" ? `/api/artists/${id}/nfo` : `/api/albums/${id}/nfo`;
    const data = await api(path);
    openNfoModal(data, { subject, id });
}

function openNfoModal(data, source) {
    state.nfoModal = source || null;
    document.getElementById("nfo-title").textContent = data.name || "nfo";
    document.getElementById("nfo-body").textContent = data.text || "";
    paintNfoChanges(data.diff, data.stale, data.name);
    document.getElementById("nfo-modal").classList.remove("hidden");
}

async function copyOpenNfo() {
    const text = document.getElementById("nfo-body").textContent || "";
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            notify("Copied the .nfo.", "info");
            return;
        }
    } catch (error) {
        /* HTTP pages cannot use the clipboard API, so the selection copy below is used. */
    }
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    notify("Copied the .nfo.", "info");
}

async function keepNfoField(action) {
    await api("/api/v1/nfo/keep", {
        method: "POST",
        body: {
            kind: action.dataset.kind,
            id: action.dataset.id,
            field: action.dataset.field,
            from_kind: action.dataset.fromKind || "",
            from_id: action.dataset.fromId || "",
        },
    });
    notify("The database now uses that .nfo value.", "success");
    const source = state.nfoModal;
    if (source && source.kind) await showVideoNfo(source.kind, source.id);
    else if (source && source.subject === "album" && source.id) await showAlbumNfoModal(source.id);
    else if (source && source.subject === "artist" && source.id) await showArtistNfoModal(source.id);
    else if (source && source.subject) await showNfo(source.subject);
}

async function writeOpenNfo() {
    const source = state.nfoModal;
    if (!source) return;
    if (source.kind) {
        await writeVideoNfo(source.kind, [source.id]);
        await showVideoNfo(source.kind, source.id);
        return;
    }
    if (source.subject === "artist") {
        const artistId = source.id || state.artistId;
        if (artistId) {
            await api(`/api/artists/${artistId}/nfo`, { method: "POST", body: {} });
            // The file is written when the call returns. Clear the purple pill now, before anything slow (the
            // library reload can take a long time while a scan runs), so it never lingers after a good write.
            clearArtistNfoStale(artistId);
            notify("Artist NFO written.", "info");
            if (state.artistId === artistId) await selectArtist(artistId);
            else refreshLibraryItems([], [artistId]).catch(() => {});
            await showArtistNfoModal(artistId);
            return;
        }
        await writeArtistNfo();
        await showNfo("artist");
        return;
    }
    if (source.subject === "album") {
        const albumId = source.id || (state.album && state.album.album && state.album.album.id);
        if (albumId && (!state.album || !state.album.album || state.album.album.id !== albumId)) {
            const data = await api(`/api/albums/${albumId}/nfo`, { method: "POST", body: {} });
            // The file is written when the call returns; use its answer to clear the purple pill straight away
            // rather than waiting for a library reload, which can take a long time while a scan runs.
            applyAlbumNfoStale(albumId, !!(data && data.album && data.album.nfo_stale));
            renderTree();
            notify("Album NFO written.", "info");
            await showAlbumNfoModal(albumId);
            refreshLibraryItems([albumId]).catch(() => {});
            return;
        }
        await writeAlbumNfo();
        if (albumId) await showAlbumNfoModal(albumId);
    }
}

function openAlbumCoverZoom() {
    const album = state.album && state.album.album;
    if (!album || !album.has_artwork) return;
    const stamp = coverStamp(album);
    openImageZoom(
        `/api/albums/${album.id}/cover?t=${stamp}`,
        `${album.title || "Album"} · Front cover`,
    );
}


// Ticking several pictures in the music artwork window: a bar offers Download, Ban and Delete for all of them.
function musicArtTicked() {
    return [...document.querySelectorAll("#artwork-modal .art-card")].filter((card) => {
        const box = card.querySelector("[data-action='art-tick']");
        return box && box.checked;
    });
}

function paintMusicArtTicks() {
    document.querySelectorAll("#artwork-modal .art-card").forEach((card) => {
        const box = card.querySelector("[data-action='art-tick']");
        card.classList.toggle("is-ticked", Boolean(box && box.checked));
    });
    const bar = document.getElementById("art-bulk");
    if (!bar) return;
    const cards = musicArtTicked();
    bar.classList.toggle("hidden", !cards.length);
    if (!cards.length) return;
    const fresh = cards.filter((card) => card.dataset.selected !== "1").length;
    const bannable = cards.filter((card) => card.dataset.online === "1" && card.dataset.banned !== "1").length;
    bar.innerHTML = `<span class="art-bulk-count">${cards.length} ticked</span>
        <button type="button" class="btn-primary" data-action="art-bulk-select" ${fresh ? "" : "disabled"} title="Download the ticked pictures. The first ticked cover (banner, logo…) becomes the file the players use; further ones are saved next to it as folder1, folder2… Fanart is added as new files.">Download ${fresh}</button>
        <button type="button" class="btn-ghost" data-action="art-bulk-ban" ${bannable ? "" : "disabled"} title="Ban the ticked online pictures: never suggested, never picked automatically">Ban ${bannable}</button>
        <button type="button" class="btn-danger" data-action="art-bulk-delete" title="Remove the ticked pictures from disk and the database">Delete ${cards.length}</button>
        <button type="button" class="btn-ghost" data-action="art-bulk-clear">Clear ticks</button>`;
}

function clearMusicArtTicks() {
    document.querySelectorAll("#artwork-modal [data-action='art-tick']").forEach((box) => { box.checked = false; });
    paintMusicArtTicks();
}

async function musicArtMany(action, ids) {
    if (!ids.length) return null;
    const result = await api(`/api/artwork/many/${action}`, { method: "POST", body: { ids } });
    await refreshArtworkModal();
    paintMusicArtTicks();
    if (action === "select" || action === "remove") {
        if (state.center === "artist" && state.artistId) await selectArtist(state.artistId);
        else if (state.album) await selectAlbum(state.album.album.id, true);
    }
    return result;
}

async function musicArtBulk(action) {
    const cards = musicArtTicked();
    const ids = (action === "select" ? cards.filter((card) => card.dataset.selected !== "1")
        : action === "ban" ? cards.filter((card) => card.dataset.online === "1" && card.dataset.banned !== "1") : cards)
        .map((card) => card.dataset.art);
    const result = await musicArtMany(action, ids);
    if (!result) return;
    const failed = (result.failed || []).length;
    const tail = failed ? `, ${failed} failed: ${result.failed[0].error}` : "";
    if (action === "select") notify(`${result.saved || 0} image${result.saved === 1 ? "" : "s"} saved${tail}.`, failed ? "warning" : "success");
    else if (action === "remove") notify(`${result.removed || 0} image${result.removed === 1 ? "" : "s"} removed${tail}.`, failed ? "warning" : "success");
    else notify(`${result.banned || 0} picture${result.banned === 1 ? "" : "s"} banned.`, "success");
}
