function renderCenter() {
    const artistView = document.getElementById("center-artist");
    const albumView = document.getElementById("center-album");
    const title = document.getElementById("center-title");
    if (state.center === "artist" && state.artistDetail) {
        artistView.classList.remove("hidden");
        albumView.classList.add("hidden");
        title.textContent = "Artist profile";
        document.getElementById("columns-btn").classList.add("hidden");
        renderArtist();
        showArtistInspector();
        return;
    }
    artistView.classList.add("hidden");
    albumView.classList.remove("hidden");
    title.textContent = "Track matrix";
    document.getElementById("columns-btn").classList.remove("hidden");
    renderAlbum();
    showAlbumInspector();
}

function renderArtist() {
    const host = document.getElementById("center-artist");
    const artist = state.artistDetail.artist;
    const albums = state.artistDetail.albums || [];
    const stamp = artistArtStamp(artist);
    const formed = [artist.formed ? `Formed ${artist.formed}` : "", artist.origin ? `in ${artist.origin}` : ""].filter(Boolean).join(" ");
    const years = artist.years_active ? `Active ${artist.years_active}` : "";
    const links = [
        artist.website ? `<a href="${escapeHtml(artist.website)}" target="_blank" rel="noopener">Website</a>` : "",
        artist.musicbrainz_artist_id ? `<a href="https://musicbrainz.org/artist/${escapeHtml(artist.musicbrainz_artist_id)}" target="_blank" rel="noopener">MusicBrainz</a>` : "",
        artist.discogs_url ? `<a href="${escapeHtml(artist.discogs_url)}" target="_blank" rel="noopener">Discogs</a>` : "",
        artist.wikipedia_url ? `<a href="${escapeHtml(artist.wikipedia_url)}" target="_blank" rel="noopener">Wikipedia</a>` : "",
    ].filter(Boolean).join(" · ");
    const genres = (artist.genres || []).map((genre) => `<button type="button" class="tag-pill vlink-chip" data-action="music-filter-query" data-query="${escapeHtml(genre)}" title="Filter library by ${escapeHtml(genre)}">${escapeHtml(genre)}</button>`).join("");
    const showBadge = typeof artBadgeAllowed === "function" && artBadgeAllowed("music");
    host.innerHTML = `
        <div class="info-stack">
        ${infoBanner({
            banner: artist.assets && artist.assets.banner ? `/api/artists/${artist.id}/art/banner?t=${stamp}&w=${musicArtWidth("banner")}` : "",
            landscape: artist.assets && artist.assets.landscape ? `/api/artists/${artist.id}/art/landscape?t=${stamp}&w=${musicArtWidth("landscape")}` : "",
            clearlogo: artist.assets && artist.assets.clearlogo ? `/api/artists/${artist.id}/art/clearlogo?t=${stamp}&w=${musicArtWidth("clearlogo")}` : "",
        }, musicHeroActions("artist", artist, libraryWritable(artist.path)))}
        <div class="info-body">
            ${infoFanart(artist.assets && artist.assets.fanart ? `/api/artists/${artist.id}/art/fanart?t=${stamp}&w=${musicArtWidth("fanart")}` : "")}
            <div class="info-body-row">
            <div class="artist-thumb-col info-cover">
            <div class="artist-thumb-wrap">
                <button type="button" class="artist-thumb${artist.assets && artist.assets.artistthumb ? " has-swap-bar" : ""}" ${artist.assets && artist.assets.artistthumb ? `data-action="zoom-artist-thumb" title="Enlarge artwork"` : `data-action="artwork" data-subject="artist" title="Swap artwork"`}>
                    <img alt="" src="/api/artists/${artist.id}/art/artistthumb?t=${stamp}&w=${musicArtWidth("artistthumb")}"${showBadge ? ` onload="updateArtBadgeOnLoad(this)"` : ""} onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'art-fallback', textContent:'Thumb'}))">
                </button>
                ${showBadge ? `<span class="art-dim-badge hidden"></span>` : ""}
                ${artist.assets && artist.assets.artistthumb ? `<button type="button" class="art-swap-bar" data-action="artwork" data-subject="artist" title="Swap artwork" aria-label="Swap artwork">Swap</button>` : ""}
            </div>
            <button type="button" data-action="artist-move" ${libraryWritable(artist.path) ? "" : "disabled"}>Move…</button>
            </div>
            <div class="artist-copy info-copy">
                <div class="artist-name-line info-name">
                    ${artistNameCell(artist)}
                    <button type="button" class="icon-btn" data-action="edit-artist-name" title="${state.artistNameEditing && state.artistNameId === artist.id ? "Save artist name" : "Edit artist name"}" aria-label="${state.artistNameEditing && state.artistNameId === artist.id ? "Save artist name" : "Edit artist name"}">${pencilIcon()}</button>
                </div>
                <span class="tag-pill">${escapeHtml(artist.type || "Artist")}</span>
                <p class="muted">${escapeHtml([formed, years].filter(Boolean).join(" · "))}</p>
                <div class="link-row">${links || `<span class="muted">Find metadata to fill website, Discogs, and Wikipedia links.</span>`}</div>
                ${artistChips(artist)}
                ${artistAliasLine(artist)}
                <div class="genre-row">${genres}</div>
            </div>
            </div>
        </div>
        </div>
        <div class="profile-body">
            <p class="folder-line">Folder: ${escapeHtml(artist.path || "")}${libraryWritable(artist.path) ? "" : " · read-only"}</p>
            <div class="action-row">
                <button type="button" data-action="scrape-artist">Find metadata</button>
                <button type="button" data-action="artist-manual-search">Artist metadata manual search</button>
                <button type="button" data-action="download-artist-art" ${libraryWritable(artist.path) ? "" : "disabled"}>Download missing artist artwork</button>
                <button type="button" data-action="merge-with">Merge with…</button>
            </div>
            ${biographyBlock(artist)}
            <div class="action-row">
                <button type="button" class="btn-ghost" data-action="write-artist-nfo">Write artist.nfo</button>
                <button type="button" class="btn-ghost" data-action="artwork" data-subject="artist">Swap thumb</button>
            </div>
            <h3>Discography</h3>
            <div class="action-row">
                <span id="studio-count" class="muted">MusicBrainz discography stays blank until you refresh.</span>
                <button type="button" class="btn-ghost" data-action="refresh-discography">Refresh discography</button>
                <button type="button" class="btn-ghost${integrationOn("lidarr") ? "" : " is-unavailable"}" data-action="lidarr-missing">Search missing in Lidarr</button>
            </div>
            <div id="discography-grid">${discographyHtml(albums)}</div>
        </div>`;
    const nameInput = document.getElementById("artist-name-input");
    if (nameInput) {
        nameInput.addEventListener("input", () => { state.artistNameDraft = nameInput.value; });
        if (state.artistNameFocus) {
            nameInput.focus();
            nameInput.select();
            state.artistNameFocus = false;
        }
    }
    const editor = document.getElementById("bio-editor");
    if (editor) editor.addEventListener("input", () => {
        state.bioDraft = editor.value;
        if (state.artistId) state.bioDrafts[state.artistId] = editor.value;
        noteArtistChanges(state.artistId, editor.value !== storedBiography());
        if (editor.value === storedBiography() && state.artistId) delete state.bioDrafts[state.artistId];
    });
    if (state.discography && state.discographyArtist === artist.id) paintDiscography(state.discography);
}

function albumTitleCell(album) {
    const icon = `<span class="match-icon ${escapeHtml(album.match_tier || "unmatched")}">${matchIcon(album.match_tier)}</span>`;
    if (state.albumTitleEditing && state.albumTitleId === album.id) {
        return `<div class="album-title-edit">${icon}<input id="album-title-input" class="album-title-input" value="${escapeHtml(state.albumTitleDraft)}" aria-label="Album title"></div>`;
    }
    return `<h2>${icon}<span class="album-title-text">${escapeHtml(album.title)}</span></h2>`;
}

function startAlbumTitleEdit() {
    const album = state.album && state.album.album;
    if (!album) return;
    state.albumTitleEditing = true;
    state.albumTitleId = album.id;
    state.albumTitleDraft = album.title || "";
    state.albumTitleFocus = true;
    renderAlbum();
}

function cancelAlbumTitleEdit() {
    if (!state.albumTitleEditing) return;
    state.albumTitleEditing = false;
    state.albumTitleDraft = "";
    state.albumTitleFocus = false;
    if (state.center === "album" && state.album) renderAlbum();
}

async function saveAlbumTitle() {
    const input = document.getElementById("album-title-input");
    const title = String(input ? input.value : state.albumTitleDraft || "").trim();
    const album = state.album && state.album.album;
    if (!album) return;
    if (!title) {
        notify("Album title cannot be empty.", "warning");
        if (input) input.focus();
        return;
    }
    const data = await api(`/api/albums/${album.id}/title`, { method: "POST", body: { title } });
    state.albumTitleEditing = false;
    state.albumTitleDraft = "";
    state.albumTitleFocus = false;
    state.album = data;
    const saved = data.album && data.album.title;
    for (const artist of state.artists || []) {
        const row = (artist.albums || []).find((item) => item.id === album.id);
        if (row && saved) row.title = saved;
    }
    renderTree();
    renderCenter();
    renderEditor();
    if (data.nfo_warning) notify(`Album title saved. ${data.nfo_warning}`, "warning");
    else if (data.nfo_written) notify("Album title saved, and album.nfo updated.", "info");
    else notify("Album title saved.", "info");
}

function deleteOpenArtist() {
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    const name = artist.name || "This artist";
    const folder = artist.path ? ` Delete from disk removes the folder ${artist.path} and the albums inside it.` : "";
    askDanger(
        "Remove this artist?",
        `${name} can be removed from the library only, or deleted from disk.${folder} Deleting from disk cannot be undone. Removing from the library leaves the files in place.`,
        "Delete from disk",
        () => deleteLibrary({ artist_ids: [artist.id] }, name),
        true,
        () => forgetLibrary({ artist_ids: [artist.id] }, name),
    );
}

function deleteOpenAlbum() {
    const album = state.album && state.album.album;
    if (!album) return;
    const name = album.title || "This album";
    const folder = album.path ? ` Delete from disk removes the folder ${album.path} and the audio files in it.` : "";
    askDanger(
        "Remove this album?",
        `${name} can be removed from the library only, or deleted from disk.${folder} Deleting from disk cannot be undone. Removing from the library leaves the files in place.`,
        "Delete from disk",
        () => deleteLibrary({ album_ids: [album.id] }, name),
        true,
        () => forgetLibrary({ album_ids: [album.id] }, name),
    );
}

function artistNameCell(artist) {
    if (state.artistNameEditing && state.artistNameId === artist.id) {
        return `<input id="artist-name-input" class="artist-name-input" value="${escapeHtml(state.artistNameDraft)}" aria-label="Artist name">`;
    }
    return `<h2>${escapeHtml(artist.name)}</h2>`;
}

function pencilIcon() {
    return `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M12.1 1.4a1.5 1.5 0 0 1 2.1 2.1L5.7 12.1 2.5 13.1l1-3.2 8.6-8.5zM3.9 10.7l-.5 1.9 1.9-.5 6.8-6.8-1.4-1.4-6.8 6.8z"/></svg>`;
}

function startArtistNameEdit() {
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    state.artistNameEditing = true;
    state.artistNameId = artist.id;
    state.artistNameDraft = artist.name || "";
    state.artistNameFocus = true;
    renderArtist();
}

function cancelArtistNameEdit() {
    if (!state.artistNameEditing) return;
    state.artistNameEditing = false;
    state.artistNameDraft = "";
    state.artistNameFocus = false;
    if (state.center === "artist" && state.artistDetail) renderArtist();
}

async function saveArtistName() {
    const input = document.getElementById("artist-name-input");
    const name = String(input ? input.value : state.artistNameDraft || "").trim();
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    if (!name) {
        notify("Artist name cannot be empty.", "warning");
        if (input) input.focus();
        return;
    }
    const data = await api(`/api/artists/${artist.id}/name`, { method: "POST", body: { name } });
    state.artistNameEditing = false;
    state.artistNameDraft = "";
    state.artistNameFocus = false;
    state.artistDetail = data;
    const row = (state.artists || []).find((item) => item.id === artist.id);
    if (row) row.name = data.artist.name;
    if (state.album && state.album.artist && state.album.artist.id === artist.id) state.album.artist.name = data.artist.name;
    renderTree();
    renderCenter();
    renderEditor();
    if (data.nfo_warning) notify(`Artist name saved. ${data.nfo_warning}`, "warning");
    else if (data.nfo_written) notify("Artist name saved, and artist.nfo updated.", "info");
    else notify("Artist name saved.", "info");
}

function changesPill() {
    return `<span class="tag-pill changes-pill" title="Edited, not saved">Changes</span>`;
}

function nfoStalePill(label, albumId, artistId) {
    const click = albumId
        ? ` data-action="show-album-nfo-diff" data-album-id="${escapeHtml(albumId)}" title="Database has changes that are not in this file. Click to show them."`
        : artistId
        ? ` data-action="show-artist-nfo-diff" data-artist-id="${escapeHtml(artistId)}" title="Database has changes that are not in this file. Click to show them."`
        : ` title="Database has changes that are not in this file"`;
    return `<span class="tag-pill changes-pill nfo-stale-pill"${click}>${escapeHtml(label)}</span>`;
}

function rememberNfoStale(kind, row) {
    if (!row || row.id == null || !Object.prototype.hasOwnProperty.call(row, "nfo_stale")) return;
    const bag = kind === "artist" ? state.staleNfoArtists : state.staleNfoAlbums;
    if (row.nfo_stale) bag.add(row.id);
    else bag.delete(row.id);
}

function applyAlbumNfoStale(albumId, stale) {
    if (!albumId) return;
    rememberNfoStale("album", { id: albumId, nfo_stale: !!stale });
    for (const artist of state.artists || []) {
        const album = (artist.albums || []).find((item) => item.id === albumId);
        if (album) album.nfo_stale = !!stale;
    }
}

function syncOpenNfoStale() {
    const album = state.album && state.album.album;
    if (album) rememberNfoStale("album", album);
    if (state.album && state.album.artist) rememberNfoStale("artist", state.album.artist);
    const artist = state.artistDetail && state.artistDetail.artist;
    if (artist) rememberNfoStale("artist", artist);
}

function holdBioDraft() {
    if (!state.artistId || !state.bioEditing) return;
    const editor = document.getElementById("bio-editor");
    const text = editor ? editor.value : state.bioDraft;
    const stored = storedBiography();
    if (text !== stored) {
        state.bioDrafts[state.artistId] = text;
        state.dirtyArtists.add(state.artistId);
    } else {
        delete state.bioDrafts[state.artistId];
        state.dirtyArtists.delete(state.artistId);
    }
}

function storedBiography() {
    const artist = state.artistDetail && state.artistDetail.artist;
    return (artist && artist.biography) || "";
}

function noteArtistChanges(id, dirty) {
    const had = state.dirtyArtists.has(id);
    if (dirty) state.dirtyArtists.add(id);
    else state.dirtyArtists.delete(id);
    if (had !== dirty) renderTree();
}

function noteAlbumChanges(albumId, tracks) {
    const dirty = (tracks || []).some((track) => {
        const drafts = state.tagDrafts[track.id];
        return drafts && Object.keys(drafts).length;
    }) || state.bulkDirtyAlbum === albumId;
    const had = state.dirtyAlbums.has(albumId);
    if (dirty) state.dirtyAlbums.add(albumId);
    else state.dirtyAlbums.delete(albumId);
    if (had !== dirty) renderTree();
}

function bioToggleButton() {
    const collapsed = !!state.bioCollapsed;
    const label = collapsed ? "Show biography" : "Hide biography";
    return `<button type="button" class="icon-btn" data-action="toggle-bio" title="${label}" aria-label="${label}" aria-expanded="${collapsed ? "false" : "true"}">${reviewChevron(collapsed)}</button>`;
}

function toggleArtistBio() {
    state.bioCollapsed = !state.bioCollapsed;
    localStorage.setItem("resonance.bioCollapsed", state.bioCollapsed ? "1" : "0");
    renderCenter();
}

function biographyBlock(artist) {
    const collapsed = !!state.bioCollapsed;
    const toggle = bioToggleButton();
    if (state.bioEditing) {
        return `<div class="artist-bio">
            <div class="bio-head"><h3>Biography</h3>${toggle}</div>
            <textarea id="bio-editor" class="bio-editor" rows="12">${escapeHtml(state.bioDraft)}</textarea>
            <div class="action-row">
                <button type="button" data-action="save-bio">Save</button>
                <button type="button" class="btn-ghost" data-action="cancel-bio">Cancel</button>
            </div>
        </div>`;
    }
    const body = `<p class="bio">${escapeHtml(artist.biography || "No biography stored yet.")}</p>`;
    return `<div class="artist-bio${collapsed ? " is-collapsed" : ""}">
        <div class="bio-head">
            <h3>Biography</h3>
            <button type="button" class="icon-btn" data-action="edit-bio" title="Edit biography" aria-label="Edit biography">${pencilIcon()}</button>
            ${toggle}
        </div>
        ${collapsed ? "" : body}
    </div>`;
}

function startBioEdit() {
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    state.bioEditing = true;
    state.bioCollapsed = false;
    localStorage.setItem("resonance.bioCollapsed", "0");
    state.bioDraft = artist.biography || "";
    renderCenter();
    const editor = document.getElementById("bio-editor");
    if (editor) {
        editor.focus();
        editor.setSelectionRange(editor.value.length, editor.value.length);
    }
}

function cancelBioEdit() {
    delete state.bioDrafts[state.artistId];
    noteArtistChanges(state.artistId, false);
    state.bioEditing = false;
    state.bioDraft = "";
    renderCenter();
}

async function saveBiography() {
    const editor = document.getElementById("bio-editor");
    const text = editor ? editor.value : state.bioDraft;
    const host = document.getElementById("editor-artist-nfo");
    const fields = host && host.querySelector("[data-nfo]") ? nfoFormValues(host) : null;
    const data = await api(`/api/artists/${state.artistId}/biography`, { method: "POST", body: { biography: text, fields } });
    state.artistDetail = data;
    state.bioEditing = false;
    state.bioDraft = "";
    delete state.bioDrafts[state.artistId];
    noteArtistChanges(state.artistId, false);
    renderCenter();
    if (fields) restoreArtistFields(fields);
    if (data.nfo_warning) notify(`Biography saved. ${data.nfo_warning}`, "warning");
    else if (data.nfo_written) notify("Biography and artist info saved, and artist.nfo updated.", "info");
    else notify("Biography saved.", "info");
}

function restoreArtistFields(fields) {
    const host = document.getElementById("editor-artist-nfo");
    if (!host || !fields || !host.querySelector("[data-nfo]")) return;
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        if (!Object.prototype.hasOwnProperty.call(fields, input.dataset.nfo)) return;
        if (input.type === "checkbox") {
            input.checked = !!fields[input.dataset.nfo];
            return;
        }
        input.value = fields[input.dataset.nfo] ?? "";
    });
    const editor = host.querySelector(".genre-editor");
    if (!editor || !Array.isArray(fields.genres)) return;
    editor.innerHTML = "";
    fields.genres.forEach((name) => {
        const label = String(name || "").trim();
        if (!label) return;
        const chip = document.createElement("span");
        chip.className = "genre-chip";
        chip.innerHTML = `<span data-genre="${escapeHtml(label)}">${escapeHtml(label)}</span><button type="button" class="genre-remove" data-action="remove-genre" aria-label="Remove ${escapeHtml(label)}">×</button>`;
        editor.appendChild(chip);
    });
}

function artistArtStamp(artist) {
    const rev = state.artStamp ? `-${state.artStamp}` : "";
    return encodeURIComponent(`${(artist && (artist.updated_at || artist.name)) || ""}${rev}`);
}

function coverStamp(album) {
    const rev = state.artStamp ? `-${state.artStamp}` : "";
    return encodeURIComponent(`${(album && album.updated_at) || ""}${rev}`);
}

function musicHeroActions(kind, item, writable) {
    const mark = kind === "artist" ? "mark-artist" : "mark-album";
    const ignore = kind === "artist" ? "ignore-artist" : "ignore-album";
    const lock = kind === "artist" ? "lock-artist" : "lock-album";
    const remove = kind === "artist" ? "delete-open-artist" : "delete-open-album";
    return `${item.status === "NEW" ? `<span class="badge-new">NEW</span>` : ""}
        ${item.status === "IGNORED" ? `<span class="tag-pill">Ignored</span>` : ""}
        ${item.locked ? `<span class="tag-pill">Locked</span>` : ""}
        <button type="button" class="${processButtonClass(item.status)}" data-action="${mark}">${processLabel(item.status)}</button>
        <button type="button" class="btn-ghost" data-action="${ignore}">${ignoreLabel(item.status)}</button>
        ${typeof lockButton === "function" ? lockButton(kind, item, lock) : ""}
        <button type="button" class="title-delete" data-action="${remove}" title="Remove…" aria-label="Remove…" ${writable ? "" : "disabled"}>${trashSvg()}</button>`;
}

// Smaller copies for what is only shown on the page. Zoom and the artwork window load the original.
const MUSIC_ART_WIDTH = { banner: 780, landscape: 780, clearlogo: 500, fanart: 780, artistthumb: 342 };

function musicArtWidth(kind) {
    return MUSIC_ART_WIDTH[kind] || 500;
}

function albumAssetUrl(album, kind) {
    const assets = new Set(state.album && state.album.assets || []);
    if (!assets.has(kind)) return "";
    return `/api/albums/${album.id}/art/${kind}?t=${coverStamp(album)}&w=${musicArtWidth(kind)}`;
}

function resolvedArtistAssets(artist) {
    if (artist && artist.assets) return artist.assets;
    if (state.artistDetail && state.artistDetail.artist && artist && state.artistDetail.artist.id === artist.id) {
        return state.artistDetail.artist.assets || {};
    }
    return {};
}

function albumBannerUrl(album, artist) {
    const own = albumAssetUrl(album, "banner");
    if (own) return own;
    const assets = resolvedArtistAssets(artist);
    if (assets.banner && artist && artist.id) {
        return `/api/artists/${artist.id}/art/banner?t=${artistArtStamp(artist)}&w=${musicArtWidth("banner")}`;
    }
    return "";
}

function albumLandscapeUrl(album, artist) {
    const own = albumAssetUrl(album, "landscape");
    if (own) return own;
    const assets = resolvedArtistAssets(artist);
    if (assets.landscape && artist && artist.id) {
        return `/api/artists/${artist.id}/art/landscape?t=${artistArtStamp(artist)}&w=${musicArtWidth("landscape")}`;
    }
    return "";
}

function albumClearlogoUrl(album, artist) {
    const own = albumAssetUrl(album, "clearlogo");
    if (own) return own;
    const assets = resolvedArtistAssets(artist);
    if (assets.clearlogo && artist && artist.id) {
        return `/api/artists/${artist.id}/art/clearlogo?t=${artistArtStamp(artist)}&w=${musicArtWidth("clearlogo")}`;
    }
    return "";
}

function albumLengthLine(album) {
    const discs = Number(album.total_discs) || 1;
    const tracks = Number(album.total_tracks) || 0;
    const discLabel = discs === 1 ? "disc" : "discs";
    const trackLabel = tracks === 1 ? "track" : "tracks";
    return `${discs} ${discLabel} · ${tracks} ${trackLabel} · ${formatDuration(album.duration_seconds)}`;
}

function renderAlbum() {
    const summary = document.getElementById("album-summary");
    const tracks = document.getElementById("tracks");
    if (!state.album) {
        summary.innerHTML = "";
        tracks.innerHTML = `<div class="empty-state">Select an artist for the profile, or an album for the track matrix.</div>`;
        renderPreview(null);
        renderEditor();
        return;
    }
    const album = state.album.album;
    const artist = state.album.artist;
    const writable = libraryWritable(album.path);
    const showBadge = typeof artBadgeAllowed === "function" && artBadgeAllowed("music");
    const ratio = showBadge && album.artwork_width && album.artwork_height && typeof formatArtAspect === "function"
        ? formatArtAspect(album.artwork_width, album.artwork_height)
        : "";
    const dims = showBadge && album.artwork_width && album.artwork_height
        ? `${album.artwork_width}×${album.artwork_height}${ratio ? ` (${ratio})` : ""}`
        : "";
    const cover = album.has_artwork
        ? `<img src="/api/albums/${album.id}/cover?t=${coverStamp(album)}" alt=""${showBadge && !dims ? ` onload="updateArtBadgeOnLoad(this)"` : ""}>${dims ? `<span class="cover-badge">${escapeHtml(dims)}</span>` : (showBadge ? `<span class="art-dim-badge hidden"></span>` : "")}`
        : `<div class="art-fallback">No art</div>`;
    const posterBadges = album.has_artwork && typeof videoCfg === "function" && videoCfg().ui_music_poster_badges !== false && state.album && state.album.tracks && state.album.tracks.length
        ? fidelitySummary(state.album.tracks)
        : "";
    const albumGenres = album.genres == null ? ((artist && artist.genres) || []) : (album.genres || []);
    const genreRow = albumGenres.length
        ? `<div class="genre-row">${albumGenres.map((genre) => `<button type="button" class="tag-pill vlink-chip" data-action="music-filter-query" data-query="${escapeHtml(genre)}" title="Filter library by ${escapeHtml(genre)}">${escapeHtml(genre)}</button>`).join("")}</div>`
        : "";
    const proposal = state.proposal
        ? `<div class="proposal-box">
            <strong>Proposed match</strong>
            <div class="proposal-fields">
                <label>Album title<input id="proposal-title" value="${escapeHtml(state.proposal.album_title || "")}"></label>
                <label>Year<input id="proposal-year" value="${escapeHtml(state.proposal.year || "")}"></label>
                <label>Edition<input id="proposal-edition" value="${escapeHtml(state.proposal.edition || "")}"></label>
            </div>
            ${proposalFacts(state.proposal)}
            <p class="muted">${escapeHtml(releaseTypeLabel(state.proposal.releasetype || state.proposal.type) || "Release type unknown")}${suffixEnabled(state.proposal.type) ? " · this type is appended to the title" : ""}</p>
            <p class="muted">${state.proposal.unmatched_local || 0} local tracks unmatched · ${state.proposal.unmatched_remote || 0} online tracks without a file</p>
        </div>`
        : "";
    summary.innerHTML = `<div class="album-summary-card info-stack">
        ${infoBanner({
            banner: albumBannerUrl(album, artist),
            landscape: albumLandscapeUrl(album, artist),
            clearlogo: albumClearlogoUrl(album, artist),
        }, musicHeroActions("album", album, writable))}
        <div class="info-body">
            ${infoFanart(albumAssetUrl(album, "fanart"))}
            <div class="info-body-row">
        <div class="album-art-col info-cover">
        <div class="album-art-wrap">
        <button type="button" class="album-art-trigger${album.has_artwork ? " has-swap-bar" : ""}" ${album.has_artwork ? `data-action="zoom-album-cover" title="Enlarge artwork"` : `data-action="artwork" title="Swap artwork"`}>${cover}</button>
        ${posterBadges ? `<div class="poster-badges poster-badges-bottom">${posterBadges}</div>` : ""}
        ${album.has_artwork ? `<button type="button" class="art-swap-bar" data-action="artwork" title="Swap artwork" aria-label="Swap artwork">Swap${dims ? ` · ${escapeHtml(dims.replace(/\s*\(([^)]*)\)$/, " · $1"))}` : ""}</button>` : ""}
        </div>
        ${allmusicUserRating(album, state.proposal)}
        <div class="album-actions">
            <button type="button" data-action="match" ${state.busy ? "disabled" : ""}>Find metadata</button>
            <button type="button" data-action="download-missing-art" ${writable ? "" : "disabled"}>Download missing album artwork</button>
            <button type="button" data-action="apply" ${state.proposal && !state.busy && writable ? "" : "disabled"}>${state.busy && state.proposal ? "Applying…" : "Apply match"}</button>
            <button type="button" data-action="send-library-update" title="Ask each library to scan this artist. The rest of the music library is left alone." ${state.busy ? "disabled" : ""}>Send library update</button>
        </div>
        </div>
        <div class="album-meta-text info-copy">
            <div class="album-head">
            <div class="album-head-copy">
            <div class="album-name-line info-name">
                ${albumTitleCell(album)}
                <button type="button" class="icon-btn" data-action="edit-album-title" title="${state.albumTitleEditing && state.albumTitleId === album.id ? "Save album title" : "Edit album title"}" aria-label="${state.albumTitleEditing && state.albumTitleId === album.id ? "Save album title" : "Edit album title"}">${pencilIcon()}</button>
            </div>
            <p class="muted album-subline">${artist && artist.id ? `<button type="button" class="vlink-chip" data-open-artist="${escapeHtml(artist.id)}" title="Jump to artist ${escapeHtml(artist.name || "")}">${escapeHtml(artist.name || "")}</button>` : escapeHtml(artist ? artist.name : "")}${album.release_year ? ` · <button type="button" class="vlink-chip" data-action="music-filter-query" data-query="${escapeHtml(String(album.release_year))}" title="Filter library by ${escapeHtml(String(album.release_year))}">${escapeHtml(String(album.release_year))}</button>` : ""} · ${escapeHtml(albumLengthLine(album))}${albumRatingMarks(album)}</p>
            ${albumChips(album, state.album.tracks)}
            </div>
            ${albumLabelPane(album)}
            </div>
            ${albumReleaseLine(album)}
            ${genreRow}
            <p class="folder-line">Folder: ${escapeHtml(album.path || "")}${writable ? "" : " · read-only"}</p>
            <div class="album-tags-row">
                ${matchPill(album)}
                ${album.edition ? `<span class="tag-pill">${escapeHtml(album.edition)}</span>` : ""}
                <span class="tag-pill">${escapeHtml(releaseTypeLabel(album.type || "album"))}</span>
                ${album.upgrade ? `<button type="button" class="tag-pill upgrade-pill" data-action="show-upgrade">Upgrade available</button>` : ""}
                ${gapLabel(state.album.gap)}
                ${fidelitySummary(state.album.tracks)}
                ${countryPill(album.country || (state.proposal && state.proposal.country))}
            </div>
            <div class="action-row">
                <button type="button" class="btn-ghost" data-action="write-album-nfo" ${writable ? "" : "disabled"}>Write album.nfo</button>
                <button type="button" class="btn-ghost" data-action="artwork" data-subject="album">Swap thumb</button>
            </div>
            <div class="action-row">
                <button type="button" class="btn-ghost" data-action="cancel-proposal" ${state.proposal ? "" : "disabled"}>Clear match</button>
                <button type="button" class="btn-ghost" data-action="toggle-aligner" ${state.proposal ? "" : "disabled"}>${state.aligner ? "Track matrix" : "Align tracks"}</button>
                <button type="button" class="btn-ghost" data-action="compilation" ${writable ? "" : "disabled"}>Treat as compilation</button>
                <button type="button" class="btn-ghost" data-action="replaygain" ${writable ? "" : "disabled"}>ReplayGain</button>
                <button type="button" class="btn-ghost" data-action="audit">Audit audio</button>
                <button type="button" class="btn-ghost" data-action="check-gaps">Check missing tracks</button>
                ${album.cue_image ? `<button type="button" data-action="open-split">Split into tagged tracks</button>` : ""}
            </div>
        </div>
            </div>
        </div>
        ${albumReviewBlock(album)}
        ${proposal}
        ${gapList(state.album.gap)}
    </div>`;
    const albumTitleInput = document.getElementById("album-title-input");
    if (albumTitleInput) {
        albumTitleInput.addEventListener("input", () => { state.albumTitleDraft = albumTitleInput.value; });
        if (state.albumTitleFocus) {
            albumTitleInput.focus();
            albumTitleInput.select();
            state.albumTitleFocus = false;
        }
    }
    const reviewEditor = document.getElementById("review-editor");
    if (reviewEditor) reviewEditor.addEventListener("input", () => { state.reviewDraft = reviewEditor.value; });
    const titleInput = document.getElementById("proposal-title");
    if (titleInput) {
        titleInput.addEventListener("input", () => { state.proposal.album_title = titleInput.value; });
        document.getElementById("proposal-year").addEventListener("input", (event) => { state.proposal.year = event.target.value; });
        document.getElementById("proposal-edition").addEventListener("input", (event) => { state.proposal.edition = event.target.value; });
    }
    renderTracks();
}

function reviewChevron(collapsed) {
    const path = collapsed ? "M3.2 6.2 8 11l4.8-4.8" : "M3.2 9.8 8 5l4.8 4.8";
    return `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="${path}"/></svg>`;
}

function reviewToggleButton() {
    const collapsed = !!state.reviewCollapsed;
    const label = collapsed ? "Show review" : "Hide review";
    return `<button type="button" class="icon-btn" data-action="toggle-review" title="${label}" aria-label="${label}" aria-expanded="${collapsed ? "false" : "true"}">${reviewChevron(collapsed)}</button>`;
}

function toggleAlbumReview() {
    state.reviewCollapsed = !state.reviewCollapsed;
    localStorage.setItem("resonance.reviewCollapsed", state.reviewCollapsed ? "1" : "0");
    renderAlbum();
}

function albumReviewBlock(album) {
    const collapsed = !!state.reviewCollapsed;
    const editing = !collapsed && !!(state.reviewEditing && album && state.reviewAlbumId === album.id);
    const toggle = reviewToggleButton();
    if (editing) {
        return `<div class="album-review">
            <div class="bio-head"><h3>Review</h3>${toggle}</div>
            <textarea id="review-editor" class="bio-editor" rows="12">${escapeHtml(state.reviewDraft || "")}</textarea>
            <div class="action-row">
                <button type="button" data-action="save-review">Save</button>
                <button type="button" class="btn-ghost" data-action="cancel-review">Cancel</button>
            </div>
        </div>`;
    }
    const review = String((album && album.review) || "").trim();
    const bits = [album && album.style, album && album.mood, album && album.theme].map((item) => String(item || "").trim()).filter(Boolean);
    const facts = bits.length ? `<p class="muted">${bits.map((item) => item.split(/[;,]/).map((part) => part.trim()).filter(Boolean).map((part) => `<button type="button" class="vlink-chip" data-action="music-filter-query" data-query="${escapeHtml(part)}" title="Filter library by ${escapeHtml(part)}">${escapeHtml(part)}</button>`).join(", ")).join(" · ")}</p>` : "";
    const body = review ? `<p class="bio">${escapeHtml(review)}</p>` : `<p class="bio">No review stored yet.</p>`;
    const link = album.allmusic_url
        ? `<a href="${escapeHtml(album.allmusic_url)}" target="_blank" rel="noopener">AllMusic</a>`
        : "";
    return `<div class="album-review${collapsed ? " is-collapsed" : ""}">
        <div class="bio-head"><h3>Review</h3><button type="button" class="icon-btn" data-action="edit-review" title="Edit review" aria-label="Edit review">${pencilIcon()}</button><button type="button" class="btn-ghost" data-action="refresh-review">Refresh</button>${toggle}${link}</div>
        ${collapsed ? "" : `${facts}${body}`}
    </div>`;
}

function startReviewEdit() {
    const album = state.album && state.album.album;
    if (!album) return;
    state.reviewEditing = true;
    state.reviewAlbumId = album.id;
    state.reviewDraft = album.review || "";
    state.reviewCollapsed = false;
    localStorage.setItem("resonance.reviewCollapsed", "0");
    renderAlbum();
    const editor = document.getElementById("review-editor");
    if (editor) {
        editor.focus();
        editor.setSelectionRange(editor.value.length, editor.value.length);
    }
}

function cancelReviewEdit() {
    state.reviewEditing = false;
    state.reviewDraft = "";
    renderAlbum();
}

async function saveAlbumReview() {
    const album = state.album && state.album.album;
    if (!album) return;
    const editor = document.getElementById("review-editor");
    const text = editor ? editor.value : state.reviewDraft;
    const data = await api(`/api/albums/${album.id}/review`, {
        method: "POST",
        body: { save: true, manual: true, review: text },
    });
    state.reviewEditing = false;
    state.reviewDraft = "";
    if (state.album && state.album.album && state.album.album.id === album.id) {
        state.album = data;
        renderAlbum();
        renderEditor();
    }
    notify(data.review_message || "Album review saved.", "info");
}

function openReviewSearch() {
    const album = state.album && state.album.album;
    const artist = state.album && state.album.artist;
    if (!album) return;
    state.reviewChoices = [];
    const artistInput = document.getElementById("review-search-artist");
    const titleInput = document.getElementById("review-search-album");
    const artistName = (artist && artist.name) || "";
    const albumTitle = stripReleaseType(album.title || "");
    if (artistInput) artistInput.value = artistName;
    if (titleInput) titleInput.value = albumTitle;
    const body = document.getElementById("review-search-body");
    if (body) {
        body.innerHTML = `<p class="muted">A trailing (single), (EP), (live), (compilation), or (album) is left off the title. Change the names, then search. Pick the review to save.</p>`;
    }
    document.getElementById("review-search-modal").classList.remove("hidden");
    if (titleInput) titleInput.focus();
}

async function searchAlbumReviews() {
    const album = state.album && state.album.album;
    if (!album) throw new Error("Open an album first.");
    const artistInput = document.getElementById("review-search-artist");
    const titleInput = document.getElementById("review-search-album");
    const artist = artistInput ? artistInput.value.trim() : "";
    const title = titleInput ? titleInput.value.trim() : "";
    const body = document.getElementById("review-search-body");
    if (!artist && !title) throw new Error("Type an artist or an album title.");
    if (body) body.innerHTML = `<p class="muted">Searching…</p>`;
    const data = await api(`/api/albums/${album.id}/review`, { method: "POST", body: { search: true, artist, title } });
    if (artistInput && data.artist && artistInput.value.trim() === artist) artistInput.value = data.artist;
    if (titleInput && data.title && titleInput.value.trim() === title) titleInput.value = data.title;
    state.reviewChoices = data.choices || [];
    if (!body) return;
    body.innerHTML = state.reviewChoices.length
        ? state.reviewChoices.map((item, index) => reviewChoiceButton(item, index)).join("")
        : `<p>No review sources are turned on.</p>`;
}

function reviewChoiceButton(item, index) {
    const text = String((item && item.review) || "").trim();
    const note = item && item.note ? `<br><small>${escapeHtml(item.note)}</small>` : "";
    const label = escapeHtml((item && (item.label || item.source)) || "Source");
    if (!text) {
        return `<div class="candidate review-choice"><span class="candidate-copy"><strong>${label}</strong>${note}<br><small>No review for this search.</small></span></div>`;
    }
    return `<button type="button" class="candidate review-choice" data-action="pick-review" data-index="${index}">
        <span class="candidate-copy"><strong>${label}</strong>${note}<span class="review-choice-text">${escapeHtml(text)}</span></span>
    </button>`;
}

async function saveChosenReview(action) {
    const choice = (state.reviewChoices || [])[Number(action && action.dataset.index)];
    const album = state.album && state.album.album;
    if (!album) throw new Error("Open an album first.");
    if (!choice || !String(choice.review || "").trim()) throw new Error("That result has no review.");
    const data = await api(`/api/albums/${album.id}/review`, {
        method: "POST",
        body: { save: true, review: choice.review, source: choice.source || "", url: choice.url || "" },
    });
    document.getElementById("review-search-modal").classList.add("hidden");
    if (state.album && state.album.album && state.album.album.id === album.id) {
        state.album = data;
        renderAlbum();
        renderEditor();
    }
    notify(data.review_message || "Album review saved.", "info");
}

function kodiScore(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return "";
    const scaled = Math.min(number <= 5 ? number * 2 : number, 10);
    const rounded = Math.round(scaled * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

function ratingMark(file, label, text, title) {
    return `<span class="vrating-item" title="${escapeHtml(title || label)}"><img src="/media/providers/${file}" alt="${escapeHtml(label)}">${escapeHtml(text)}</span>`;
}

function albumRatingMarks(album) {
    const critic = album.allmusic_rating;
    const user = album.allmusic_user_rating;
    const hasCritic = critic != null && critic !== "";
    const hasUser = user != null && user !== "";
    const marks = [];
    if (hasCritic || hasUser) {
        const scores = [hasCritic ? String(critic) : "", hasUser ? String(user) : ""].filter(Boolean).join(" · ");
        const votes = Number(album.allmusic_votes);
        const voteText = votes > 0 ? ` · ${votes.toLocaleString()} votes` : "";
        const title = [
            hasCritic ? `AllMusic ${critic} / 5` : "",
            hasUser ? `users ${user} / 5` : "",
            votes > 0 ? `${votes.toLocaleString()} votes` : "",
        ].filter(Boolean).join(" · ");
        marks.push(ratingMark("allmusic.png", "AllMusic", `${scores}${voteText}`, title));
    }
    const kodi = kodiScore(critic);
    const kodiUser = kodiScore(user);
    if (kodi || kodiUser) {
        const scores = [kodi, kodiUser].filter(Boolean).join(" · ");
        const title = [kodi ? `Kodi ${kodi} / 10` : "", kodiUser ? `user ${kodiUser} / 10` : ""].filter(Boolean).join(" · ");
        marks.push(ratingMark("kodi.png", "Kodi", scores, title));
    }
    return marks.length ? `<span class="vratings album-ratings">${marks.join("")}</span>` : "";
}

function allmusicUserRating(album, proposal) {
    const value = album.allmusic_user_rating || (proposal && proposal.allmusic_user_rating);
    if (value == null || value === "") return "";
    const url = String((album.allmusic_url || (proposal && proposal.allmusic_url) || "")).trim();
    const label = `AllMusic users ${value} / 5`;
    const text = url
        ? `<a href="${escapeHtml(url)}#review" target="_blank" rel="noopener">${escapeHtml(label)}</a>`
        : escapeHtml(label);
    return `<p class="cover-user-rating">${text}</p>`;
}

function albumLabelPane(album) {
    const icons = (album && album.label_icons) || [];
    const marks = icons.filter((item) => item && item.src).map((item) => {
        const name = item.name || album.label || "Label";
        return `<img src="${escapeHtml(item.src)}" alt="${escapeHtml(name)}" title="${escapeHtml(name)}">`;
    }).join("");
    return marks ? `<div class="album-label-pane">${marks}</div>` : "";
}

function albumReleaseLine(album) {
    const label = String((album && album.label) || "").trim();
    const catalog = String((album && album.catalog) || "").trim();
    const bits = [];
    if (label) bits.push(`<span class="muted">Label</span> <button type="button" class="vlink-chip" data-action="music-filter-query" data-query="${escapeHtml(label)}" title="Filter library by ${escapeHtml(label)}">${escapeHtml(label)}</button>`);
    if (catalog) bits.push(`<span class="muted">Catalog</span> ${escapeHtml(catalog)}`);
    return bits.length ? `<p class="album-release-line">${bits.join(" · ")}</p>` : "";
}

function proposalFact(label, value) {
    const text = String(value ?? "").trim();
    if (!text) return "";
    return `<span><span class="muted">${escapeHtml(label)}</span> ${escapeHtml(text)}</span>`;
}

function proposalFacts(proposal) {
    const rows = proposal.expected && proposal.expected.length ? proposal.expected : (proposal.tracks || []);
    const seconds = rows.reduce((sum, track) => sum + (Number(track.duration_seconds) || 0), 0);
    const releaseId = String(proposal.release_id || "").trim();
    const groupId = String(proposal.release_group_id || "").trim();
    const release = releaseId
        ? `<span><span class="muted">MusicBrainz release</span> <a href="https://musicbrainz.org/release/${escapeHtml(releaseId)}" target="_blank" rel="noopener">${escapeHtml(releaseId)}</a></span>`
        : "";
    const group = groupId
        ? `<span><span class="muted">Release group</span> <a href="https://musicbrainz.org/release-group/${escapeHtml(groupId)}" target="_blank" rel="noopener">${escapeHtml(groupId)}</a></span>`
        : "";
    const facts = [
        release,
        group,
        proposalFact("Tracks", rows.length ? String(rows.length) : ""),
        proposalFact("Discs", proposal.totaldiscs),
        proposalFact("Duration", seconds ? formatDuration(seconds) : ""),
        proposalFact("Format", proposal.media),
        proposalFact("Country", countryLabel(proposal.country || proposal.releasecountry)),
        proposalFact("Status", proposal.releasestatus),
        proposalFact("Label", proposal.label),
        proposalFact("Catalog", proposal.catalognumber),
        proposalFact("Barcode", proposal.barcode),
        proposalFact("Released", proposal.date),
        proposalFact("Style", proposal.style),
        proposalFact("Mood", proposal.mood),
        proposalFact("Theme", proposal.theme),
        proposalFact("AllMusic", proposal.allmusic_rating ? `${proposal.allmusic_rating} / 5` : ""),
    ].filter(Boolean).join("");
    const allmusic = String(proposal.allmusic_url || "").trim();
    const link = allmusic
        ? `<span><span class="muted">AllMusic page</span> <a href="${escapeHtml(allmusic)}" target="_blank" rel="noopener">Open</a></span>`
        : "";
    const body = `${facts}${link}`;
    return body ? `<div class="proposal-facts">${body}</div>` : "";
}

function renderTracks() {
    const host = document.getElementById("tracks");
    if (!state.album || state.center !== "album") return;
    if (state.aligner && state.proposal) {
        renderAligner(host);
        renderPreview(currentTrack());
        syncPreviewControls();
        return;
    }
    const columns = trackColumns();
    const widths = columns.map((column) => columnWidth(column.key));
    const cols = columns.map((column, index) => `<col data-col="${escapeHtml(column.key)}" style="width:${widths[index]}px">`).join("");
    const head = columns.map((column) => `<th data-col="${escapeHtml(column.key)}"><span class="col-label">${escapeHtml(column.label)}</span><span class="col-resize" data-col="${escapeHtml(column.key)}" role="separator" aria-orientation="vertical" aria-label="Resize ${escapeHtml(column.label)}" title="Drag to resize. Double-click to reset."></span></th>`).join("");
    let body = "";
    let lastDisc = null;
    for (const track of state.album.tracks) {
        if ((state.album.album.total_discs || 1) > 1 && track.disc_number !== lastDisc) {
            lastDisc = track.disc_number;
            body += `<tr class="disc-row"><td colspan="${columns.length}">Disc ${track.disc_number}</td></tr>`;
        }
        const selected = state.trackIds.has(track.id) || track.id === state.trackId;
        const active = selected ? " class=\"active\"" : "";
        const cells = columns.map((column) => renderCell(column, track)).join("");
        const drag = state.proposal ? " draggable=\"true\"" : "";
        body += `<tr data-track="${escapeHtml(track.id)}"${active}${drag}>${cells}</tr>`;
    }
    const tableWidth = widths.reduce((sum, width) => sum + width, 0);
    host.innerHTML = state.album.tracks.length
        ? `<table class="track-table" style="width:${tableWidth}px"><colgroup>${cols}</colgroup><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
        : `<div class="empty-state">This album has no audio files.</div>`;
    bindColumnResize(host.querySelector(".track-table"));
    bindTrackDrag();
    renderPreview(currentTrack());
    syncPreviewControls();
}

function bindColumnResize(table) {
    if (!table) return;
    table.querySelectorAll(".col-resize").forEach((handle) => {
        handle.addEventListener("mousedown", (event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            const key = handle.dataset.col;
            const col = table.querySelector(`col[data-col="${key}"]`);
            const startX = event.clientX;
            const start = col ? parseFloat(col.style.width) || columnWidth(key) : columnWidth(key);
            document.body.classList.add("is-col-resize");
            const move = (ev) => {
                const width = Math.max(48, Math.min(720, Math.round(start + ev.clientX - startX)));
                state.columnWidths[key] = width;
                if (col) col.style.width = `${width}px`;
                syncTableWidth(table);
            };
            const up = () => {
                localStorage.setItem("resonance.columnWidths", JSON.stringify(state.columnWidths));
                document.body.classList.remove("is-col-resize");
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
            };
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
        });
        handle.addEventListener("dblclick", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const key = handle.dataset.col;
            delete state.columnWidths[key];
            localStorage.setItem("resonance.columnWidths", JSON.stringify(state.columnWidths));
            const col = table.querySelector(`col[data-col="${key}"]`);
            if (col) col.style.width = `${columnWidth(key)}px`;
            syncTableWidth(table);
        });
    });
}

function syncTableWidth(table) {
    const sum = [...table.querySelectorAll("col")].reduce((total, col) => total + (parseFloat(col.style.width) || 0), 0);
    table.style.width = `${Math.round(sum)}px`;
}

function trackColumns() {
    const tag = (track, key) => (track.tags || {})[key] || "";
    const columns = [];
    if (state.columns.disc) columns.push({ key: "disc", label: "Disc #", value: (track) => String(track.disc_number || 1) });
    if (state.columns.track) columns.push({ key: "num", label: "Track #", value: (track) => String(track.track_number).padStart(2, "0") });
    columns.push({ key: "title", label: "Title", html: (track) => `${escapeHtml(track.title || "")} ${trackBadges(track)}` });
    if (state.columns.albumArtist) columns.push({ key: "albumartist", label: "Album artist", value: (track) => tag(track, "albumartists") || tag(track, "albumartist") || "" });
    if (state.columns.artist) columns.push({ key: "artist", label: "Artists", value: (track) => tag(track, "artists") || track.artist_name || "" });
    if (state.columns.year) columns.push({ key: "year", label: "Year", value: (track) => track.year ? String(track.year) : "" });
    if (state.columns.duration) columns.push({ key: "duration", label: "Duration", value: (track) => formatDuration(track.duration_seconds) });
    if (state.columns.codec) columns.push({ key: "codec", label: "Codec", value: (track) => (track.file_format || "").toUpperCase() });
    if (state.columns.sampleRate) columns.push({ key: "rate", label: "Sample rate", value: (track) => formatRate(track.sample_rate) });
    if (state.columns.bitDepth) columns.push({ key: "depth", label: "Bit depth", value: (track) => track.bit_depth ? `${track.bit_depth}-bit` : "—" });
    if (state.columns.bitrate) columns.push({ key: "bitrate", label: "Bitrate", value: (track) => track.bitrate ? `${track.bitrate} kbps` : "—" });
    if (state.columns.acoustid) columns.push({ key: "acoustid", label: "AcoustID %", value: (track) => track.acoustid_score == null ? "—" : `${track.acoustid_score}%` });
    if (state.columns.lyrics) columns.push({ key: "lyrics", label: "Lyrics", value: (track) => lyricsLabel(track) });
    if (state.columns.bpmKey) columns.push({ key: "bpm", label: "BPM / key", value: (track) => [tag(track, "bpm"), tag(track, "initialkey")].filter(Boolean).join(" / ") || "—" });
    if (state.columns.replaygain) columns.push({ key: "rg", label: "ReplayGain", value: (track) => tag(track, "replaygain_track_gain") || "—" });
    if (state.columns.completeness) columns.push({ key: "score", label: "Complete", value: (track) => `${track.tag_completeness_percent || 0}%` });
    return columns;
}

function lyricsLabel(track) {
    if ((track.tags || {})._instrumental) return "instrumental";
    return track.lyrics_type && track.lyrics_type !== "none" ? track.lyrics_type : "—";
}

function renderColumnMenu() {
    const labels = {
        disc: "Disc #",
        track: "Track #",
        title: "Title",
        albumArtist: "Album artist",
        artist: "Artists",
        year: "Year",
        duration: "Duration",
        codec: "Codec",
        sampleRate: "Sample rate",
        bitDepth: "Bit depth",
        bitrate: "Bitrate",
        acoustid: "AcoustID %",
        lyrics: "Lyrics type",
        bpmKey: "BPM / musical key",
        replaygain: "ReplayGain",
        completeness: "Completeness %",
    };
    const boxes = Object.keys(COLUMN_DEFAULTS).map((key) =>
        `<label><input type="checkbox" data-column="${key}" ${state.columns[key] ? "checked" : ""} ${key === "title" ? "disabled" : ""}> ${labels[key]}</label>`
    ).join("");
    document.getElementById("column-menu").innerHTML = `${boxes}<p><button type="button" class="btn-ghost" data-action="reset-columns">Reset</button></p>`;
}

function resetColumns() {
    state.columns = { ...COLUMN_DEFAULTS };
    localStorage.setItem("resonance.columns", JSON.stringify(state.columns));
    renderColumnMenu();
    renderTracks();
}
