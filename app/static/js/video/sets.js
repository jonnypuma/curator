const SET_QUICK = new Set(["new", "missing", "noart"]);

function setHasArt(set, kind) {
    const art = set && set.artwork;
    if (!art) return false;
    if (Array.isArray(art)) return art.includes(kind);
    return !!art[kind];
}

const SET_RIBBONS = [
    ["new", "New", (set) => !!set.has_new],
    ["missing", "Movies missing", (set) => Number(set.missing_count) > 0],
    ["noart", "Artwork missing", (set) => !setHasArt(set, "poster") || !setHasArt(set, "fanart")],
    ["noscrape", "Not scraped", (set) => !set.scraped_at],
    ["scrapefail", "Scrape failed", (set) => !!set.scrape_error],
    ["nonfo", "No NFO", (set) => !set.nfo_path],
    ["nfo", "NFO changes", (set) => !!set.nfo_stale],
    ["unmatched", "Unmatched", (set) => !set.tmdb_collection_id],
    ["locked", "Locked", (set) => !!set.locked],
];

function visibleSets() {
    const match = textMatcher(state.video.filter.sets);
    const ribbons = SET_RIBBONS.filter(([key]) => libraryRibbons().has(key));
    const sort = (state.video && state.video.setSort) || { key: "name", dir: "asc" };
    const dir = sort.dir === "desc" ? -1 : 1;
    return (state.video.sets || []).filter((set) => {
        const text = `${set.name || ""} ${set.first_year || ""} ${set.last_year || ""}`.toLowerCase();
        return (!match || match(text)) && ribbons.every(([, , test]) => test(set));
    }).sort((a, b) => {
        if (sort.key === "year") {
            const byYear = ((Number(a.first_year) || 0) - (Number(b.first_year) || 0)) * dir;
            if (byYear) return byYear;
        } else if (sort.key === "movies") {
            const byCount = ((Number(a.movie_count) || 0) - (Number(b.movie_count) || 0)) * dir;
            if (byCount) return byCount;
        }
        return librarySortName(a.name).localeCompare(librarySortName(b.name), undefined, { sensitivity: "base" }) * dir;
    });
}

function setSortMark(key) {
    const sort = (state.video && state.video.setSort) || { key: "name", dir: "asc" };
    if (sort.key !== key) return "";
    return sort.dir === "desc" ? " ↓" : " ↑";
}

function renderSetList() {
    const host = document.getElementById("video-list");
    document.getElementById("video-ribbons").innerHTML = ribbonBarHtml(SET_RIBBONS, state.video.sets || [], SET_QUICK);
    state.video.rows = visibleSets();
    const rows = state.video.rows;
    const all = state.video.sets || [];
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") {
        renderVideoPosterGrid(rows, "set");
        renderVideoCounts(all.length ? `${rows.length} of ${all.length} sets` : "No sets yet");
        if (typeof paintVideoSelection === "function") paintVideoSelection();
        return;
    }
    const checked = rows.length > 0 && rows.every((set) => selectionHas("set", set.id));
    host.innerHTML = `<div class="vlist">
        <div class="vl-head">
            <label class="vl-check"><input type="checkbox" data-action="video-check-all" ${checked ? "checked" : ""} title="Select the sets on screen" aria-label="Select the sets on screen"></label>
            <button type="button" class="vm-sort" data-action="video-sort" data-col="name">Set${setSortMark("name")}</button>
            <span class="vl-meta">
                <button type="button" class="vm-sort" data-action="video-sort" data-col="year">Years${setSortMark("year")}</button>
                ·
                <button type="button" class="vm-sort" data-action="video-sort" data-col="movies">Movies${setSortMark("movies")}</button>
            </span>
        </div>
        <div class="vwin-rows"></div>
    </div>`;
    state.video.paintToken += 1;
    paintSetRows();
    renderVideoCounts(all.length ? `${state.video.rows.length} of ${all.length} sets` : "No sets yet");
    if (typeof paintVideoSelection === "function") paintVideoSelection();
    if (!all.length) {
        host.innerHTML = `<p class="muted vpad">Sets come from the &lt;set&gt; tag in movie .nfo files and from TMDB collections when movies are scraped. Scan or scrape the movie folders to fill this list.</p>`;
    }
}

function setRowHtml(set, index) {
    const years = set.first_year ? (set.last_year && set.last_year !== set.first_year ? `${set.first_year}–${set.last_year}` : `${set.first_year}`) : "";
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    const processedHtml = cfg.ui_set_processed !== false ? (set.status === "PROCESSED" ? `<span class="process-mark ok" title="Processed">✓</span>` : `<span class="process-mark bad" title="Not processed">✕</span>`) : "";
    return `<div class="vl-row${set.id === state.video.setId ? " is-selected" : ""}" style="top:${index * VIDEO_ROW}px" data-action="video-open-set" data-id="${escapeHtml(set.id)}">
        <label class="vl-check"><input type="checkbox" data-action="video-check" data-kind="set" data-id="${escapeHtml(set.id)}" ${selectionHas("set", set.id) ? "checked" : ""} aria-label="Select ${escapeHtml(set.name || "set")}"></label>
        ${set.locked ? lockIcon(true) : ""}
        <span class="vl-title" title="${escapeHtml(set.name)}">${escapeHtml(set.name)}</span>
        ${set.has_new ? chip("NEW", "is-new") : ""}${processedHtml}${nfoChangePill({ ...set, _kind: "set" })}${probeFailPill(set)}
        <span class="vl-meta${set.missing_count ? " has-missing" : ""}" title="${set.part_count ? `${set.part_count - set.missing_count} of ${set.part_count} in the TMDB collection are in the library` : "Movies in the library"}">${escapeHtml(years)} · ${set.part_count ? `${set.part_count - set.missing_count}/${set.part_count}` : set.movie_count}</span>
    </div>`;
}

function paintSetRows() {
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") return paintVideoRows();
    const host = document.getElementById("video-list");
    const head = host.querySelector(".vl-head");
    paintWindow(host, state.video.rows || [], setRowHtml, head ? head.offsetHeight : 0);
}

async function openSet(id) {
    if (!id) return;
    if (state.video && state.video.sets) {
        const found = state.video.sets.find((s) => s.id === id || (s.name && s.name.toLowerCase() === String(id).toLowerCase()));
        if (found) id = found.id;
    }
    if (state.media !== "sets") {
        state.video.setId = id;
        switchMedia("sets");
        return;
    }
    state.video.setId = id;
    state.video.paintToken += 1;
    paintSetRows();
    const center = document.getElementById("video-center");
    const token = (state.video.detailToken += 1);
    center.innerHTML = `<p class="muted vpad">Loading…</p>`;
    try {
        const set = await api(`/api/v1/sets/${encodeURIComponent(id)}`);
        if (token !== state.video.detailToken) return;
        renderSetInfo(set);
    } catch (error) {
        if (token === state.video.detailToken) center.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
    }
}

function renderSetInfo(set) {
    state.video.setDetail = set;
    const movies = set.movies || [];
    const runtime = movies.reduce((sum, movie) => sum + (Number(movie.runtime_minutes) || 0), 0);
    const grid = movies.map((movie) => `<button type="button" class="vset-card" data-action="video-open-movie" data-id="${escapeHtml(movie.id)}" data-switch="1" title="${escapeHtml(movie.title || "")}">
        ${movie.poster ? `<img loading="lazy" src="${artUrl(movie.poster, 342)}" alt="">` : `<span class="vposter is-empty">No poster</span>`}
        <strong class="vset-title">${escapeHtml(movie.title || "")}</strong>
        <small>${escapeHtml([movie.year, movie.resolution, hdrLabel(movie)].filter(Boolean).join(" · "))}</small>
    </button>`).join("");
    const art = set.artwork || {};
    const folder = set.folder
        ? `<p class="vline muted">Set folder: ${escapeHtml(set.folder)}</p>`
        : `<p class="vline muted">No set artwork yet. Choose a central set folder under Settings &gt; Movie Sets, then press Scrape.</p>`;
    const missing = set.missing || [];
    const today = new Date().toISOString().slice(0, 10);
    const missingGrid = missing.map((part) => {
        const unreleased = !part.release_date || part.release_date > today;
        return `<div class="vset-card is-missing" data-tmdb="${escapeHtml(part.tmdb_id)}" title="${escapeHtml(part.overview || part.title)}">
            ${part.poster ? `<img loading="lazy" src="${escapeHtml(part.poster)}" alt="" referrerpolicy="no-referrer">` : `<span class="vposter is-empty">No poster</span>`}
            <strong class="vset-title">${escapeHtml(part.title)}</strong>
            <small>${escapeHtml([part.year, unreleased ? "Not released" : ""].filter(Boolean).join(" · "))}</small>
            <small class="vset-radarr" data-radarr-state></small>
            <button type="button" class="btn-ghost${integrationOn("radarr") ? "" : " is-unavailable"}" data-action="video-radarr-search" data-tmdb="${escapeHtml(part.tmdb_id)}">Search in Radarr</button>
        </div>`;
    }).join("");
    const hasNew = set.status === "NEW";
    const lockBtn = typeof lockButton === "function" ? lockButton("set", set) : "";
    const bannerActions = `<div class="vstatus">${hasNew ? `<span class="badge-new">NEW</span>` : ""}
        <button type="button" class="${hasNew ? "btn-process" : "btn-ghost"}" data-action="video-set-processed" data-id="${escapeHtml(set.id)}" ${hasNew ? "" : "disabled"}>${hasNew ? "Mark processed" : "Processed"}</button>
        ${lockBtn}</div>
        <button type="button" class="title-delete" data-action="video-set-delete" data-id="${escapeHtml(set.id)}" title="Remove…" aria-label="Remove…">${typeof trashSvg === "function" ? trashSvg() : ""}</button>`;
    const owned = set.part_count ? `${set.part_count - missing.length} of ${set.part_count} in the library` : `${movies.length} movies`;
    const missingSection = missing.length
        ? `<section class="vsection vset-missing"><div class="vset-missing-head"><h3>Missing from the library (${missing.length})</h3>
                <button type="button" data-action="video-radarr-search" data-all="1"${integrationOn("radarr") ? "" : ` class="is-unavailable"`}>Search all missing in Radarr</button></div>
                <div class="vset-grid">${missingGrid}</div></section>`
        : (set.part_count ? "" : `<p class="vline muted vpad">Scrape the set to load the full TMDB collection and see which movies are missing.</p>`);
    const body = `${infoTitle(escapeHtml(set.name || ""), { kind: "set", id: set.id, locked: set.locked })}
        <div class="vchips">${artMarks(set.artwork, INFO_ART.set)}${nfoChip("set.nfo", set.nfo_path, "set", set.id, set.nfo_stale)}</div>
        <p class="vline">${owned}${runtime ? ` · ${fmtRuntime(runtime)} in total` : ""}${set.tmdb_collection_id ? ` · <a href="https://www.themoviedb.org/collection/${encodeURIComponent(set.tmdb_collection_id)}" target="_blank" rel="noopener">TMDB collection ${escapeHtml(set.tmdb_collection_id)}</a>` : ""}</p>
        ${set.overview ? `<p class="vplot">${escapeHtml(set.overview)}</p>` : ""}
        ${folder}
        ${set.scrape_error ? `<p class="vscrape-error">Last scrape: ${escapeHtml(set.scrape_error)} <button type="button" class="btn-ghost" data-action="video-copy-probe" data-fail="scrape" title="${escapeHtml(set.scrape_error)}">Copy</button></p>` : ""}
        <div class="vactions">
            <button type="button" class="btn-ghost" data-action="video-edit" data-kind="set" data-id="${escapeHtml(set.id)}" ${set.locked ? "disabled title=\"Unlock to edit\"" : ""}>Edit</button>
            <button type="button" class="btn-ghost" data-action="video-match" data-kind="set" data-id="${escapeHtml(set.id)}" ${set.locked ? "disabled" : ""}>Fix Match</button>
            <button type="button" class="btn-ghost" data-action="video-nfo-one" data-kind="set" data-id="${escapeHtml(set.id)}">Write set.nfo</button>
            <button type="button" class="btn-ghost btn-remove" data-action="video-set-remove" data-id="${escapeHtml(set.id)}">Remove from library</button>
        </div>`;
    document.getElementById("video-center").innerHTML = `<article class="vinfo">
        ${videoHero(art, art.poster, body, { kind: "set", id: set.id }, coverActions("set", set), { actions: bannerActions, badges: movies.length ? toneBadge(`${movies.length} ${movies.length === 1 ? "movie" : "movies"}`, "badge-plain") : "" })}
        <section class="vsection"><div class="vset-grid">${grid}</div></section>
        <section class="vsection"><h3>Artwork</h3>${artGallery(art, { kind: "set", id: set.id })}</section>
        ${missingSection}
    </article>`;
    if (missing.length) paintRadarrStates(missing.map((part) => part.tmdb_id));
}
async function paintRadarrStates(ids) {
    const token = state.video.detailToken;
    let data;
    try {
        data = await api("/api/v1/radarr/states", { method: "POST", body: { tmdb_ids: ids } });
    } catch (error) {
        return;
    }
    if (token !== state.video.detailToken) return;
    Object.entries(data.states || {}).forEach(([tmdb, info]) => {
        const label = document.querySelector(`.vset-card[data-tmdb="${CSS.escape(tmdb)}"] [data-radarr-state]`);
        if (label) label.textContent = info.has_file ? "In Radarr, file not scanned yet" : (info.monitored ? "Monitored in Radarr" : "In Radarr, not monitored");
    });
}

async function searchSetInRadarr(action) {
    const ids = action.dataset.all
        ? [...document.querySelectorAll(".vset-missing .vset-card[data-tmdb]")].map((card) => card.dataset.tmdb)
        : [action.dataset.tmdb];
    if (!ids.length) return;
    const data = await api("/api/v1/radarr/search", { method: "POST", body: { tmdb_ids: ids } });
    if (data.queued) {
        notify(data.message || "Radarr search queued.", "info");
        return;
    }
    (data.results || []).forEach((item) => {
        const label = document.querySelector(`.vset-card[data-tmdb="${CSS.escape(item.tmdb_id)}"] [data-radarr-state]`);
        if (label) label.textContent = item.ok ? (item.action === "added" ? "Added to Radarr, searching" : "Radarr is searching") : item.error;
    });
    if (data.failed && data.failed.length) {
        notify(`Radarr: ${data.ok} sent, ${data.failed.length} failed. ${data.failed[0].error}`, "error");
    } else {
        notify(ids.length === 1 ? "Sent to Radarr." : `Sent ${ids.length} movies to Radarr.`, "success");
    }
}

function moveSetSelection(step) {
    const rows = state.video.rows || [];
    if (!rows.length) return;
    const index = rows.findIndex((set) => set.id === state.video.setId);
    const next = Math.max(0, Math.min(rows.length - 1, index < 0 ? 0 : index + step));
    const host = document.getElementById("video-list");
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") {
        openSet(rows[next].id);
        if (typeof vgridReveal === "function") vgridReveal(host, rows[next].id);
        const card = host && host.querySelector(`.vgrid-card[data-id="${CSS.escape(rows[next].id)}"]`);
        if (card) card.scrollIntoView({ block: "nearest" });
        return;
    }
    scrollRowIntoView(host, next, 0);
    openSet(rows[next].id);
}

function openCreateSetModal() {
    const nameEl = document.getElementById("create-set-name");
    const tmdbEl = document.getElementById("create-set-tmdb");
    const overviewEl = document.getElementById("create-set-overview");
    if (nameEl) nameEl.value = "";
    if (tmdbEl) tmdbEl.value = "";
    if (overviewEl) overviewEl.value = "";
    const modal = document.getElementById("create-set-modal");
    if (modal) modal.classList.remove("hidden");
    if (nameEl) nameEl.focus();
}

async function createSetFromModal() {
    const name = (document.getElementById("create-set-name") || {}).value || "";
    const tmdb = (document.getElementById("create-set-tmdb") || {}).value || "";
    const overview = (document.getElementById("create-set-overview") || {}).value || "";
    if (!name.trim()) {
        notify("Enter a set name.", "warning");
        return;
    }
    const body = { name: name.trim(), overview: overview.trim() };
    if (tmdb.trim()) body.tmdb_collection_id = Number(tmdb.trim()) || null;
    const data = await api("/api/v1/sets", { method: "POST", body });
    const modal = document.getElementById("create-set-modal");
    if (modal) modal.classList.add("hidden");
    notify(`Created movie set “${name.trim()}”.`, "success");
    state.video.stale.sets = true;
    await loadVideo("sets", { keepScroll: true, quiet: true });
    if (data && data.id) openSet(data.id);
}
