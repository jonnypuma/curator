// The window behind a show's Duplicate pill when another folder holds the same show.

state.twins = { id: "", shows: [], undo: null };

async function openTwinShows(id) {
    state.twins.id = id;
    state.twins.undo = null;
    document.getElementById("twin-modal").classList.remove("hidden");
    await loadTwinShows();
}

async function loadTwinShows() {
    const data = await api(`/api/v1/twin-shows/${encodeURIComponent(state.twins.id)}`);
    state.twins.shows = data.shows || [];
    renderTwinShows();
}

function renderTwinShows() {
    const shows = state.twins.shows;
    const first = shows[0] || {};
    const undo = state.twins.undo
        ? `<div class="ins-card ins-wide"><button type="button" class="btn-ghost" data-action="twin-undo">Undo not duplicates</button></div>`
        : "";
    const cards = shows.map((show) => {
        const ids = [show.tvdb_id && `TVDB ${show.tvdb_id}`, show.tmdb_id && `TMDB ${show.tmdb_id}`, show.imdb_id].filter(Boolean).join(" · ");
        return compareCardHtml({
            id: show.id,
            name: `${show.title || ""}${show.year ? ` (${show.year})` : ""}`,
            lines: [
                escapeHtml(`${Number(show.seasons) || 0} seasons · ${Number(show.episodes) || 0} episodes${Number(show.missing) ? ` · ${Number(show.missing)} missing` : ""} · ${fmtSize(show.size_bytes)}`),
                escapeHtml([show.resolutions || "Not read yet", ids].filter(Boolean).join(" · ")),
            ],
            path: show.path || "",
            del: `data-action="twin-delete" data-id="${escapeHtml(show.id)}"`,
            delTitle: "Delete this show folder from disk",
            remove: `data-action="twin-remove" data-id="${escapeHtml(show.id)}"`,
        });
    }).join("");
    const shared = shows.length > 1 ? compareSharedIds(first, shows[1], [["tvdb_id", "TheTVDB id"], ["tmdb_id", "TMDB id"], ["imdb_id", "IMDb id"]]) : [];
    const reason = shows.length > 1
        ? `Folders that hold one show: ${shared.length ? `the same ${shared.join(" and ")}` : "the same title and year"}, and the same name once a year or country in brackets is left out.`
        : "";
    const actions = compareDismissButtons(shows.map((show) => ({ ...show, label: show.path })),
        (left, right) => `data-action="twin-dismiss" data-left="${escapeHtml(left.id)}" data-right="${escapeHtml(right.id)}"`);
    document.getElementById("twin-list").innerHTML = undo + compareGroupHtml({ reason, cards, actions })
        + (shows.length > 1 ? "" : `<p class="muted">No other folder holds this show now.</p>`);
}

function applyTwinMarks(marks) {
    (marks || []).forEach((mark) => {
        const show = (state.video.shows || []).find((row) => row.id === mark.id);
        if (show) Object.assign(show, { duplicate_show: mark.duplicate_show, duplicate_release: mark.duplicate_release });
    });
    if (typeof renderVideoList === "function") renderVideoList();
}

async function dismissTwinShows(left, right) {
    const data = await api("/api/v1/twin-shows/dismiss", { method: "POST", body: { left_id: left, right_id: right } });
    state.twins.undo = { left, right };
    applyTwinMarks(data.shows);
    await loadTwinShows();
}

async function undoTwinShows() {
    const pair = state.twins.undo;
    if (!pair) return;
    const data = await api("/api/v1/twin-shows/restore", { method: "POST", body: { left_id: pair.left, right_id: pair.right } });
    state.twins.undo = null;
    applyTwinMarks(data.shows);
    await loadTwinShows();
}

function deleteTwinAsk(id) {
    const show = state.twins.shows.find((row) => row.id === id) || {};
    askDanger(`Delete ${show.title || "this show"} in this folder?`, show.path || "", "Delete from disk", async () => {
        const result = await api("/api/v1/delete", { method: "POST", body: { kind: "show", ids: [id] } });
        if ((result.errors || []).length) throw new Error(result.errors[0]);
        state.video.shows = (state.video.shows || []).filter((row) => row.id !== id);
        const left = state.twins.shows.find((row) => row.id !== id);
        if (!left) {
            document.getElementById("twin-modal").classList.add("hidden");
            if (typeof renderVideoList === "function") renderVideoList();
            return;
        }
        state.twins.id = left.id;
        await loadTwinShows();
        applyTwinMarks(state.twins.shows.map((row) => ({ id: row.id, duplicate_show: state.twins.shows.length - 1, duplicate_release: state.twins.shows.length > 1 })));
    }, true, null, true);
}

// The same for music: the window behind an artist's Duplicate pill.
state.twinArtists = { id: "", artists: [], undo: null };

async function openTwinArtists(id) {
    state.twinArtists.id = id;
    state.twinArtists.undo = null;
    document.getElementById("twin-artists-modal").classList.remove("hidden");
    await loadTwinArtists();
}

async function loadTwinArtists() {
    const data = await api(`/api/v1/twin-artists/${encodeURIComponent(state.twinArtists.id)}`);
    state.twinArtists.artists = data.artists || [];
    renderTwinArtists();
}

function renderTwinArtists() {
    const artists = state.twinArtists.artists;
    const first = artists[0] || {};
    const undo = state.twinArtists.undo
        ? `<div class="ins-card ins-wide"><button type="button" class="btn-ghost" data-action="twin-artists-undo">Undo not duplicates</button></div>`
        : "";
    const cards = artists.map((artist) => compareCardHtml({
        id: artist.id,
        name: artist.name || "",
        lines: [
            escapeHtml(`${Number(artist.albums) || 0} albums · ${Number(artist.tracks) || 0} tracks · ${Number(artist.size_bytes) ? formatBytes(Number(artist.size_bytes)) : "empty"}`),
            escapeHtml(artist.mbid ? `MusicBrainz ${artist.mbid}` : "No MusicBrainz id"),
        ],
        path: artist.path || "",
        remove: `data-action="twin-artists-remove" data-id="${escapeHtml(artist.id)}"`,
        extra: `<button type="button" class="btn-ghost" data-action="twin-artists-merge" data-id="${escapeHtml(artist.id)}">Merge…</button>`,
    })).join("");
    const shared = artists.length > 1 ? compareSharedIds(first, artists[1], [["mbid", "MusicBrainz artist id"]]) : [];
    const reason = artists.length > 1
        ? `Folders of one artist: ${shared.length ? "the same MusicBrainz artist id" : "the same name, ignoring capitals and punctuation"}. Merge moves the albums into one artist.`
        : "";
    const actions = compareDismissButtons(artists.map((artist) => ({ ...artist, label: artist.path })),
        (left, right) => `data-action="twin-artists-dismiss" data-left="${escapeHtml(left.id)}" data-right="${escapeHtml(right.id)}"`);
    document.getElementById("twin-artists-list").innerHTML = undo + compareGroupHtml({ reason, cards, actions })
        + (artists.length > 1 ? "" : `<p class="muted">No other folder holds this artist now.</p>`);
}

function applyTwinArtistMarks(marks) {
    (marks || []).forEach((mark) => {
        const artist = (state.artists || []).find((row) => row.id === mark.id);
        if (artist) Object.assign(artist, { duplicate: mark.duplicate, twin_count: mark.twin_count });
    });
    if (typeof renderTree === "function") renderTree();
}

async function dismissTwinArtists(left, right) {
    const data = await api("/api/v1/twin-artists/dismiss", { method: "POST", body: { left_id: left, right_id: right } });
    state.twinArtists.undo = { left, right };
    applyTwinArtistMarks(data.artists);
    await loadTwinArtists();
}

async function undoTwinArtists() {
    const pair = state.twinArtists.undo;
    if (!pair) return;
    const data = await api("/api/v1/twin-artists/restore", { method: "POST", body: { left_id: pair.left, right_id: pair.right } });
    state.twinArtists.undo = null;
    applyTwinArtistMarks(data.artists);
    await loadTwinArtists();
}

// The merge window of the artist page does the work: open that artist and its merge picker, which lists the twin first.
async function mergeTwinArtist(id) {
    document.getElementById("twin-artists-modal").classList.add("hidden");
    await selectArtist(id);
    openArtistPick();
}

// Remove from library (the files stay) for one show folder or one artist folder of a compare.
function removeTwinShowAsk(id) {
    const show = state.twins.shows.find((row) => row.id === id) || {};
    askDanger(`Remove ${show.title || "this show"} in this folder from the library?`, `${show.path || ""} The files stay on disk, and the next scan adds the show back.`,
        "Remove from library", async () => {
            const result = await api("/api/v1/remove", { method: "POST", body: { kind: "show", ids: [id] } });
            if ((result.errors || []).length) throw new Error(result.errors[0]);
            state.video.shows = (state.video.shows || []).filter((row) => row.id !== id);
            const left = state.twins.shows.find((row) => row.id !== id);
            if (!left) {
                document.getElementById("twin-modal").classList.add("hidden");
                if (typeof renderVideoList === "function") renderVideoList();
                return;
            }
            state.twins.id = left.id;
            await loadTwinShows();
        }, false);
}

function removeTwinArtistAsk(id) {
    const artist = state.twinArtists.artists.find((row) => row.id === id) || {};
    askDanger(`Remove ${artist.name || "this artist"} in this folder from the library?`, `${artist.path || ""} The files stay on disk, and the next scan adds the artist back.`,
        "Remove from library", async () => {
            await forgetLibrary({ artist_ids: [id] }, artist.name || "1 artist");
            const left = state.twinArtists.artists.find((row) => row.id !== id);
            if (!left) {
                document.getElementById("twin-artists-modal").classList.add("hidden");
                return;
            }
            state.twinArtists.id = left.id;
            await loadTwinArtists();
        }, false);
}

function onTwinAction(name, action) {
    if (name === "twin-artists") return runAction(() => openTwinArtists(action.dataset.id));
    if (name === "twin-artists-dismiss") return runAction(() => dismissTwinArtists(action.dataset.left, action.dataset.right));
    if (name === "twin-artists-undo") return runAction(undoTwinArtists);
    if (name === "twin-artists-merge") return runAction(() => mergeTwinArtist(action.dataset.id));
    if (name === "twin-dismiss") return runAction(() => dismissTwinShows(action.dataset.left, action.dataset.right));
    if (name === "twin-undo") return runAction(undoTwinShows);
    if (name === "twin-delete") return deleteTwinAsk(action.dataset.id);
    if (name === "twin-remove") return removeTwinShowAsk(action.dataset.id);
    if (name === "twin-artists-remove") return removeTwinArtistAsk(action.dataset.id);
    return false;
}
