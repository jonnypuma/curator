const VIDEO_LEFT_DEFAULT = { movies: 0.62, sets: 340, tv: 400 };

function readJson(key, fallback) {
    try {
        const value = JSON.parse(localStorage.getItem(key) || "null");
        return value == null ? fallback : value;
    } catch (error) {
        return fallback;
    }
}

state.video = {
    movies: null,
    sets: null,
    shows: null,
    rows: [],
    loading: {},
    asOf: { movies: "", tv: "" },
    listEpoch: 0,
    loadEpochs: {},
    stale: { movies: true, sets: true, tv: true },
    filter: { movies: "", sets: "", tv: "" },
    ribbons: { movies: new Set(), sets: new Set(), tv: new Set() },
    movieColumns: normalizeMovieColumns(readJson("curator.movieColumns", MOVIE_DEFAULT_COLUMNS)),
    tvColumns: normalizeTvColumns(readJson("curator.tvColumns", TV_DEFAULT_COLUMNS)),
    movieWidths: readJson("curator.movieWidths", {}),
    tvWidths: readJson("curator.tvWidths", {}),
    movieFilters: {},
    tvFilters: {},
    movieSort: readJson("curator.movieSort", { key: "title", dir: "asc" }),
    tvSort: readJson("curator.tvSort", { key: "title", dir: "asc" }),
    setSort: readJson("curator.setSort", { key: "name", dir: "asc" }),
    tvChecked: new Set(),
    setChecked: new Set(),
    movieId: null,
    setId: null,
    tvSel: null,
    detail: null,
    detailToken: 0,
    paintToken: 0,
    showDetails: new Map(),
    expanded: new Set(),
    left: readJson("curator.videoLeft", {}),
    right: readJson("curator.videoRight", {}),
    viewMode: readJson("curator.videoViewMode", {}),
};

function initVideo() {
    const filter = document.getElementById("video-filter");
    const list = document.getElementById("video-list");
    if (!filter || !list) {
        try { if (typeof pollVideoScan === "function") pollVideoScan(); } catch (e) { console.error("pollVideoScan error", e); }
        try { if (typeof pollVideoFiles === "function") pollVideoFiles(); } catch (e) { console.error("pollVideoFiles error", e); }
        return;
    }
    filter.addEventListener("input", debounce(() => {
        if (state.media === "music") return;
        state.video.filter[state.media] = filter.value;
        state.videoListScroll = 0;
        renderVideoList();
        list.scrollTop = 0;
    }, 150));
    const clearVideoScrollGuard = () => { state.videoScrollAt = 0; };
    list.addEventListener("wheel", clearVideoScrollGuard, { passive: true });
    list.addEventListener("touchmove", clearVideoScrollGuard, { passive: true });
    list.addEventListener("pointerdown", clearVideoScrollGuard, { passive: true });
    list.addEventListener("scroll", () => {
        if (state.videoScrollPin) return;
        const top = list.scrollTop;
        if (top === 0 && state.videoListScroll > 80) {
            const max = Math.max(0, list.scrollHeight - list.clientHeight);
            if (max + 1 < state.videoListScroll || performance.now() - (state.videoScrollAt || 0) < 1500) return;
        }
        state.videoListScroll = top;
        requestAnimationFrame(paintVideoRows);
    }, { passive: true });
    list.addEventListener("mousedown", (event) => {
        if (event.target.closest(".vl-caret")) event.preventDefault();
    });
    list.addEventListener("keydown", onVideoKey);
    window.addEventListener("resize", () => {
        applyVideoPanes();
        paintVideoRows();
    });
    const colMenu = document.getElementById("video-columns-menu");
    if (colMenu) {
        colMenu.addEventListener("change", (event) => {
            const key = event.target.dataset.videoCol;
            if (key) setMovieColumn(key, event.target.checked);
        });
    }
    document.addEventListener("click", (event) => {
        const menu = document.getElementById("video-columns-menu");
        if (menu && !menu.classList.contains("hidden") && !event.target.closest("#video-columns-menu, #video-columns-btn")) closeVideoColumns();
        const colFilter = document.getElementById("video-col-filter");
        if (colFilter && !colFilter.classList.contains("hidden") && !event.target.closest("#video-col-filter, .vm-filter")) colFilter.classList.add("hidden");
        if (!event.target.closest(".rescan-split, body > .scan-menu")) closeRescanMenus();
    });
    try { if (typeof bindVideoSplit === "function") bindVideoSplit(); } catch (e) { console.error("bindVideoSplit error", e); }
    try { if (typeof bindVideoScrape === "function") bindVideoScrape(); } catch (e) { console.error("bindVideoScrape error", e); }
    try { if (typeof bindVideoTags === "function") bindVideoTags(); } catch (e) { console.error("bindVideoTags error", e); }
    try { if (typeof bindInsights === "function") bindInsights(); } catch (e) { console.error("bindInsights error", e); }
    try { if (typeof pollVideoScan === "function") pollVideoScan(); } catch (e) { console.error("pollVideoScan error", e); }
    try { if (typeof pollVideoFiles === "function") pollVideoFiles(); } catch (e) { console.error("pollVideoFiles error", e); }
}

function renderVideo() {
    if (state.media === "music") return;
    const filter = document.getElementById("video-filter");
    if (filter) filter.value = state.video.filter[state.media] || "";
    const placeholders = { movies: "Filter titles, years, codecs, HDR, IDs…", sets: "Filter sets…", tv: "Filter shows…" };
    if (filter) filter.placeholder = placeholders[state.media] || "Filter…";
    document.getElementById("video-columns-btn").classList.toggle("hidden", state.media === "sets");
    document.getElementById("video-export-btn").classList.remove("hidden");
    document.getElementById("video-tags-btn").classList.toggle("hidden", state.media === "sets");
    const expandBtn = document.getElementById("video-expand-btn");
    const collapseBtn = document.getElementById("video-collapse-btn");
    const canExpand = state.media === "tv" || (state.media === "movies" && !!(typeof videoCfg === "function" && videoCfg().collapse_versions));
    if (expandBtn) expandBtn.classList.toggle("hidden", !canExpand);
    if (collapseBtn) collapseBtn.classList.toggle("hidden", !canExpand);
    document.getElementById("video-scrape-btn").classList.remove("hidden");
    const add = document.getElementById("video-add-btn");
    if (add) {
        add.hidden = false;
        add.textContent = state.media === "tv" ? "+ Show" : state.media === "sets" ? "+ Set" : "+ Movie";
        add.title = state.media === "tv"
            ? "Search TMDB or TheTVDB and send the show to Sonarr"
            : state.media === "sets"
                ? "Create a new movie set"
                : "Search TMDB and send the movie to Radarr";
    }
    syncVideoViewToggle();
    closeVideoColumns();
    closeVideoMenu();
    applyVideoPanes();
    const batch = document.getElementById("video-batch-select");
    if (batch) {
        batch.hidden = false;
        batch.querySelectorAll("[data-action='video-select-tier']").forEach((button) => {
            button.hidden = false;
        });
    }
    const key = state.media === "sets" ? "sets" : state.media === "tv" ? "tv" : "movies";
    const data = key === "sets" ? state.video.sets : key === "tv" ? state.video.shows : state.video.movies;
    if (data) renderVideoList();
    else showVideoListLoading();
    if (!data || state.video.stale[key]) loadVideo(state.media);
    renderVideoCenter();
    if (typeof paintMediaTotals === "function") paintMediaTotals();
}

function showVideoListLoading() {
    const list = document.getElementById("video-list");
    if (!list) return;
    state.video.rows = [];
    list.innerHTML = `<div class="tree-loading" role="status"><span class="activity-spin" aria-hidden="true"></span><span>Loading...</span></div>`;
}

async function loadVideo(media, options) {
    const opts = options || {};
    const key = media === "sets" ? "sets" : media === "tv" ? "tv" : "movies";
    const have = key === "sets" ? state.video.sets : key === "tv" ? state.video.shows : state.video.movies;
    if (state.video.loading[key]) {
        if (state.media === media && !have) showVideoListLoading();
        return;
    }
    const boot = typeof watchBoot === "function" ? watchBoot("video") : null;
    state.video.loading[key] = true;
    // listEpoch invalidates in-flight change refreshes; each library also has its own counter so
    // several libraries can load at the same time without discarding each other's answers.
    state.video.listEpoch = (state.video.listEpoch || 0) + 1;
    state.video.loadEpochs = state.video.loadEpochs || {};
    const epoch = (state.video.loadEpochs[key] = (state.video.loadEpochs[key] || 0) + 1);
    const list = document.getElementById("video-list");
    const scroll = list ? list.scrollTop : 0;
    if (!opts.quiet && state.media === media && !have) showVideoListLoading();
    try {
        if (key === "movies") {
            const data = await api("/api/v1/movies");
            if (epoch !== state.video.loadEpochs[key]) return;
            state.video.movies = data.movies || [];
            state.video.asOf.movies = data.as_of || "";
        } else if (key === "sets") {
            const data = await api("/api/v1/sets");
            if (epoch !== state.video.loadEpochs[key]) return;
            state.video.sets = data.sets || [];
        } else {
            const data = await api("/api/v1/tv/shows");
            if (epoch !== state.video.loadEpochs[key]) return;
            state.video.shows = data.shows || [];
            state.video.asOf.tv = data.as_of || "";
        }
        state.video.stale[key] = false;
    } catch (error) {
        if (list && state.media === media) list.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
        return;
    } finally {
        state.video.loading[key] = false;
        if (boot) boot.done();
    }
    if (state.media !== media) return;
    try {
        renderVideoList();
        if (opts.keepScroll && list) {
            state.videoListScroll = scroll;
            list.scrollTop = scroll;
            paintVideoRows();
        }
    } catch (err) {
        console.error("renderVideoList error during loadVideo", err);
    }
}

function applyVideoChanges(key, data) {
    const removed = new Set((data.removed || []).map((id) => String(id)));
    const incoming = key === "tv" ? (data.shows || []) : (data.movies || []);
    const byId = new Map(incoming.map((row) => [String(row.id), row]));
    let list = (key === "tv" ? state.video.shows : state.video.movies) || [];
    let dropped = 0;
    if (removed.size) {
        const kept = [];
        list.forEach((row) => {
            if (removed.has(String(row.id))) dropped += 1;
            else kept.push(row);
        });
        list = kept;
        removed.forEach((id) => {
            if (key === "movies") selectionSet("movie", id, false);
            else {
                state.video.showDetails.delete(id);
                state.video.expanded.delete(`show:${id}`);
                selectionSet("show", id, false);
            }
        });
    }
    const seen = new Set(list.map((row) => String(row.id)));
    list = list.map((row) => byId.get(String(row.id)) || row);
    incoming.forEach((row) => {
        if (!seen.has(String(row.id))) list.push(row);
    });
    if (key === "tv") state.video.shows = list;
    else state.video.movies = list;
    if (data.as_of) state.video.asOf[key] = data.as_of;
    return { ids: incoming.map((row) => String(row.id)), dropped };
}

async function refreshOpenShows(ids) {
    const open = (ids || []).filter((id) => state.video.showDetails.has(id));
    for (const id of open) {
        try {
            const detail = await api(`/api/v1/tv/shows/${encodeURIComponent(id)}`);
            if (state.video.showDetails.has(id)) state.video.showDetails.set(id, detail);
        } catch (error) {
            /* The show list still updates. The next open loads the episodes. */
        }
    }
}

async function refreshVideoChanges(media) {
    const key = media === "tv" ? "tv" : "movies";
    const have = key === "tv" ? state.video.shows : state.video.movies;
    const since = (state.video.asOf || {})[key];
    if (!have || !since) return loadVideo(media, { keepScroll: true, quiet: true });
    const epoch = state.video.listEpoch || 0;
    const ticket = (state.video.changeTicket = (state.video.changeTicket || 0) + 1);
    const list = document.getElementById("video-list");
    const scroll = list ? list.scrollTop : 0;
    let paint = false;
    try {
        const data = await api(`/api/v1/library/changes?media=${encodeURIComponent(key)}&since=${encodeURIComponent(since)}`);
        if (ticket !== state.video.changeTicket || (state.video.listEpoch || 0) !== epoch) return;
        const changed = applyVideoChanges(key, data);
        if (key === "tv" && changed.ids.length) await refreshOpenShows(changed.ids);
        if (ticket !== state.video.changeTicket || (state.video.listEpoch || 0) !== epoch) return;
        state.video.stale[key] = false;
        paint = changed.ids.length > 0 || changed.dropped > 0;
    } catch (error) {
        return;
    }
    if (!paint || state.media !== media) return;
    renderVideoList();
    if (list) {
        state.videoListScroll = scroll;
        list.scrollTop = scroll;
        paintVideoRows();
    }
}

function videoSortChoices() {
    if (state.media === "sets") {
        return { sort: state.video.setSort || { key: "name", dir: "asc" }, columns: [["name", "Name"], ["year", "Years"], ["movies", "Movies"]] };
    }
    if (typeof movieColumns !== "function") return { sort: { key: "title", dir: "asc" }, columns: [] };
    const columns = movieColumns().filter((column) => column.key !== "art").map((column) => [column.key, columnLabel(column)]);
    return { sort: matrixSort(), columns };
}

function paintVideoSortSelect() {
    const wrap = document.getElementById("video-sort-wrap");
    const select = document.getElementById("video-sort-select");
    if (!wrap || !select) return;
    const show = state.media === "movies" || state.media === "tv" || state.media === "sets";
    wrap.hidden = !show;
    if (!show) return;
    const { sort, columns } = videoSortChoices();
    const options = columns.flatMap(([key, label]) => [
        [`${key}:asc`, `Sort by ${label} ↑`],
        [`${key}:desc`, `Sort by ${label} ↓`],
    ]);
    select.innerHTML = options.map(([value, text]) => `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`).join("");
    select.value = `${sort.key}:${sort.dir === "desc" ? "desc" : "asc"}`;
}

function setVideoSortFromSelect(value) {
    const [key, dir] = String(value || "").split(":");
    if (!key) return;
    const sort = { key, dir: dir === "desc" ? "desc" : "asc" };
    if (state.media === "sets") {
        state.video.setSort = sort;
        localStorage.setItem("curator.setSort", JSON.stringify(sort));
    } else {
        const tv = matrixMode() === "tv";
        state.video[tv ? "tvSort" : "movieSort"] = sort;
        localStorage.setItem(tv ? "curator.tvSort" : "curator.movieSort", JSON.stringify(sort));
    }
    renderVideoList();
}

document.addEventListener("change", (event) => {
    if (event.target && event.target.id === "video-sort-select") setVideoSortFromSelect(event.target.value);
});

function renderVideoList() {
    paintVideoSortSelect();
    if (state.media === "movies" && !state.settings && !settingsSettled) {
        loadSettings().then(() => {
            if (state.media === "movies" && state.video.movies) renderVideoList();
        });
        return;
    }
    if (state.media === "movies") {
        renderMovieRibbons();
        renderMovieMatrix();
    } else if (state.media === "sets") {
        renderSetList();
    } else if (state.media === "tv") {
        renderTvTree();
    }
}

function videoViewMode() {
    const map = (state.video && state.video.viewMode) || {};
    return map[state.media] === "grid" ? "grid" : "list";
}

function syncVideoViewToggle() {
    const btn = document.getElementById("video-view-toggle");
    if (!btn) return;
    const isGrid = videoViewMode() === "grid";
    const gridIcon = btn.querySelector(".icon-grid");
    const listIcon = btn.querySelector(".icon-list");
    if (gridIcon) gridIcon.classList.toggle("hidden", isGrid);
    if (listIcon) listIcon.classList.toggle("hidden", !isGrid);
    btn.title = isGrid ? "Switch to List / Matrix view" : "Switch to Poster Grid view";
    btn.setAttribute("aria-label", btn.title);
    const sizeBox = document.querySelector('[data-size-toggle="video"]');
    if (sizeBox) sizeBox.classList.toggle("hidden", !isGrid);
    const colBtn = document.getElementById("video-columns-btn");
    if (colBtn) colBtn.classList.toggle("hidden", state.media === "sets" || isGrid);
}

function toggleVideoViewMode() {
    if (!state.video.viewMode || typeof state.video.viewMode !== "object") state.video.viewMode = {};
    state.video.viewMode[state.media] = videoViewMode() === "grid" ? "list" : "grid";
    localStorage.setItem("curator.videoViewMode", JSON.stringify(state.video.viewMode));
    syncVideoViewToggle();
    renderVideoList();
}

function videoGridCardHtml(row, kind, size) {
        const itemKind = row._kind || kind || "movie";
        if (itemKind !== "movie" && itemKind !== "show" && itemKind !== "set") return "";
        const id = row.id;
        const title = row.name || row.title || "Untitled";
        const year = row.year || row.first_year || "";
        const active = (itemKind === "movie" && id === state.video.movieId)
            || (itemKind === "set" && id === state.video.setId)
            || (itemKind === "show" && state.video.tvSel && state.video.tvSel.type === "show" && state.video.tvSel.id === id);
        const checked = selectionHas(itemKind, id);
        const selected = active || checked;
        let posterUrl = "";
        let fullPosterSrc = "";
        if (row.poster) {
            fullPosterSrc = artUrl(row.poster);
            posterUrl = artUrl(row.poster, size === "large" ? 500 : size === "small" ? 200 : 342);
        } else if (row.artwork && !Array.isArray(row.artwork) && row.artwork.poster) {
            fullPosterSrc = artUrl(row.artwork.poster);
            posterUrl = artUrl(row.artwork.poster, size === "large" ? 500 : size === "small" ? 200 : 342);
        } else if (Array.isArray(row.artwork) && row.artwork.includes("poster")) {
            const folder = row.folder || row.path || "";
            if (folder) {
                fullPosterSrc = artUrl(`${folder}/poster.jpg`);
                posterUrl = artUrl(`${folder}/poster.jpg`, size === "large" ? 500 : size === "small" ? 200 : 342);
            }
        }
        const showBadge = typeof artBadgeAllowed === "function" && artBadgeAllowed(itemKind);
        const openAct = itemKind === "set" ? "video-open-set" : itemKind === "show" ? "video-open-show" : "video-open-movie";
        let progress = "";
        if (itemKind === "show" || itemKind === "season") {
            const have = Math.max(0, (Number(row.episode_count) || 0) - (Number(row.missing_count) || 0));
            const total = have + (Number(row.missing_count) || 0);
            progress = tvProgressBarHtml(have, total, Number(row.missing_count) > 0);
        }
        return `<div class="vgrid-card${selected ? " is-selected" : ""}${active ? " is-active" : ""}${checked ? " is-checked" : ""}${row.status === "NEW" || row.has_new || row.new_count ? " is-new" : ""}" data-action="${openAct}" data-kind="${itemKind}" data-id="${escapeHtml(id)}">
            <div class="vgrid-poster-wrap">
                ${posterUrl ? `<img class="vgrid-poster" loading="lazy" src="${escapeHtml(posterUrl)}" data-full-src="${escapeHtml(fullPosterSrc)}" alt=""${showBadge ? ` onload="updateArtBadgeOnLoad(this)"` : ""} onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'vgrid-fallback', textContent:'No Poster'}))">${showBadge ? `<span class="art-dim-badge hidden"></span>` : ""}` : `<div class="vgrid-fallback">${escapeHtml(title)}</div>`}
                <label class="vgrid-check" onclick="event.stopPropagation()"><input type="checkbox" data-action="video-check" data-kind="${itemKind}" data-id="${escapeHtml(id)}" ${checked ? "checked" : ""}></label>
                ${row.locked ? `<span class="vgrid-lock">${lockIcon(true)}</span>` : ""}
            </div>
            ${progress}
            <div class="vgrid-meta">
                <strong class="vgrid-title" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
                <small class="vgrid-sub">${escapeHtml([year, row.resolution || (itemKind === "show" ? `${row.season_count || 0} seasons` : itemKind === "set" ? `${row.movie_count || 0} movies` : "")].filter(Boolean).join(" · "))}</small>
                ${size === "large" ? videoGridBadges(row, itemKind) : ""}
            </div>
        </div>`;
}

// Large cards carry a row of small badges with the technical facts the list shows in columns.
function videoGridBadges(row, kind) {
    let facts = [];
    if (kind === "movie") {
        facts = [row.resolution, row.hdr_main && row.hdr_main !== "SDR" ? row.hdr_main : "", row.codec, row.audio_codec ? [row.audio_codec, row.audio_channels].filter(Boolean).join(" ") : "", row.edition];
    } else if (kind === "show") {
        facts = [row.status, row.episode_count ? `${row.episode_count} episodes` : "", Number(row.missing_count) ? `${row.missing_count} missing` : ""];
    } else {
        facts = [row.status, row.movie_count ? `${row.movie_count} movies` : "", Number(row.missing_count) ? `${row.missing_count} missing` : ""];
    }
    const chips = facts.filter(Boolean).slice(0, 5).map((fact) => `<span class="vgrid-chip">${escapeHtml(String(fact))}</span>`).join("");
    return `<div class="vgrid-badges">${chips}</div>`;
}

function renderVideoPosterGrid(rows, kind) {
    const host = document.getElementById("video-list");
    if (!host) return;
    const items = (rows || []).filter((row) => ["movie", "show", "set"].includes(row._kind || kind || "movie"));
    vgridMount(host, {
        kind: `video-${state.media}`,
        items,
        key: (row) => row.id,
        ratio: 1.5,
        render: (row, size) => videoGridCardHtml(row, kind, size),
        empty: `<div class="vposter-grid"><p class="muted vpad">No matching items.</p></div>`,
    });
}

function paintVideoRows() {
    if (videoViewMode() === "grid") {
        const host = document.getElementById("video-list");
        if (!host) return;
        host.querySelectorAll(".vgrid-card").forEach((card) => {
            const itemKind = card.dataset.kind || "movie";
            const id = card.dataset.id || "";
            const active = (itemKind === "movie" && id === state.video.movieId)
                || (itemKind === "set" && id === state.video.setId)
                || (itemKind === "show" && state.video.tvSel && state.video.tvSel.type === "show" && state.video.tvSel.id === id);
            const checked = selectionHas(itemKind, id);
            card.classList.toggle("is-active", !!active);
            card.classList.toggle("is-checked", !!checked);
            card.classList.toggle("is-selected", !!(active || checked));
            const box = card.querySelector(".vgrid-check input");
            if (box) box.checked = !!checked;
        });
        return;
    }
    if (state.media === "movies") paintMovieRows();
    else if (state.media === "sets") paintSetRows();
    else if (state.media === "tv") paintTvRows();
}

function renderVideoCenter() {
    const center = document.getElementById("video-center");
    if (state.media === "movies" && state.video.movieId) return openMovie(state.video.movieId);
    if (state.media === "sets" && state.video.setId) return openSet(state.video.setId);
    if (state.media === "tv" && state.video.tvSel) {
        const sel = state.video.tvSel;
        if (sel.type === "show") return openShow(sel.id);
        if (sel.type === "season" && sel.show) return openSeason(sel.id, sel.show);
        if (sel.type === "episode") return openEpisode(sel.id);
    }
    const hints = {
        movies: "Pick a movie in the list. Every column can be sorted, and Columns chooses what is shown.",
        sets: "Pick a set to see its movies.",
        tv: "Pick a show, a season, or an episode.",
    };
    center.innerHTML = `<div class="video-empty"><h2 id="video-stage-title">${escapeHtml(MEDIA_TITLES[state.media] || "")}</h2>
        <p id="video-stage-counts-center" class="muted">${escapeHtml(mediaTotalsText(state.media))}</p>
        <p class="muted">${escapeHtml(hints[state.media] || "")}</p></div>`;
}

function renderVideoCounts(text) {
    const node = document.getElementById("video-stage-counts");
    if (node) node.textContent = text;
    paintVideoLegend();
}

function paintVideoLegend() {
    const count = document.getElementById("video-selected-count");
    if (!count) return;
    const facts = state.media === "music" || typeof videoSelectionFacts !== "function" ? { n: 0 } : videoSelectionFacts();
    count.textContent = `Items Selected: ${facts.n || 0}`;
    const button = document.getElementById("video-prune-held");
    if (!button) return;
    const rows = state.media === "tv" ? state.video.shows : state.media === "movies" ? state.video.movies : [];
    const held = (rows || []).filter((row) => row.prune_held).length;
    button.classList.toggle("hidden", held === 0);
    button.textContent = held ? `Remove all not found (${held.toLocaleString()})` : "Remove all not found";
}

function closeVideoColumns() {
    const menu = document.getElementById("video-columns-menu");
    const button = document.getElementById("video-columns-btn");
    if (menu) menu.classList.add("hidden");
    if (button) button.setAttribute("aria-expanded", "false");
}

function toggleVideoColumns() {
    const menu = document.getElementById("video-columns-menu");
    const opening = menu.classList.contains("hidden");
    if (opening) renderMovieColumnsMenu();
    menu.classList.toggle("hidden", !opening);
    document.getElementById("video-columns-btn").setAttribute("aria-expanded", opening ? "true" : "false");
}

/**
 * The list (matrix) pane on the left stretches; the info pane on the right keeps its width.
 * Only the right width is saved. Before one has been saved, it is what the old layout left over
 * (the old saved or default left width), so the first look is unchanged.
 */
function videoRightWidth() {
    const stage = document.getElementById("video-stage");
    const total = stage ? stage.clientWidth : window.innerWidth;
    const min = state.media === "movies" ? 420 : 220;
    let right = state.video.right[state.media];
    if (!right) {
        const fallback = VIDEO_LEFT_DEFAULT[state.media] || 380;
        const left = state.video.left[state.media] || (fallback < 1 ? Math.round(total * fallback) : fallback);
        right = total - 8 - left;
    }
    return Math.max(360, Math.min(Math.max(360, total - 8 - min), Math.round(right)));
}

function applyVideoPanes() {
    const stage = document.getElementById("video-stage");
    if (!stage || state.media === "music") return;
    if (window.innerWidth <= 1100) {
        stage.style.gridTemplateColumns = "";
        return;
    }
    stage.style.gridTemplateColumns = `minmax(0, 1fr) 8px ${videoRightWidth()}px`;
}

function bindVideoSplit() {
    const handle = document.getElementById("video-split");
    if (!handle) return;
    window.addEventListener("resize", () => { if (state.media !== "music") applyVideoPanes(); });
    const keep = () => {
        // The old left width is dropped once a right width is saved, so the two never disagree.
        delete state.video.left[state.media];
        localStorage.setItem("curator.videoLeft", JSON.stringify(state.video.left));
        localStorage.setItem("curator.videoRight", JSON.stringify(state.video.right));
    };
    handle.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || window.innerWidth <= 1100) return;
        const origin = event.clientX;
        const start = videoRightWidth();
        const move = (ev) => {
            state.video.right[state.media] = start - (ev.clientX - origin);
            applyVideoPanes();
            paintVideoRows();
        };
        const up = () => {
            state.video.right[state.media] = videoRightWidth();
            keep();
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", up);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", up);
        event.preventDefault();
    });
    handle.addEventListener("dblclick", () => {
        delete state.video.right[state.media];
        delete state.video.left[state.media];
        localStorage.setItem("curator.videoLeft", JSON.stringify(state.video.left));
        localStorage.setItem("curator.videoRight", JSON.stringify(state.video.right));
        applyVideoPanes();
        paintVideoRows();
    });
}

function setIdsFrom(action) {
    return selectionIds("set", action && action.dataset.id);
}

function removeSets(ids) {
    const chosen = (ids || []).filter(Boolean);
    if (!chosen.length) return;
    const count = chosen.length;
    askDanger(
        `Remove ${count} movie set${count === 1 ? "" : "s"} from the library?`,
        "The set record, collection list and artwork entry are removed. Movie files, movie .nfo files and each movie's own New status stay. The set folder on disk stays. A later scrape can create the set again from a movie.",
        "Remove from library",
        () => forgetSets(chosen),
        false,
    );
}

function deleteSetsAsk(ids) {
    const chosen = (ids || []).filter(Boolean);
    if (!chosen.length) return;
    const count = chosen.length;
    askDanger(
        `Remove ${count} movie set${count === 1 ? "" : "s"}?`,
        "Delete from disk removes the set folder under the movie set information folder: its artwork and set.nfo. Movies and their files are not touched. The set is also removed from the library. Removing from the library leaves that folder in place.",
        "Delete from disk",
        () => deleteSets(chosen),
        true,
        () => forgetSets(chosen),
    );
}

async function forgetSets(ids) {
    const data = await api("/api/v1/remove", { method: "POST", body: { kind: "set", ids } });
    notify(`Removed ${data.removed || 0} set${data.removed === 1 ? "" : "s"} from the library. Movies were left in place.`, "info");
    await afterSetRemoval(ids);
}

async function deleteSets(ids) {
    const data = await api("/api/v1/delete", { method: "POST", body: { kind: "set", ids } });
    const deleted = data.deleted || [];
    const errors = data.errors || [];
    if (errors.length) notify(`Deleted ${deleted.length}. ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "warning");
    else notify(`Deleted ${deleted.length} set${deleted.length === 1 ? "" : "s"} from disk. Movies were left in place.`, "info");
    await afterSetRemoval(ids);
}

async function afterSetRemoval(ids) {
    const gone = new Set(ids || []);
    state.video.sets = (state.video.sets || []).filter((set) => !gone.has(set.id));
    selectionDrop("set", [...gone]);
    if (gone.has(state.video.setId)) state.video.setId = null;
    (state.video.movies || []).forEach((movie) => {
        if (gone.has(movie.set_id)) {
            movie.set_id = null;
            movie.set_name = "";
        }
    });
    state.video.stale.movies = true;
    if (state.media === "sets") {
        renderSetList();
        const center = document.getElementById("video-center");
        if (center && !state.video.setId) center.innerHTML = "";
    }
    if (typeof loadMediaTotals === "function") loadMediaTotals();
}

async function processSets(ids) {
    const chosen = (ids || []).filter(Boolean);
    if (!chosen.length) return;
    await api("/api/v1/status", { method: "POST", body: { kind: "set", ids: chosen, status: "PROCESSED" } });
    (state.video.sets || []).forEach((set) => {
        if (chosen.includes(set.id)) {
            set.has_new = false;
            set.status = "PROCESSED";
        }
    });
    state.video.paintToken += 1;
    if (state.media === "sets") paintSetRows();
    if (state.video.setId && chosen.includes(state.video.setId)) openSet(state.video.setId);
    notify("Marked as processed.", "success");
}

async function copyProbeFailure(text, kind) {
    const failure = String(text || "").trim();
    if (!failure) return;
    const label = kind === "scrape" ? "Scrape failure" : "Probe failure";
    try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(failure);
        else copyPlainText(failure);
        notify(`${label} copied.`, "info");
    } catch (error) {
        try {
            copyPlainText(failure);
            notify(`${label} copied.`, "info");
        } catch (fallback) {
            notify(`Could not copy the ${label.toLowerCase()}.`, "warning");
        }
    }
}

function paintCurrentVideoList() {
    if (state.media === "movies") {
        const host = document.getElementById("video-list");
        const scroll = host ? host.scrollTop : 0;
        renderMovieRibbons();
        if (!host || !host.querySelector(".vwin-rows")) renderMovieMatrix();
        else {
            state.video.rows = visibleMovies();
            state.video.paintToken += 1;
            paintMovieRows();
            renderVideoCounts(`${state.video.rows.length} of ${(state.video.movies || []).length} movies`);
            paintVideoSelection();
            host.scrollTop = scroll;
        }
        return;
    }
    if (state.media === "tv") {
        if (typeof paintTvAfterStatus === "function") paintTvAfterStatus();
        const shows = state.video.shows || [];
        const episodes = shows.reduce((sum, item) => sum + (item.episode_count || 0), 0);
        const shownShows = (state.video.rows || []).filter((row) => row._kind === "show").length;
        renderVideoCounts(shows.length ? (shownShows !== shows.length ? `${shownShows} of ${shows.length} shows · ${episodes} episodes` : `${shows.length} shows · ${episodes} episodes`) : "No shows yet");
        return;
    }
    if (state.media === "sets") {
        state.video.paintToken += 1;
        if (typeof paintSetRows === "function") paintSetRows();
    }
}

function rewriteVideoPaths(moves) {
    const steps = (moves || []).filter((move) => move && move.from && move.to);
    if (!steps.length) return;
    const rewrite = (value) => {
        if (typeof value !== "string" || !value) return value;
        let next = value;
        steps.forEach((move) => {
            const from = String(move.from).replace(/\/+$/, "");
            const to = String(move.to).replace(/\/+$/, "");
            if (next === from || next.startsWith(`${from}/`)) next = to + next.slice(from.length);
        });
        return next;
    };
    const touch = (item) => {
        if (!item || typeof item !== "object") return;
        ["path", "folder", "nfo_path"].forEach((key) => {
            if (!item[key]) return;
            item[key] = rewrite(item[key]);
            const display = key === "path" ? "display_path" : `display_${key}`;
            if (item[display]) item[display] = rewrite(item[display]);
        });
        if (item.file) touch(item.file);
    };
    (state.video.movies || []).forEach(touch);
    (state.video.shows || []).forEach(touch);
    if (state.video.detail) touch(state.video.detail);
    (state.video.showDetails || new Map()).forEach((detail) => {
        touch(detail);
        (detail.seasons || []).forEach(touch);
        (detail.episodes || []).forEach(touch);
    });
    paintCurrentVideoList();
}

function patchVideoRows(kind, ids, fields) {
    const chosen = new Set(ids || []);
    const apply = (item) => {
        if (item && chosen.has(item.id)) Object.assign(item, fields);
    };
    if (kind === "set") {
        (state.video.sets || []).forEach((item) => {
            if (!item || !chosen.has(item.id)) return;
            Object.assign(item, fields);
            item.nfo_stale = false;
            if (fields.has_nfo && !item.nfo_path) item.nfo_path = "set.nfo";
        });
        if (state.video.setDetail && chosen.has(state.video.setDetail.id)) {
            Object.assign(state.video.setDetail, fields);
            if (state.media === "sets" && typeof renderSetInfo === "function") {
                renderSetInfo(state.video.setDetail);
            }
        }
        if (state.media === "sets" && typeof paintSetRows === "function") paintSetRows();
        return;
    }
    if (kind === "movie") {
        (state.video.movies || []).forEach(apply);
        if (state.video.detail) apply(state.video.detail);
        if (state.media === "movies" && state.video.detail && chosen.has(state.video.detail.id) && typeof renderMovieInfo === "function") {
            renderMovieInfo(state.video.detail);
        }
    } else {
        if (kind === "show") (state.video.shows || []).forEach(apply);
        (state.video.showDetails || new Map()).forEach((detail) => {
            if (kind === "show") apply(detail);
            if (kind === "season") (detail.seasons || []).forEach(apply);
            if (kind === "episode") (detail.episodes || []).forEach(apply);
            if (kind === "show" && Object.prototype.hasOwnProperty.call(fields, "locked") && chosen.has(detail.id)) {
                (detail.seasons || []).forEach((season) => { season.locked = fields.locked; });
                (detail.episodes || []).forEach((episode) => { episode.locked = fields.locked; });
            }
            if (kind === "season" && Object.prototype.hasOwnProperty.call(fields, "locked")) {
                (detail.seasons || []).forEach((season) => {
                    if (!chosen.has(season.id)) return;
                    (detail.episodes || []).filter((episode) => episode.season_id === season.id).forEach((episode) => {
                        episode.locked = fields.locked;
                    });
                });
            }
        });
        const sel = state.video.tvSel;
        if (sel) {
            const sameItem = chosen.has(sel.id) && sel.type === kind;
            const parentShow = kind === "show" && chosen.has(sel.show);
            let parentSeason = false;
            if (kind === "season" && sel.type === "episode") {
                const detail = state.video.showDetails && state.video.showDetails.get(sel.show);
                const ep = detail && (detail.episodes || []).find((e) => e.id === sel.id);
                if (ep && chosen.has(ep.season_id)) parentSeason = true;
            }
            if (sameItem || parentShow || parentSeason) refreshOpenTvPane();
        }
    }
    paintCurrentVideoList();
}

function refreshOpenTvPane() {
    const sel = state.video.tvSel;
    if (!sel || state.media !== "tv") return;
    if (sel.type === "show") {
        const show = state.video.showDetails.get(sel.id);
        if (show) renderShowInfo(show);
        return;
    }
    if (sel.type === "episode") {
        if (typeof openEpisode === "function") openEpisode(sel.id);
        return;
    }
    if (sel.type === "season") {
        const show = state.video.showDetails.get(sel.show);
        const season = show && (show.seasons || []).find((item) => item.id === sel.id);
        if (show && season) renderSeasonInfo(show, season);
    }
}

function patchVideoTags(ids, change) {
    const chosen = ids && ids.length ? new Set(ids) : null;
    const touch = (item) => {
        if (!item || (chosen && !chosen.has(item.id))) return;
        let tags = Array.isArray(item.tags) ? item.tags.slice() : [];
        if (change.drop) tags = tags.filter((tag) => tag !== change.drop);
        if (change.rename) tags = tags.map((tag) => (tag === change.rename[0] ? change.rename[1] : tag));
        if (change.remove) tags = tags.filter((tag) => !change.remove.includes(tag));
        if (change.add) tags = [...new Set(tags.concat(change.add))];
        item.tags = tags;
    };
    (state.video.movies || []).forEach(touch);
    (state.video.shows || []).forEach(touch);
    (state.video.showDetails || new Map()).forEach((detail) => {
        touch(detail);
        (detail.episodes || []).forEach(touch);
    });
    if (state.video.detail) touch(state.video.detail);
    paintCurrentVideoList();
}

function forgetLocalVideo(kind, ids) {
    const chosen = new Set(ids || []);
    if (!chosen.size) return;
    if (kind === "movie") {
        state.video.movies = (state.video.movies || []).filter((movie) => !chosen.has(movie.id));
        selectionDrop("movie", [...chosen]);
        if (chosen.has(state.video.movieId)) {
            state.video.movieId = null;
            state.video.detail = null;
        }
    } else if (kind === "set") {
        state.video.sets = (state.video.sets || []).filter((set) => !chosen.has(set.id));
        selectionDrop("set", [...chosen]);
        if (chosen.has(state.video.setId)) state.video.setId = null;
    } else if (kind === "show") {
        state.video.shows = (state.video.shows || []).filter((show) => !chosen.has(show.id));
        chosen.forEach((id) => {
            if (state.video.showDetails) state.video.showDetails.delete(id);
            selectionSet("show", id, false);
        });
        if (state.video.tvSel && chosen.has(state.video.tvSel.id)) state.video.tvSel = null;
    } else {
        (state.video.showDetails || new Map()).forEach((detail, showId) => {
            if (kind === "season") {
                const gone = (detail.seasons || []).filter((season) => chosen.has(season.id));
                if (!gone.length) return;
                const seasonIds = new Set(gone.map((season) => season.id));
                const removed = (detail.episodes || []).filter((episode) => seasonIds.has(episode.season_id)).length;
                detail.seasons = (detail.seasons || []).filter((season) => !seasonIds.has(season.id));
                detail.episodes = (detail.episodes || []).filter((episode) => !seasonIds.has(episode.season_id));
                const show = (state.video.shows || []).find((item) => item.id === showId);
                if (show && removed) show.episode_count = Math.max(0, (show.episode_count || 0) - removed);
            } else {
                const before = (detail.episodes || []).length;
                detail.episodes = (detail.episodes || []).filter((episode) => !chosen.has(episode.id));
                const removed = before - detail.episodes.length;
                const show = (state.video.shows || []).find((item) => item.id === showId);
                if (show && removed) show.episode_count = Math.max(0, (show.episode_count || 0) - removed);
            }
            if (typeof recountTvNew === "function") recountTvNew(showId);
        });
        selectionDrop(kind, [...chosen]);
        if (state.video.tvSel && state.video.tvSel.type === kind && chosen.has(state.video.tvSel.id)) state.video.tvSel = null;
    }
    state.videoDuplicateGroups = (state.videoDuplicateGroups || []).flatMap((group) => {
        const left = (group.items || []).filter((item) => !chosen.has(item.id));
        if (left.length === (group.items || []).length) return [group];
        return left.length >= 2 ? [{ ...group, items: left }] : [];
    });
    paintCurrentVideoList();
    const movieGone = kind === "movie" && !state.video.movieId && state.media === "movies";
    const tvGone = state.media === "tv" && !state.video.tvSel && (kind === "show" || kind === "season" || kind === "episode");
    if ((movieGone || tvGone) && typeof renderVideoCenter === "function") renderVideoCenter();
    if (typeof loadMediaTotals === "function") loadMediaTotals();
}

async function setVideoStatus(action) {
    const { kind, id, status } = action.dataset;
    await api("/api/v1/status", { method: "POST", body: { kind, ids: [id], status } });
    applyLocalVideoStatus(kind, [id], status);
}

function applyLocalVideoStatus(kind, ids, status) {
    const chosen = new Set(ids || []);
    if (!chosen.size) return;
    if (kind === "movie") {
        (state.video.movies || []).forEach((movie) => {
            if (chosen.has(movie.id)) movie.status = status;
        });
        if (state.video.detail && chosen.has(state.video.detail.id)) state.video.detail.status = status;
        if (state.media === "movies") {
            renderMovieRibbons();
            state.video.rows = visibleMovies();
            state.video.paintToken += 1;
            paintMovieRows();
            renderVideoCounts(`${state.video.rows.length} of ${(state.video.movies || []).length} movies`);
            if (state.video.movieId && chosen.has(state.video.movieId) && state.video.detail && state.video.detail.id === state.video.movieId) {
                renderMovieInfo(state.video.detail);
            }
        }
        return;
    }
    if (kind === "set") {
        (state.video.sets || []).forEach((set) => {
            if (!chosen.has(set.id)) return;
            set.status = status;
            if (status === "PROCESSED") set.has_new = false;
            if (status === "NEW") set.has_new = true;
        });
        state.video.paintToken += 1;
        if (state.media === "sets") paintSetRows();
        if (state.video.setId && chosen.has(state.video.setId)) openSet(state.video.setId);
        return;
    }
    if (kind === "show") {
        (state.video.shows || []).forEach((show) => {
            if (chosen.has(show.id)) show.status = status;
        });
        chosen.forEach((id) => {
            const detail = state.video.showDetails.get(id);
            if (detail) detail.status = status;
        });
    } else {
        const touched = new Set();
        state.video.showDetails.forEach((detail, showId) => {
            const list = kind === "season" ? detail.seasons : detail.episodes;
            (list || []).forEach((item) => {
                if (!chosen.has(item.id)) return;
                item.status = status;
                touched.add(showId);
            });
        });
        if (kind === "episode" || kind === "season") touched.forEach((showId) => recountTvNew(showId));
        mirrorTvStatus(touched);
    }
    if (kind === "show") mirrorTvStatus(chosen);
    paintTvAfterStatus({ keepRows: true });
    refreshOpenTvStatus(kind, chosen, status);
}

function recountTvNew(showId) {
    const detail = state.video.showDetails.get(showId);
    if (!detail) return;
    const episodes = detail.episodes || [];
    (detail.seasons || []).forEach((season) => {
        season.new_count = episodes.filter((episode) => episode.season_id === season.id && episode.status === "NEW").length;
    });
    const count = episodes.filter((episode) => episode.status === "NEW").length;
    detail.new_count = count;
    const show = (state.video.shows || []).find((item) => item.id === showId);
    if (show) show.new_count = count;
}

function mirrorTvStatus(showIds) {
    const wanted = showIds || null;
    (state.video.rows || []).forEach((row) => {
        if (row._kind === "show") {
            if (wanted && !wanted.has(row.id)) return;
            const show = (state.video.shows || []).find((item) => item.id === row.id);
            if (!show) return;
            row.status = show.status;
            row.new_count = show.new_count;
            return;
        }
        if (wanted && !wanted.has(row._showId)) return;
        const detail = state.video.showDetails.get(row._showId);
        if (!detail) return;
        if (row._kind === "season") {
            const season = (detail.seasons || []).find((item) => item.id === row.id);
            if (!season) return;
            row.status = season.status;
            row.new_count = season.new_count;
        } else if (row._kind === "episode") {
            const episode = (detail.episodes || []).find((item) => item.id === row.id);
            if (episode) row.status = episode.status;
        }
    });
}

function paintTvAfterStatus(options) {
    const keepRows = options && options.keepRows;
    if (state.media !== "tv") return;
    const host = document.getElementById("video-list");
    const scroll = host ? host.scrollTop : 0;
    const ribbons = document.getElementById("video-ribbons");
    if (ribbons) {
        ribbons.innerHTML = ribbonBarHtml(TV_RIBBONS, (state.video.shows || []).concat(
            [...state.video.showDetails.values()].flatMap((detail) => (detail.episodes || []).map((episode) => ({ ...episode, _kind: "episode" })))
        ));
    }
    if (keepRows) {
        state.video.paintToken += 1;
        if (host && host.querySelector(".vwin-rows")) {
            paintTvRows();
            host.scrollTop = scroll;
        }
        return;
    }
    if (!host || !host.querySelector(".vwin-rows")) {
        renderTvTree();
        if (host) host.scrollTop = scroll;
        return;
    }
    state.video.rows = visibleTvRows();
    state.video.paintToken += 1;
    paintTvRows();
    host.scrollTop = scroll;
}

function refreshOpenTvStatus(kind, chosen, status) {
    if (state.media !== "tv") return;
    const sel = state.video.tvSel;
    if (!sel) return;
    if (sel.type === "episode" && kind === "episode" && chosen.has(sel.id)) {
        const center = document.getElementById("video-center");
        const host = center && center.querySelector(".vstatus");
        let locked = false;
        (state.video.showDetails || new Map()).forEach((detail) => {
            (detail.episodes || []).forEach((episode) => {
                if (episode.id === sel.id) locked = !!episode.locked;
            });
        });
        if (host) host.outerHTML = statusButtons("episode", { id: sel.id, status, locked });
        syncStatusChip(center, status);
        return;
    }
    if (sel.type === "show") {
        const show = state.video.showDetails.get(sel.id);
        if (!show) return;
        const rows = kind === "season" ? (show.seasons || []) : (show.episodes || []);
        const hit = kind === "show" ? chosen.has(sel.id) : rows.some((item) => chosen.has(item.id));
        if (hit) renderShowInfo(show);
        return;
    }
    if (sel.type !== "season") return;
    const show = state.video.showDetails.get(sel.show);
    if (!show) return;
    const season = (show.seasons || []).find((item) => item.id === sel.id);
    if (!season) return;
    const hit = (kind === "season" && chosen.has(season.id))
        || (kind === "show" && chosen.has(show.id))
        || (kind === "episode" && (show.episodes || []).some((episode) => episode.season_id === season.id && chosen.has(episode.id)));
    if (hit) renderSeasonInfo(show, season);
}

function syncStatusChip(root, status) {
    const chips = root && (root.querySelector(".vchips-media") || root.querySelector(".vchips"));
    if (!chips) return;
    const existing = [...chips.querySelectorAll(".vchip")].find((node) => node.textContent === "NEW" || node.textContent === "Ignored" || node.textContent === "Processed");
    const next = statusChip(status);
    if (existing && next) existing.outerHTML = next;
    else if (existing) existing.remove();
    else if (next) chips.insertAdjacentHTML("beforeend", next);
}

function matrixTextSelected(action) {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount || !action) return false;
    const node = selection.anchorNode;
    return !!(node && action.contains(node));
}

function onVideoAction(name, action, event) {
    if (onVideoScrapeAction(name, action) || onVideoEditAction(name, action) || onVideoFilesAction(name, action)) return;
    if (name === "video-open-movie" || name === "video-open-set" || name === "video-open-show" || name === "video-open-season" || name === "video-open-episode") {
        if (matrixTextSelected(action)) return;
    }
    if (name === "video-view-toggle") return toggleVideoViewMode();
    if (name === "video-filter-query") {
        const q = (action.dataset.query || "").trim();
        if (!q) return;
        const targetMedia = state.media === "sets" ? "movies" : state.media;
        if (state.media !== targetMedia) switchMedia(targetMedia);
        state.video.filter[targetMedia] = q;
        const box = document.getElementById("video-filter");
        if (box) box.value = q;
        renderVideoList();
        const list = document.getElementById("video-list");
        if (list) list.scrollTop = 0;
        return;
    }
    if (name === "create-set-save" || name === "video-create-set-save") return runAction(createSetFromModal, "Creating movie set…");
    if (name === "video-batch-thumbs") return runAction(() => runVideoBatch("thumbs"), "Generating episode thumbnails…");
    if (name === "video-batch-themes") return runAction(() => runVideoBatch("themes"), "Downloading theme songs…");
    if (name === "video-batch-lock") {
        const unlock = videoSelectionAllLocked();
        return runAction(() => runVideoBatch(unlock ? "unlock" : "lock"), unlock ? "Unlocking…" : "Locking…");
    }
    if (name === "video-open-movie") {
        if (action.dataset.switch && state.media !== "movies") {
            state.video.movieId = action.dataset.id;
            switchMedia("movies");
            return;
        }
        focusVideoList();
        return openMovie(action.dataset.id);
    }
    if (name === "video-open-set") {
        focusVideoList();
        return openSet(action.dataset.id);
    }
    if (name === "video-open-show") {
        focusVideoList();
        return openShow(action.dataset.id);
    }
    if (name === "video-open-season") {
        focusVideoList();
        return openSeason(action.dataset.id, action.dataset.show);
    }
    if (name === "video-open-episode") {
        focusVideoList();
        return openEpisode(action.dataset.id);
    }
    if (name === "video-toggle") {
        event.stopPropagation();
        return toggleTvNode(action.dataset.key);
    }
    if (name === "video-sort") return sortMovies(action.dataset.col);
    if (name === "video-ribbon") {
        const key = action.dataset.ribbon;
        const ribbons = libraryRibbons();
        if (ribbons.has(key)) ribbons.delete(key);
        else ribbons.add(key);
        renderVideoList();
        const list = document.getElementById("video-list");
        if (list) list.scrollTop = 0;
        return;
    }
    if (name === "video-columns") return toggleVideoColumns();
    if (name === "video-columns-reset") {
        const key = matrixColumnsKey();
        state.video[key] = (key === "tvColumns" ? TV_DEFAULT_COLUMNS : MOVIE_DEFAULT_COLUMNS).slice();
        localStorage.setItem(key === "tvColumns" ? "curator.tvColumns" : "curator.movieColumns", JSON.stringify(state.video[key]));
        renderMovieColumnsMenu();
        return renderVideoList();
    }
    if (name === "video-col-filter") return openColumnFilter(action);
    if (name === "video-col-filter-toggle") return toggleColumnFilter(action.dataset.col, action.dataset.value || "");
    if (name === "video-col-filter-clear") return clearColumnFilter(action.dataset.col);
    if (name === "video-col-filter-set") return setColumnFilter(action.dataset.col, action.dataset.value || "");
    if (name === "video-filters-clear") return clearLibraryFilters();
    if (name === "video-filter-save") return openSavedFilterModal(state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : "movies");
    if (name === "video-filter-menu") {
        event.stopPropagation();
        return toggleSavedFilterMenu("video-saved-filters");
    }
    if (name === "video-filter-apply") return applyVideoSavedFilter(action.dataset.id);
    if (name === "video-filter-delete") {
        event.stopPropagation();
        return runAction(() => deleteSavedFilter(action.dataset.id, state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : "movies"));
    }
    if (name === "video-check") {
        event.preventDefault();
        event.stopPropagation();
        return selectionToggle(action.dataset.kind, action.dataset.id, event.shiftKey).then(() => paintCheckedRows());
    }
    if (name === "video-check-all") return selectionToggleVisible(action.checked).then(() => paintCheckedRows());
    if (name === "video-batch-scrape") return runAction(scrapeSelectedRows, "Scraping…");
    if (name === "video-batch-reload") return runAction(() => reloadSelectedRows(action), "Starting a scan…");
    if (name === "video-batch-move") return openBatchMove();
    if (name === "video-art-fetch") return runAction(() => fetchVideoArtwork(action), "Downloading artwork…");
    if (name === "video-rescan") return runAction(() => runCoverRescan(action), "Starting a scan…");
    if (name === "video-rescan-menu") return toggleRescanMenu(action);
    if (name === "video-rescan-mode") return chooseRescanMode(action);
    if (name === "video-deep-rescan") return runAction(() => deepRescanFolder(action), "Starting a deep scan…");
    if (name === "video-season-rescan") return runAction(() => deepRescanSeason(action), "Starting a deep scan…");
    if (name === "video-episode-rescan") return runAction(() => deepRescanEpisode(action), "Starting a deep scan…");
    if (name === "video-add-open") return runAction(openVideoAdd, "Opening search…");
    if (name === "video-add-pick") return runAction(() => pickVideoAdd(action), state.media === "tv" ? "Sending to Sonarr…" : "Sending to Radarr…");
    if (name === "video-art-delete") {
        askDanger(
            "Delete artwork",
            `Delete the ${action.dataset.artKind || ""} image file from disk? This cannot be undone.`,
            "Delete artwork",
            () => runAction(() => deleteVideoArt(action), "Deleting artwork…"),
            true
        );
        return;
    }
    if (name === "video-art-zoom") return openImageZoom(action.dataset.src, action.dataset.caption);
    if (name === "video-subs-get") return downloadSubtitle(Number(action.dataset.index));
    if (name === "video-subs-search") return searchSubtitles((document.getElementById("subs-find-languages") || {}).value || "");
    if (name === "video-subs-test") return testOpenSubtitles(action);
    if (name === "video-art-swap") {
        const image = (action.closest(".vposter-wrap") || action).querySelector("img");
        return runAction(() => openVideoArtPicker(action.dataset.kind, action.dataset.id, image ? fullImageUrl(image.src) : ""), "Searching artwork…");
    }
    if (name === "video-art-highlight") {
        const card = action.closest(".art-card");
        if (card) showVideoCompare(card);
        return;
    }
    if (name === "video-art-upload") return chooseVideoArtFile(action.dataset.artKind);
    if (name === "video-art-choose") return runAction(() => chooseVideoArt(action), "Saving artwork…");
    if (name === "video-copy-probe") {
        event.stopPropagation();
        return copyProbeFailure(action.getAttribute("title") || "", action.dataset.fail);
    }
    if (name === "video-upgrade") {
        event.stopPropagation();
        return runAction(() => showVideoUpgrade(action.dataset.kind, action.dataset.id), "Looking up copies…");
    }
    if (name === "video-versions") {
        event.stopPropagation();
        if (!state.video.openVersions) state.video.openVersions = new Set();
        if (state.video.openVersions.has(action.dataset.key)) state.video.openVersions.delete(action.dataset.key);
        else state.video.openVersions.add(action.dataset.key);
        const list = document.getElementById("video-list");
        const scroll = list ? list.scrollTop : 0;
        renderMovieMatrix();
        if (list) {
            list.scrollTop = scroll;
            paintMovieRows();
        }
        return;
    }
    if (name === "video-batch-art") return runAction(() => runVideoBatch("artwork"), "Downloading artwork…");
    if (name === "video-batch-nfo") return runAction(() => runVideoBatch("nfo"), "Writing .nfo files…");
    if (name === "video-batch-rename") return runAction(() => openSelectionRename(), "Preparing rename…");
    if (name === "video-batch-subs") return runAction(() => runVideoBatch("subs"), "Normalizing subtitles…");
    if (name === "video-batch-split") {
        const ids = typeof selectedSplitEpisodeIds === "function" ? selectedSplitEpisodeIds() : [];
        if (!ids.length) return;
        return openEpisodeSplits(ids);
    }
    if (name === "video-batch-trailers") return runAction(() => runVideoBatch("trailers"), "Downloading trailers…");
    if (name === "video-set-processed") return runAction(() => processSets([action.dataset.id]), "Saving…");
    if (name === "video-set-remove") return removeSets(setIdsFrom(action));
    if (name === "video-set-delete") return deleteSetsAsk(setIdsFrom(action));
    if (name === "video-select-tier") return selectVideoTier(action.dataset.tier);
    if (name === "video-select-all") return selectVideoAll(true);
    if (name === "video-select-none") return selectVideoAll(false);
    if (name === "video-select-clear") {
        if (state.media === "sets") selectionReplace("set", []);
        else if (state.media === "tv") selectionReplace("tv", []);
        else selectionReplace("movie", []);
        paintCheckedRows();
        return;
    }
    if (name === "video-batch-remove") return askVideoBatchRemoval(false);
    if (name === "video-batch-delete") return askVideoBatchRemoval(true);
    if (name === "video-batch-processed") {
        if (state.media === "sets") return runAction(() => processSets(selectionIds("set")), "Saving…");
        return runAction(() => runVideoBatch("processed"), "Saving…");
    }
    if (name === "video-sets-scrape") return runAction(scrapeAllSets, "Scraping movie sets…");
    if (name === "video-reload") {
        state.video.showDetails.clear();
        loadMediaTotals();
        return loadVideo(state.media, { keepScroll: true });
    }
    if (name === "video-expand-all") return runAction(expandAllVideoRows, "Expanding…");
    if (name === "video-collapse-all") return collapseAllVideoRows();
    if (name === "video-trailer-popout") return openTrailerPopout(action);
    if (name === "video-trailer-pip") return requestTrailerPip(document.querySelector("#video-center video.vtrailer"));
    if (name === "video-trailer-popout-pip") return requestTrailerPip(document.getElementById("trailer-popout-video"));
    if (name === "video-trailer-popout-size") return toggleTrailerPopoutSize();
    if (name === "video-trailer-popout-close") return closeTrailerPopout();
    if (name === "video-status") return runAction(() => setVideoStatus(action), "Saving…");
    if (name === "video-scan-start") return runAction(startVideoScanFromModal);
    if (name === "video-apply-match") return runAction(openPendingMatches, "Loading…");
    if (name === "video-apply-match-confirm") {
        const ids = pendingMatchIds();
        document.getElementById("pending-match-modal").classList.add("hidden");
        if (!ids.length) return;
        return runAction(() => applyPendingMatches(ids), "Applying match…");
    }
    if (name === "video-pending-match-remove") return removePendingMatchRow(action);
    if (name === "video-scan-cancel") return cancelVideoScan();
    if (name === "trakt-save-client") return runAction(saveTraktClient);
    if (name === "trakt-connect") {
        const tab = window.open("about:blank", "_blank");
        return runAction(() => connectTrakt(action, tab));
    }
    if (name === "trakt-device-cancel") return runAction(cancelTraktDevice);
    if (name === "trakt-copy-code") return copyTraktCode(action.dataset.code);
    if (name === "trakt-disconnect") return runAction(disconnectTrakt);
    if (name === "trakt-sync") return runAction(startTraktSync, "Starting the Trakt sync…");
}
