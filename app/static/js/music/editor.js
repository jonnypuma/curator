function renderEditor() {
    const host = document.getElementById("editor");
    const diffHost = document.getElementById("editor-diff");
    const sideHost = document.getElementById("editor-sidecar");
    const card = document.getElementById("completeness-card");
    const badge = document.getElementById("active-track-badge");
    const chosen = selectedTracks();
    if (chosen.length > 1) {
        renderBulkEditor(chosen, host, diffHost, sideHost, card, badge);
        return;
    }
    const track = currentTrack();
    if (!track) {
        showTrackLocation(null);
        if (badge) badge.textContent = "";
        if (card) card.innerHTML = "";
        host.innerHTML = `<div class="empty-state">Select a track to inspect tags. Artist profile stays in the centre pane.</div>`;
        if (diffHost) {
            diffHost.innerHTML = `<div class="empty-state">Find metadata on an album to compare tags with MusicBrainz.</div>`;
            diffHost.classList.remove("has-diff");
        }
        const idleTab = document.querySelector("[data-inspector='diff']");
        if (idleTab) idleTab.classList.remove("has-diff");
        if (sideHost) sideHost.innerHTML = `<div class="empty-state">Sidecar files appear here after an album is open.</div>`;
        return;
    }
    const album = state.album.album;
    const artist = state.album.artist;
    const proposal = proposalFor(track.id);
    const percent = track.tag_completeness_percent || 0;
    const tone = percent >= 80 ? "" : percent >= 40 ? " warn" : " low";
    if (badge) badge.textContent = `Trk #${String(track.track_number || 0).padStart(2, "0")}`;
    if (card) {
        const checks = completenessChecks(track, album, artist).map(([label, ok]) =>
            `<div class="${ok ? "ok" : "bad"}">${ok ? "✓" : "–"} ${escapeHtml(label)}</div>`
        ).join("");
        card.innerHTML = `<div class="completeness-container"><span>Tag completeness ${percent}%</span><div class="progress-bar-bg"><div class="progress-bar-fill${tone}" style="width:${percent}%"></div></div><div class="check-grid">${checks}</div></div>`;
    }
    const wide = new Set(["title", "album_name", "genre", "comment", "musicbrainz_track_id", "musicbrainz_recordingid", "musicbrainz_release_group_id", "musicbrainz_albumid", "musicbrainz_artistid", "catalognumber", "barcode", "label", "asin"]);
    const fields = FIELDS.map(([key, label]) => {
        const current = embeddedDisplay(track, key);
        const proposed = proposal ? proposal[key] : null;
        const diff = proposal && String(proposed ?? "") !== String(current ?? "");
        const proposedInput = proposal
            ? `<input class="proposed${diff ? " is-diff" : ""}" data-proposed="${key}" value="${escapeHtml(proposed ?? "")}">`
            : "";
        return `<div class="input-group${wide.has(key) ? " span-2" : ""}"><label>${escapeHtml(label)}</label><div class="${proposal ? "diff-pair" : ""}"><input data-field="${key}" value="${escapeHtml(current ?? "")}">${proposedInput}</div></div>`;
    }).join("");
    const known = new Set(["title", "artist", "artists", "artistsort", "album", "albumartist", "albumartists", "albumartistsort", "genre", "year", "tracknumber", "discnumber", "composer", "conductor", "bpm", "initialkey", "replaygain_track_gain", "comment", "musicbrainz_trackid", "musicbrainz_recordingid", "musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_artistid", "catalognumber", "barcode", "label", "releasecountry", "releasestatus", "releasetype", "media", "asin"]);
    const extraLabels = {
        date: "Release date",
        originaldate: "Original date",
        isrc: "ISRC",
        totaltracks: "Total tracks",
        totaldiscs: "Total discs",
        musicbrainz_albumartistid: "MusicBrainz album artist ID",
        musicbrainz_originalalbumid: "MusicBrainz original album ID",
        musicbrainz_originalartistid: "MusicBrainz original artist ID",
        musicbrainz_discid: "MusicBrainz disc ID",
    };
    const extras = Object.entries(track.tags || {}).filter(([key]) => !known.has(key) && !key.startsWith("_")).map(([key, value]) => {
        const drafts = state.tagDrafts[track.id] || {};
        const shown = Object.prototype.hasOwnProperty.call(drafts, key) ? drafts[key] : value;
        return `<div class="input-group span-2"><label>${escapeHtml(extraLabels[key] || key)}</label><input data-extra="${escapeHtml(key)}" value="${escapeHtml(shown ?? "")}"></div>`;
    }).join("");
    const technical = [
        ["Codec", (track.file_format || "").toUpperCase()],
        ["Sample rate", formatRate(track.sample_rate)],
        ["Bit depth", track.bit_depth ? `${track.bit_depth}-bit` : "—"],
        ["Bitrate", track.bitrate ? `${track.bitrate} kbps` : "—"],
        ["Duration", formatDuration(track.duration_seconds)],
        ["AcoustID", track.acoustid_score == null ? "—" : `${track.acoustid_score}%`],
    ].map(([label, value]) => `<div><span class="muted">${escapeHtml(label)}</span><div class="mono">${escapeHtml(value)}</div></div>`).join("");
    showTrackLocation(track);
    host.innerHTML = `<div class="tech-grid">${technical}</div><div class="tag-grid">${fields}${extras}</div>`;
    host.querySelectorAll("[data-field], [data-extra]").forEach((input) => {
        input.addEventListener("input", () => stashTagInput(track, input));
    });
    if (diffHost) {
        diffHost.innerHTML = renderDiff(track, proposal);
        const changed = !!(proposal && diffHasChanges(track, proposal));
        diffHost.classList.toggle("has-diff", changed);
        const diffTab = document.querySelector("[data-inspector='diff']");
        if (diffTab) diffTab.classList.toggle("has-diff", changed);
    }
    if (sideHost) sideHost.innerHTML = renderSidecar(track, album, artist);
}

function stashTagInput(track, input) {
    const key = input.dataset.field || input.dataset.extra;
    const original = input.dataset.extra
        ? String((track.tags || {})[key] ?? "")
        : String(fieldValue(track, key) ?? "");
    if (!state.tagDrafts[track.id]) state.tagDrafts[track.id] = {};
    if (input.value === original) delete state.tagDrafts[track.id][key];
    else state.tagDrafts[track.id][key] = input.value;
    if (!Object.keys(state.tagDrafts[track.id]).length) delete state.tagDrafts[track.id];
    if (state.album) noteAlbumChanges(state.album.album.id, state.album.tracks);
}

function showTrackLocation(track) {
    const host = document.getElementById("track-location");
    if (!host) return;
    const path = track && track.file_path ? String(track.file_path) : "";
    if (!path) {
        host.classList.add("hidden");
        host.innerHTML = "";
        return;
    }
    host.classList.remove("hidden");
    host.innerHTML = `<strong>${escapeHtml(folderName(path))}</strong><span class="mono">${escapeHtml(path)}</span>`;
}

const DISCOG_GROUPS = [
    ["album", "Studio albums"],
    ["ep", "EPs"],
    ["single", "Singles"],
    ["compilation", "Compilations"],
    ["live", "Live"],
    ["unknown", "Other"],
];

function albumCard(album) {
    const group = album.musicbrainz_release_group_id || "";
    return `<button type="button" class="discog-card is-owned" data-action="jump-album" data-jump-album="${escapeHtml(album.id)}"
        data-discog-group="${escapeHtml(group)}" data-discog-album="${escapeHtml(album.id)}" data-discog-title="${escapeHtml(album.title || "")}" data-discog-year="${escapeHtml(album.release_year || "")}" data-discog-owned="1">
        <span class="discog-cover"><img src="/api/albums/${album.id}/cover?w=160" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'art-fallback', textContent:'No art'}))"></span>
        <strong>${escapeHtml(album.title)}</strong>
        <div class="muted">${escapeHtml(album.release_year || "")} ${matchIcon(album.match_tier)} ${album.match_ratio || 0}%</div>
    </button>`;
}

function discographyHtml(albums) {
    if (!albums.length) return `<p class="muted">No albums under this artist.</p>`;
    const buckets = new Map(DISCOG_GROUPS.map(([key]) => [key, []]));
    const extra = new Map();
    albums.forEach((album) => {
        const key = String(album.type || "album").toLowerCase();
        if (buckets.has(key)) buckets.get(key).push(album);
        else {
            if (!extra.has(key)) extra.set(key, []);
            extra.get(key).push(album);
        }
    });
    const sections = DISCOG_GROUPS
        .filter(([key]) => buckets.get(key).length)
        .map(([key, label]) => ({ label, rows: buckets.get(key) }));
    extra.forEach((rows, key) => {
        sections.push({ label: releaseTypeLabel(key) || "Other", rows });
    });
    return sections.map((section) => `<h4 class="section-label">${escapeHtml(section.label)} <span class="muted">${section.rows.length}</span></h4>
        <div class="discog">${section.rows.map(albumCard).join("")}</div>`).join("");
}

function releaseTypeLabel(value) {
    return String(value || "").split(/[;,]/).map((part) => {
        const text = part.trim();
        if (!text) return "";
        const lower = text.toLowerCase();
        if (lower === "unknown") return "Unknown";
        if (lower === "ep") return "EP";
        return text.charAt(0).toUpperCase() + text.slice(1);
    }).filter(Boolean).join(" · ");
}

function storedTag(track, key) {
    return String((track.tags || {})[key] || "").trim();
}

function completenessChecks(track, album, artist) {
    const group = track.musicbrainz_release_group_id || album.musicbrainz_release_group_id;
    const artOk = !!(album.has_artwork && (album.artwork_width || 0) >= 800 && (album.artwork_height || 0) >= 800);
    return [
        ["Title", !!track.title],
        ["Track number", (track.track_number || 0) >= 1],
        ["Disc number", (track.disc_number || 0) >= 1],
        ["Release year", track.year !== null && track.year !== undefined && track.year !== ""],
        ["Genre", !!track.genre],
        ["MusicBrainz track", !!track.musicbrainz_track_id],
        ["Release group", !!group],
        ["Release ID", !!(storedTag(track, "musicbrainz_albumid") || album.musicbrainz_release_id)],
        ["Catalog number", !!(storedTag(track, "catalognumber") || album.catalog)],
        ["Label", !!(storedTag(track, "label") || album.label)],
        ["Release country", !!(storedTag(track, "releasecountry") || album.country)],
        ["Release status", !!(storedTag(track, "releasestatus") || album.release_status)],
        ["Release type", !!storedTag(track, "releasetype")],
        ["Artist NFO", !!(artist && artist.has_nfo)],
        ["Album NFO", !!album.has_nfo],
        ["Art >= 800px", artOk],
    ];
}

function embeddedDisplay(track, key) {
    const drafts = state.tagDrafts[track.id];
    if (drafts && Object.prototype.hasOwnProperty.call(drafts, key)) return String(drafts[key] ?? "");
    return String(fieldValue(track, key) ?? "");
}

function diffHasChanges(track, proposal) {
    if (!track || !proposal) return false;
    return FIELDS.some(([key]) => embeddedDisplay(track, key) !== String(proposal[key] ?? ""));
}

function renderDiff(track, proposal) {
    if (!proposal) return `<div class="empty-state">Find metadata to compare this track with MusicBrainz. Proposed values show beside the current tags.</div>`;
    const rows = FIELDS.map(([key, label]) => {
        const current = embeddedDisplay(track, key);
        const proposed = String(proposal[key] ?? "");
        const changed = current !== proposed;
        const save = changed
            ? `<button type="button" class="diff-save" data-action="save-diff" data-diff-key="${escapeHtml(key)}" title="Save this tag">✓</button>`
            : "";
        return `<tr class="${changed ? "is-diff" : ""}"><td class="muted">${escapeHtml(label)}</td><td class="diff-value" data-diff-key="${escapeHtml(key)}" data-diff-side="embedded">${escapeHtml(current) || "—"}</td><td class="diff-value${changed ? " changed" : ""}" data-diff-key="${escapeHtml(key)}" data-diff-side="proposed">${escapeHtml(proposed) || "—"}</td><td>${save}</td></tr>`;
    }).join("");
    return `<table class="diff-table"><thead><tr><th>Field</th><th>Embedded</th><th>MusicBrainz</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

function musicLockPin(kind, itemId, key, lockedFields) {
    if (!kind || !itemId) return "";
    const isLocked = Array.isArray(lockedFields) && lockedFields.includes(key);
    const icon = typeof lockIcon === "function" ? lockIcon(isLocked) : (isLocked ? "🔒" : "🔓");
    const title = isLocked ? "Field locked against scans/scrapes. Click to unlock." : "Click to lock this field against scans/scrapes.";
    return `<button type="button" class="vfield-lock${isLocked ? " is-locked" : ""}" data-action="music-lock-field" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(itemId)}" data-field="${escapeHtml(key)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${icon}</button>`;
}

function nfoInput(key, label, value, wide, lockedFields, kind, itemId) {
    const pin = musicLockPin(kind, itemId, key, lockedFields);
    return `<div class="input-group${wide ? " span-2" : ""}"><label>${escapeHtml(label)}${pin}</label><input data-nfo="${key}" value="${escapeHtml(value ?? "")}"></div>`;
}

function genreEditor(genres) {
    const chips = (genres || []).map((genre) =>
        `<span class="genre-chip"><span data-genre="${escapeHtml(genre)}">${escapeHtml(genre)}</span><button type="button" class="genre-remove" data-action="remove-genre" aria-label="Remove ${escapeHtml(genre)}">×</button></span>`
    ).join("");
    return `<div class="genre-editor">${chips}</div><div class="genre-add"><input data-genre-input placeholder="Add a genre" aria-label="Add a genre"><button type="button" data-action="add-genre">Add</button></div>`;
}

function addGenreChip(form) {
    if (!form) return;
    const input = form.querySelector("[data-genre-input]");
    const name = input ? input.value.trim() : "";
    if (!name) return;
    if (/^\d+$/.test(name)) {
        notify("That number is an old ID3 genre code, not a genre name.", "warning");
        return;
    }
    const editor = form.querySelector(".genre-editor");
    if (!editor) return;
    const exists = [...editor.querySelectorAll("[data-genre]")].some((node) => (node.dataset.genre || "").toLowerCase() === name.toLowerCase());
    if (!exists) {
        const chip = document.createElement("span");
        chip.className = "genre-chip";
        chip.innerHTML = `<span data-genre="${escapeHtml(name)}">${escapeHtml(name)}</span><button type="button" class="genre-remove" data-action="remove-genre" aria-label="Remove ${escapeHtml(name)}">×</button>`;
        editor.appendChild(chip);
    }
    input.value = "";
}

function wireGenreInput(host) {
    const input = host.querySelector("[data-genre-input]");
    if (!input || input.dataset.wired === "1") return;
    input.dataset.wired = "1";
    input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        addGenreChip(host);
    });
}

function nfoFormValues(host) {
    const body = {};
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        body[input.dataset.nfo] = input.type === "checkbox" ? input.checked : input.value;
    });
    body.genres = [...host.querySelectorAll("[data-genre]")].map((node) => node.dataset.genre).filter(Boolean);
    return body;
}

function artistNfoStamp(artist) {
    const locked = Array.isArray(artist.locked_fields) ? artist.locked_fields : [];
    return `${artist.id}:${artist.updated_at || ""}:${locked.join(",")}`;
}

function albumNfoStamp(album) {
    const locked = Array.isArray(album.locked_fields) ? album.locked_fields : [];
    return `${album.id}:${album.updated_at || ""}:${locked.join(",")}`;
}

function renderArtistNfo() {
    const host = document.getElementById("editor-artist-nfo");
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!host) return;
    if (!artist) {
        host.innerHTML = `<div class="empty-state">Open an artist to edit artist.nfo.</div>`;
        host.dataset.stamp = "";
        return;
    }
    const locked = Array.isArray(artist.locked_fields) ? artist.locked_fields : [];
    const stamp = artistNfoStamp(artist);
    if (host.dataset.stamp === stamp) return;
    host.dataset.stamp = stamp;
    const f = (key, label, val, wide) => nfoInput(key, label, val, wide, locked, "artist", artist.id);
    host.innerHTML = `<form class="nfo-form" onsubmit="return false">
        <p class="muted">These fields are stored for the artist and written into artist.nfo. Biography stays in the centre. Numbers such as 0 or 17 are old ID3 genre codes and are left out when you save.</p>
        <div class="tag-grid">
            ${f("type", "Type", artist.type)}
            ${f("sortname", "Sort name", artist.sortname)}
            ${f("gender", "Gender", artist.gender)}
            ${f("disambiguation", "Disambiguation", artist.disambiguation, true)}
            ${f("formed", "Formed", artist.formed)}
            ${f("origin", "Born / origin", artist.origin)}
            ${f("years_active", "Years active", artist.years_active, true)}
            ${f("died", "Died", artist.died)}
            ${f("disbanded", "Disbanded", artist.disbanded)}
            ${f("website", "Website", artist.website, true)}
            ${f("discogs_url", "Discogs", artist.discogs_url, true)}
            ${f("wikipedia_url", "Wikipedia", artist.wikipedia_url, true)}
            ${f("style", "Style", artist.style, true)}
            ${f("mood", "Mood", artist.mood, true)}
            ${f("instruments", "Instruments", artist.instruments, true)}
            ${f("musicbrainz_artist_id", "MusicBrainz artist id", artist.musicbrainz_artist_id, true)}
        </div>
        <h3 class="section-label">Genres ${musicLockPin("artist", artist.id, "genres", locked)}</h3>
        ${genreEditor(artist.genres || [])}
    </form>`;
    wireGenreInput(host);
}

function renderAlbumNfo() {
    const host = document.getElementById("editor-album-nfo");
    const album = state.album && state.album.album;
    if (!host) return;
    if (!album) {
        host.innerHTML = `<div class="empty-state">Open an album to edit album.nfo.</div>`;
        host.dataset.stamp = "";
        return;
    }
    const locked = Array.isArray(album.locked_fields) ? album.locked_fields : [];
    const stamp = albumNfoStamp(album);
    if (host.dataset.stamp === stamp) return;
    host.dataset.stamp = stamp;
    const artist = state.album.artist;
    const ownGenres = album.genres;
    const genres = ownGenres == null ? ((artist && artist.genres) || []) : ownGenres;
    const types = ["album", "single", "ep", "compilation", "live", "unknown"].map((kind) =>
        `<option value="${kind}"${(album.type || "album") === kind ? " selected" : ""}>${escapeHtml(releaseTypeLabel(kind))}</option>`
    ).join("");
    const f = (key, label, val, wide) => nfoInput(key, label, val, wide, locked, "album", album.id);
    host.innerHTML = `<form class="nfo-form" onsubmit="return false">
        <p class="muted">These fields are stored for the album and written into album.nfo. Track tags stay on Embedded ID3. ${ownGenres == null ? "Genres start from the artist until you save this album." : ""}</p>
        <div class="tag-grid">
            ${f("title", "Title", album.title, true)}
            ${f("release_year", "Year", album.release_year)}
            <div class="input-group"><label>Type${musicLockPin("album", album.id, "type", locked)}</label><select data-nfo="type">${types}</select></div>
            ${f("release_status", "Release status", album.release_status)}
            ${f("label", "Label", album.label, true)}
            ${f("catalog", "Catalog number", album.catalog)}
            ${f("barcode", "Barcode", album.barcode)}
            ${f("country", "Country", album.country)}
            ${f("edition", "Edition", album.edition)}
            ${f("release_group", "Release group", album.release_group)}
            <div class="input-group"><label>Box set${musicLockPin("album", album.id, "boxset", locked)}</label><label class="check-line"><input type="checkbox" data-nfo="boxset"${album.boxset ? " checked" : ""}> This album is a box set</label></div>
            <div class="input-group span-2"><label>Review${musicLockPin("album", album.id, "review", locked)}</label><textarea data-nfo="review" rows="5">${escapeHtml(album.review || "")}</textarea></div>
            ${f("style", "Style", album.style, true)}
            ${f("mood", "Mood", album.mood)}
            ${f("theme", "Theme", album.theme)}
            ${f("allmusic_rating", "AllMusic rating", album.allmusic_rating)}
            ${f("allmusic_user_rating", "AllMusic user rating", album.allmusic_user_rating)}
            ${f("allmusic_votes", "AllMusic votes", album.allmusic_votes)}
            ${f("allmusic_url", "AllMusic", album.allmusic_url, true)}
            ${f("musicbrainz_release_id", "MusicBrainz release id", album.musicbrainz_release_id, true)}
            ${f("musicbrainz_release_group_id", "MusicBrainz release group id", album.musicbrainz_release_group_id, true)}
        </div>
        <p class="muted">${album.total_discs || 1} disc · ${formatDuration(album.duration_seconds)} · duration is taken from the tracks</p>
        <h3 class="section-label">Genres ${musicLockPin("album", album.id, "genres", locked)}</h3>
        ${genreEditor(genres)}
    </form>`;
    wireGenreInput(host);
}

async function toggleMusicFieldLock(action) {
    const kind = action.dataset.kind;
    const id = action.dataset.id;
    const field = action.dataset.field;
    if (!kind || !id || !field) return;
    const target = kind === "artist"
        ? (state.artistDetail && state.artistDetail.artist && state.artistDetail.artist.id === id ? state.artistDetail.artist : null)
        : (state.album && state.album.album && state.album.album.id === id ? state.album.album : null);
    const current = Array.isArray(target && target.locked_fields) ? target.locked_fields : [];
    const nextLocked = !current.includes(field);
    const data = await api("/api/library/lock-field", {
        method: "POST",
        body: { kind, id, field, locked: nextLocked },
    });
    const updatedFields = Array.isArray(data && data.locked_fields)
        ? data.locked_fields
        : (nextLocked ? [...current, field] : current.filter((item) => item !== field));
    if (target) target.locked_fields = updatedFields;
    const isNowLocked = updatedFields.includes(field);
    action.classList.toggle("is-locked", isNowLocked);
    action.innerHTML = lockIcon(isNowLocked);
    action.title = isNowLocked ? "Field locked — scrapes keep this value. Click to unlock." : "Click to lock this field from scrapes";
    const host = document.getElementById(kind === "artist" ? "editor-artist-nfo" : "editor-album-nfo");
    if (host && target) {
        host.dataset.stamp = kind === "artist" ? artistNfoStamp(target) : albumNfoStamp(target);
    }
    notify(`Field "${field}" ${isNowLocked ? "locked" : "unlocked"}.`, "info");
}

async function highlightAlbumNfoDiff() {
    const album = state.album && state.album.album;
    const host = document.getElementById("editor-album-nfo");
    if (!album || !host) return;
    let data;
    try {
        data = await api(`/api/albums/${album.id}/nfo`);
    } catch (error) {
        notify(error.message || "album.nfo could not be read.", "error");
        return;
    }
    const diff = data.diff || {};
    const fields = new Set(diff.fields || []);
    host.querySelectorAll(".nfo-file-diff").forEach((node) => node.classList.remove("nfo-file-diff"));
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        const group = input.closest(".input-group");
        if (!group || !fields.has(input.dataset.nfo)) return;
        group.classList.add("nfo-file-diff");
        const stored = diff.file && diff.file[input.dataset.nfo];
        group.title = stored ? `album.nfo has: ${stored}` : "album.nfo does not have this value";
    });
    const genres = host.querySelector(".genre-editor");
    if (genres && fields.has("genres")) {
        genres.classList.add("nfo-file-diff");
        const stored = diff.file && diff.file.genres;
        genres.title = stored ? `album.nfo has: ${stored}` : "album.nfo does not have these genres";
    }
    const form = host.querySelector("form");
    if (!form) return;
    let note = form.querySelector(".nfo-diff-note");
    if (!note) {
        note = document.createElement("p");
        note.className = "nfo-diff-note";
        form.prepend(note);
    }
    const changes = diff.changes || [];
    note.textContent = changes.length
        ? changes.map((row) => `${row.label}: album.nfo “${nfoBlank(row.file, "not in the file")}”, database “${nfoBlank(row.database, "not in the database")}”`).join(" ")
        : "album.nfo matches the fields shown here.";
}

async function clearArtistNfo() {
    const host = document.getElementById("editor-artist-nfo");
    if (!host) return;
    host.querySelectorAll("[data-nfo]").forEach((input) => {
        if (input.type === "checkbox") input.checked = false;
        else input.value = "";
    });
    const editor = host.querySelector(".genre-editor");
    if (editor) editor.innerHTML = "";
    await saveArtistProfile("Artist info cleared.");
}

async function saveArtistProfile(doneMessage) {
    const host = document.getElementById("editor-artist-nfo");
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!host || !artist) return;
    const fields = nfoFormValues(host);
    const previousMbid = String(artist.musicbrainz_artist_id || "");
    let data;
    try {
        data = await api(`/api/artists/${artist.id}/profile`, { method: "POST", body: fields });
    } catch (error) {
        if (error.body && error.body.conflict === "musicbrainz_artist_id") {
            openArtistMerge(error.body, fields);
            return;
        }
        throw error;
    }
    state.artistDetail = data;
    host.dataset.stamp = "";
    const nextMbid = String((data.artist && data.artist.musicbrainz_artist_id) || "");
    if (previousMbid !== nextMbid) {
        state.discography = null;
        state.discographyArtist = "";
    }
    renderTree();
    renderArtist();
    renderArtistNfo();
    if (previousMbid !== nextMbid) await loadDiscography(artist.id);
    if (data.nfo_warning) notify(`${doneMessage || "Artist info saved."} artist.nfo was not written: ${data.nfo_warning}`, "warning");
    else notify(doneMessage || "Artist info saved and artist.nfo updated.", "info");
}

function artistAliasLine(artist) {
    const folders = (artist && artist.folder_aliases) || [];
    if (!folders.length) return "";
    return `<p class="muted">Also indexed from ${folders.map((path) => escapeHtml(path)).join(", ")}</p>`;
}

function openArtistPick() {
    const artist = state.artistDetail && state.artistDetail.artist;
    if (!artist) return;
    state.artistPickId = artist.id;
    state.artistPickResults = [];
    const input = document.getElementById("artist-pick-query");
    const results = document.getElementById("artist-pick-results");
    if (input) input.value = artist.name || "";
    if (results) results.innerHTML = "";
    const source = document.getElementById("artist-pick-source");
    if (source) {
        const albums = (state.artistDetail.albums || []).length;
        source.innerHTML = `<span class="muted">This artist</span>
            <strong>${escapeHtml(artist.name || "Artist")}</strong>
            <span class="muted">${albums} album${albums === 1 ? "" : "s"}${artist.musicbrainz_artist_id ? " · MusicBrainz id" : ""}</span>
            <span class="mono">${escapeHtml(artist.path || "")}</span>`;
    }
    document.getElementById("artist-pick-modal").classList.remove("hidden");
    if (input) {
        input.focus();
        input.select();
    }
    queueArtistPick();
}

function queueArtistPick() {
    clearTimeout(state.artistPickTimer);
    state.artistPickTimer = setTimeout(runArtistPick, 200);
}

async function runArtistPick() {
    const artistId = state.artistPickId;
    const input = document.getElementById("artist-pick-query");
    const results = document.getElementById("artist-pick-results");
    if (!artistId || !input || !results) return;
    const query = input.value.trim();
    if (!query) {
        state.artistPickResults = [];
        results.innerHTML = `<p class="muted">Type a name or part of a folder path.</p>`;
        return;
    }
    try {
        const data = await api(`/api/artists/${artistId}/candidates?q=${encodeURIComponent(query)}`);
        if (state.artistPickId !== artistId || input.value.trim() !== query) return;
        state.artistPickResults = data.artists || [];
        if (!state.artistPickResults.length) {
            results.innerHTML = `<p class="muted">No other artist matches.</p>`;
            return;
        }
        results.innerHTML = state.artistPickResults.map((row) => {
            const count = Number(row.album_count) || 0;
            return `<button type="button" class="pick-result" data-action="pick-merge-artist" data-id="${escapeHtml(row.id)}">
                <strong>${escapeHtml(row.name || "Artist")}</strong>
                <span class="muted">${count} album${count === 1 ? "" : "s"}${row.has_mbid ? " · MusicBrainz id" : ""}</span>
                <span class="mono">${escapeHtml(row.path || "")}</span>
            </button>`;
        }).join("");
    } catch (error) {
        results.innerHTML = `<p class="muted">${escapeHtml(error.message || "Search failed.")}</p>`;
    }
}

function chooseMergeArtist(id) {
    const artist = state.artistDetail && state.artistDetail.artist;
    const other = (state.artistPickResults || []).find((row) => row.id === id);
    if (!artist || !other) return;
    document.getElementById("artist-pick-modal").classList.add("hidden");
    const albums = (state.artistDetail.albums || []).length;
    openArtistMerge({
        current: {
            id: artist.id,
            name: artist.name,
            path: artist.path,
            album_count: albums,
            has_mbid: !!artist.musicbrainz_artist_id,
        },
        other,
    }, null, { keepFolders: true });
}

function openArtistMerge(body, fields, options) {
    const keepFolders = !!(options && options.keepFolders);
    state.artistMerge = {
        current: body.current || {},
        other: body.other || {},
        fields: fields || null,
        keepFolders,
        conflicts: [],
    };
    showMergeError("");
    const conflicts = document.getElementById("artist-merge-conflicts");
    if (conflicts) conflicts.innerHTML = "";
    const current = state.artistMerge.current;
    const other = state.artistMerge.other;
    const master = mergeMaster(current, other);
    state.artistMerge.keepId = master;
    const text = document.getElementById("artist-merge-text");
    const note = document.getElementById("artist-merge-note");
    const choices = document.getElementById("artist-merge-choices");
    if (text) {
        text.textContent = keepFolders
            ? "Choose which artist stays in the library. Albums from both folders are listed under that artist."
            : "That MusicBrainz artist id is already used by another artist. Choose which artist stays. Its albums stay put. The other artist's album folders move under it, and that artist entry is removed.";
    }
    if (note) {
        const bothIds = keepFolders && current.has_mbid && other.has_mbid
            ? " Each entry has its own MusicBrainz id. The one you leave unselected loses that id."
            : "";
        note.textContent = keepFolders
            ? `Neither folder is renamed or moved. The other library entry is removed. The next scan keeps both folders on the artist you choose.${bothIds}`
            : "The artist you leave unselected is removed from the library after its album folders move. A leftover artist folder on disk, such as one that still has artist.nfo, can show up again on the next scan.";
    }
    if (choices) {
        choices.innerHTML = [other, current].filter((row) => row && row.id).map((row) => {
            const count = Number(row.album_count) || 0;
            const bits = [
                row.has_mbid ? "Has a MusicBrainz id" : "No MusicBrainz id yet",
                `${count} album${count === 1 ? "" : "s"}`,
            ];
            const folder = row.path ? `<span class="mono">${escapeHtml(row.path)}</span>` : "";
            return `<label class="choice pick-choice"><input type="radio" name="artist-merge-master" value="${escapeHtml(row.id)}" ${row.id === master ? "checked" : ""}> <span><strong>${escapeHtml(row.name || "Artist")}</strong> <span class="muted">${bits.join(" · ")}</span>${folder}</span></label>`;
        }).join("");
    }
    paintMergeOptions(keepFolders);
    paintMergeButton();
    refreshMergeNote();
    document.getElementById("artist-merge-modal").classList.remove("hidden");
}

function keptMergeArtist() {
    const pending = state.artistMerge;
    if (!pending) return null;
    const chosen = document.querySelector("input[name='artist-merge-master']:checked");
    const keepId = chosen ? chosen.value : pending.keepId;
    const current = pending.current || {};
    const other = pending.other || {};
    if (keepId && String(keepId) === String(other.id)) return other;
    return current;
}

function paintMergeButton() {
    const button = document.getElementById("artist-merge-confirm");
    const keep = keptMergeArtist();
    if (!button) return;
    const path = keep && keep.path ? keep.path : "";
    button.textContent = path ? `Merge ${path}` : "Merge";
}

function paintMergeOptions(keepFolders) {
    const host = document.getElementById("artist-merge-options");
    if (!host) return;
    const move = keepFolders
        ? `<label class="choice"><input type="checkbox" id="artist-merge-move"> <span>Move album folders into the artist you keep</span></label>`
        : "";
    host.innerHTML = `${move}<label class="choice"><input type="checkbox" id="artist-merge-remove"> <span>Delete the other artist folder when no audio files are left</span></label>`;
}

function refreshMergeNote() {
    const pending = state.artistMerge;
    const note = document.getElementById("artist-merge-note");
    if (!pending || !note) return;
    const token = (state.mergePreviewToken || 0) + 1;
    state.mergePreviewToken = token;
    window.clearTimeout(state.mergePreviewTimer);
    paintMergeButton();
    state.mergePreviewTimer = window.setTimeout(() => loadMergePreview(token), 120);
}

async function loadMergePreview(token) {
    const pending = state.artistMerge;
    const note = document.getElementById("artist-merge-note");
    if (!pending || !note || token !== state.mergePreviewToken) return;
    const chosen = document.querySelector("input[name='artist-merge-master']:checked");
    const keepId = chosen ? chosen.value : pending.keepId;
    const current = pending.current || {};
    const other = pending.other || {};
    const currentId = current.id;
    const otherId = other.id;
    const dropId = keepId === currentId ? otherId : currentId;
    const moveBox = document.getElementById("artist-merge-move");
    const removeBox = document.getElementById("artist-merge-remove");
    const moveFolders = pending.keepFolders ? !!(moveBox && moveBox.checked) : true;
    const bothIds = pending.keepFolders && current.has_mbid && other.has_mbid
        ? " Each entry has its own MusicBrainz id. The one you leave unselected loses that id."
        : "";
    if (!currentId || !dropId) return;
    try {
        const data = await api(`/api/artists/${currentId}/merge-preview`, {
            method: "POST",
            body: {
                keep_id: keepId,
                drop_id: dropId,
                move_folders: moveFolders,
                remove_empty: !!(removeBox && removeBox.checked),
            },
        });
        if (token !== state.mergePreviewToken) return;
        const lines = (data.lines || []).filter(Boolean);
        note.textContent = `${lines.join(" ")} File tags stay as they are.${bothIds}`;
        paintMergeConflicts(data.conflicts || []);
    } catch (error) {
        if (token !== state.mergePreviewToken) return;
        note.textContent = error.message || "The folder preview could not be loaded.";
        showMergeError(error.message || "The folder preview could not be loaded.");
    }
}

function showMergeError(message) {
    const node = document.getElementById("artist-merge-error");
    if (!node) return;
    const text = String(message || "").trim();
    node.textContent = text;
    node.classList.toggle("hidden", !text);
}

function mergeFolderChoices() {
    const choices = {};
    document.querySelectorAll("#artist-merge-conflicts input[type='radio']:checked").forEach((input) => {
        const name = String(input.name || "");
        if (!name.startsWith("merge-folder-")) return;
        choices[name.slice("merge-folder-".length)] = input.value;
    });
    return choices;
}

function mergeChoiceError() {
    const conflicts = (state.artistMerge && state.artistMerge.conflicts) || [];
    const choices = mergeFolderChoices();
    const missing = conflicts.find((conflict) => !choices[conflict.album_id]);
    if (!missing) return "";
    return missing.message || "Choose which copy to keep, or keep both.";
}

function paintMergeConflicts(conflicts) {
    const host = document.getElementById("artist-merge-conflicts");
    const pending = state.artistMerge;
    if (!host || !pending) return;
    const previous = mergeFolderChoices();
    pending.conflicts = conflicts || [];
    if (!pending.conflicts.length) {
        host.innerHTML = "";
        return;
    }
    host.innerHTML = pending.conflicts.map((conflict) => {
        const id = escapeHtml(conflict.album_id || "");
        const replace = conflict.existing_album_id
            ? `<label class="choice"><input type="radio" name="merge-folder-${id}" value="keep-incoming"> <span>Keep the incoming copy and delete the folder already in this artist</span></label>`
            : `<p class="muted">That folder is not an album in the library, so it cannot be deleted from here. Keep both copies, or turn off moving folders.</p>`;
        return `<div class="merge-conflict">
            <p class="merge-alert">${escapeHtml(conflict.message || "")}</p>
            <p class="muted mono">Incoming: ${escapeHtml(conflict.source || "")}</p>
            <p class="muted mono">Already here: ${escapeHtml(conflict.dest || "")}</p>
            <label class="choice"><input type="radio" name="merge-folder-${id}" value="both"> <span>Keep both copies. The incoming folder will be named ${escapeHtml(conflict.duplicate_name || "")}</span></label>
            <label class="choice"><input type="radio" name="merge-folder-${id}" value="keep-existing"> <span>Keep the copy already in this artist and delete the incoming folder</span></label>
            ${replace}
        </div>`;
    }).join("");
    Object.entries(previous).forEach(([id, value]) => {
        const input = host.querySelector(`input[name="merge-folder-${CSS.escape(id)}"][value="${CSS.escape(value)}"]`);
        if (input) input.checked = true;
    });
}

function showUndoArtwork(undo) {
    const button = document.getElementById("undo-artwork");
    if (!button) return;
    const ready = !!(undo && undo.asset_type);
    button.classList.toggle("hidden", !ready);
    button.textContent = ready ? `Undo ${assetLabel(undo.asset_type)}` : "Undo last artwork";
}

async function undoArtwork() {
    const target = state.artworkTarget || {};
    const artistMode = target.subject === "artist";
    const id = artistMode ? target.artistId : (target.albumId || (state.album && state.album.album.id));
    if (!id) return;
    await api(`/api/${artistMode ? "artists" : "albums"}/${id}/artwork/undo`, { method: "POST", body: {} });
    notify("Previous artwork restored.", "info");
    await refreshArtworkModal();
    if (artistMode && state.artistId) await selectArtist(state.artistId);
    else if (state.album) await selectAlbum(state.album.album.id, true);
}

function mergeMaster(current, other) {
    if (other.has_mbid && !current.has_mbid) return other.id;
    if (current.has_mbid && !other.has_mbid) return current.id;
    if ((Number(other.album_count) || 0) > (Number(current.album_count) || 0)) return other.id;
    return current.id;
}

async function confirmArtistMerge() {
    const pending = state.artistMerge;
    if (!pending) return;
    const chosen = document.querySelector("input[name='artist-merge-master']:checked");
    const keepId = chosen ? chosen.value : pending.keepId;
    const currentId = pending.current && pending.current.id;
    const otherId = pending.other && pending.other.id;
    const dropId = keepId === currentId ? otherId : currentId;
    const moveBox = document.getElementById("artist-merge-move");
    const removeBox = document.getElementById("artist-merge-remove");
    const moveFolders = pending.keepFolders ? !!(moveBox && moveBox.checked) : true;
    showMergeError("");
    let data;
    try {
        data = await api(`/api/artists/${currentId}/merge`, {
            method: "POST",
            body: {
                keep_id: keepId,
                drop_id: dropId,
                move_folders: moveFolders,
                remove_empty: !!(removeBox && removeBox.checked),
                folder_choices: mergeFolderChoices(),
            },
        });
    } catch (error) {
        const message = error.message || "The artists could not be merged.";
        showMergeError(message);
        notify(message, "error");
        return;
    }
    document.getElementById("artist-merge-modal").classList.add("hidden");
    state.artistMerge = null;
    if (keepId === currentId && pending.fields && Object.keys(pending.fields).length) {
        const saved = await api(`/api/artists/${keepId}/profile`, { method: "POST", body: pending.fields });
        state.artistId = keepId;
        state.artistDetail = saved;
    } else {
        state.artistId = keepId;
        state.artistDetail = data;
    }
    await loadLibrary();
    await selectArtist(keepId);
    const warnings = (data.merge_warnings || []).filter(Boolean);
    if (warnings.length) notify(`Artists merged. ${warnings[0]}`, "warning");
    else notify("Artists merged. The master kept its saved info.", "info");
}

async function writeAlbumNfo() {
    const album = state.album && state.album.album;
    if (!album) return;
    const data = await api(`/api/albums/${album.id}/nfo`, { method: "POST", body: {} });
    state.album = data;
    if (data.album) applyAlbumNfoStale(data.album.id, data.album.nfo_stale);
    renderTree();
    renderAlbum();
    renderAlbumNfo();
    renderEditor();
    notify("album.nfo written.", "info");
}

async function refreshLiveArtwork() {
    try {
        if (state.center === "album" && state.album && state.album.album) {
            const id = state.album.album.id;
            const before = `${state.album.album.updated_at || ""}|${state.album.album.has_artwork ? 1 : 0}|${state.album.album.artwork_width || 0}`;
            const data = await api(`/api/albums/${id}`);
            if (!state.album || !state.album.album || state.album.album.id !== id) return;
            const after = `${data.album.updated_at || ""}|${data.album.has_artwork ? 1 : 0}|${data.album.artwork_width || 0}`;
            if (after === before) return;
            const trackId = state.trackId;
            state.album = data;
            state.trackId = trackId;
            renderAlbum();
            renderEditor();
            return;
        }
        if (state.center === "artist" && state.artistId && state.artistDetail && state.artistDetail.artist) {
            const id = state.artistId;
            const before = state.artistDetail.artist.updated_at || "";
            const data = await api(`/api/artists/${id}`);
            if (state.artistId !== id || !data.artist) return;
            if ((data.artist.updated_at || "") === before) return;
            state.artistDetail = data;
            renderArtist();
        }
    } catch (error) {
        return;
    }
}

async function saveAlbumProfile() {
    const host = document.getElementById("editor-album-nfo");
    const album = state.album && state.album.album;
    if (!host || !album) return;
    const data = await api(`/api/albums/${album.id}/profile`, { method: "POST", body: nfoFormValues(host) });
    state.album = data;
    if (data.album && !data.nfo_warning) applyAlbumNfoStale(data.album.id, data.album.nfo_stale);
    host.dataset.stamp = "";
    renderTree();
    renderAlbum();
    renderAlbumNfo();
    renderEditor();
    if (data.nfo_warning) notify(`Album info saved. album.nfo was not written: ${data.nfo_warning}`, "warning");
    else notify("Album info saved and album.nfo updated.", "info");
}
