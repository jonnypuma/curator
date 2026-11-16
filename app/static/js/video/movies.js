const MOVIE_COLUMNS = [
    { key: "lock", label: "Lock", width: 44, get: (m) => (m.locked ? "Locked" : ""), sort: (m) => (m.locked ? 1 : 0), chip: (m) => lockIcon(m.locked), cls: "center" },
    { key: "title", label: "Title", width: 420, get: (m) => m.title || "", sort: (m) => titleSortKey(m), fixed: true, chip: (m) => movieTitleHtml(m) },
    { key: "year", label: "Year", width: 64, get: (m) => m.year || "", sort: (m) => m.year || 0, cls: "num", fixed: true },
    { key: "edition", label: "Edition", width: 120, get: (m) => m.edition || "" },
    { key: "resolution", label: "Res", width: 72, get: (m) => m.resolution || "", sort: (m) => ({ "8K": 5, "4K": 4, "1080p": 3, "720p": 2, SD: 1 }[m.resolution] || 0), chip: (m) => resolutionText(m.resolution), cls: "center" },
    { key: "hdr_main", label: "Main HDR", width: 210, get: (m) => hdrLabel(m), chip: (m) => hdrMainHtml(m) },
    { key: "hdr_profile", label: "DV profile", width: 72, get: (m) => (m.hdr_format === "dovi" && m.dovi_profile ? `P${m.dovi_profile}` : ""), chip: (m) => (m.hdr_format === "dovi" && m.dovi_profile ? hdrBadge(`P${m.dovi_profile}`, doviProfileClass(m.dovi_profile)) : ""), cls: "center" },
    { key: "hdr_el", label: "EL", width: 56, get: (m) => (m.dovi_el_type || ""), chip: (m) => (String(m.dovi_el_type || "").toUpperCase() === "FEL" ? hdrBadge("FEL", "badge-el-fel") : String(m.dovi_el_type || "").toUpperCase() === "MEL" ? hdrBadge("MEL", "badge-el-mel") : ""), cls: "center" },
    { key: "hdr_secondary", label: "Secondary HDR", width: 110, get: (m) => m.hdr_secondary || "", chip: (m) => hdrSecondaryHtml(m) },
    { key: "hybrid", label: "Hybrid", width: 64, get: (m) => (m.is_hybrid ? "Yes" : ""), sort: (m) => (m.is_hybrid ? 1 : 0), cls: "center" },
    { key: "codec", label: "Video codec", width: 84, get: (m) => m.video_codec || "", chip: (m) => videoCodecText(m.video_codec), cls: "center" },
    { key: "video_profile", label: "Video profile", width: 110, get: (m) => m.video_profile || "" },
    { key: "bitdepth", label: "Bits", width: 48, get: (m) => m.bit_depth || "", sort: (m) => m.bit_depth || 0, cls: "num" },
    { key: "audio_codec", label: "Audio codec", width: 88, get: (m) => normalAudioCodec(m.audio_codec), chip: (m) => audioCodecText(m.audio_codec), cls: "center" },
    { key: "audio_channels", label: "Channels", width: 72, get: (m) => m.audio_channels || "", chip: (m) => channelText(m.audio_channels), cls: "center" },
    { key: "audio", label: "Audio", width: 150, get: (m) => [normalAudioCodec(m.audio_codec), m.audio_channels].filter(Boolean).join(" "), chip: (m) => `${audioCodecText(m.audio_codec)}${channelText(m.audio_channels)}` || escapeHtml(m.audio_main || "") },
    { key: "audio_langs", label: "Audio langs", width: 110, get: (m) => langText(m.audio_langs) },
    { key: "subs", label: "Subtitles", width: 110, get: (m) => langText(m.sub_langs) },
    { key: "runtime", label: "Runtime", width: 72, get: (m) => fmtRuntime(m.runtime_minutes || Math.round((m.duration_seconds || 0) / 60)), sort: (m) => m.runtime_minutes || (m.duration_seconds || 0) / 60, cls: "num" },
    { key: "rating", label: "Rating", width: 60, get: (m) => (m.rating ? Number(m.rating).toFixed(1) : ""), sort: (m) => m.rating || 0, cls: "num" },
    { key: "votes", label: "Votes", width: 72, get: (m) => (m.votes ? Number(m.votes).toLocaleString() : ""), sort: (m) => m.votes || 0, cls: "num" },
    { key: "mpaa", label: "MPAA", width: 80, get: (m) => m.mpaa || "" },
    { key: "genres", label: "Genres", width: 170, get: (m) => listText(m.genres) },
    { key: "set", label: "Set", width: 170, get: (m) => m.set_name || "" },
    { key: "directors", label: "Director", width: 150, get: (m) => listText(m.directors, 2) },
    { key: "studios", label: "Studio", width: 140, get: (m) => listText(m.studios, 2) },
    { key: "countries", label: "Country", width: 110, get: (m) => listText(m.countries, 2), chip: (m) => countryFlags(m.countries) },
    { key: "width", label: "Width", width: 64, get: (m) => m.width || "", sort: (m) => m.width || 0, cls: "num" },
    { key: "height", label: "Height", width: 64, get: (m) => m.height || "", sort: (m) => m.height || 0, cls: "num" },
    { key: "aspect", label: "Aspect", width: 64, get: (m) => m.aspect_ratio || "", cls: "num" },
    { key: "fps", label: "FPS", width: 56, get: (m) => m.fps || "", sort: (m) => m.fps || 0, cls: "num" },
    { key: "max_cll", label: "MaxCLL", width: 68, get: (m) => m.max_cll || "", sort: (m) => Number(m.max_cll) || 0, cls: "num" },
    { key: "max_fall", label: "MaxFALL", width: 72, get: (m) => m.max_fall || "", sort: (m) => Number(m.max_fall) || 0, cls: "num" },
    { key: "source", label: "Source", width: 90, get: (m) => sourceName(m.video_source), chip: (m) => sourceCovered(m.video_source, m.source_format) ? "" : sourceText(m.video_source) },
    { key: "source_format", label: "Source format", width: 100, get: (m) => sourceName(m.source_format || m.video_source), chip: (m) => m.source_format ? sourceFormatText(m.source_format) : sourceText(m.video_source) },
    { key: "three_d", label: "3D", width: 64, get: (m) => (m.stereo_mode || (m.is_3d ? "3D" : "")), sort: (m) => (m.stereo_mode || (m.is_3d ? "3D" : "")), chip: (m) => (m.stereo_mode || m.is_3d ? toneBadge(m.stereo_mode || "3D", "badge-3d") : ""), cls: "center" },
    { key: "container", label: "Container", width: 80, get: (m) => containerName(m.container) },
    { key: "size", label: "Size", width: 80, get: (m) => fmtSize(m.size_bytes), sort: (m) => m.size_bytes || 0, cls: "num" },
    { key: "bitrate", label: "Bitrate", width: 76, get: (m) => (m.bitrate_mbps ? `${m.bitrate_mbps} Mb/s` : ""), sort: (m) => m.bitrate_mbps || 0, cls: "num" },
    { key: "imdb", label: "IMDb", width: 96, get: (m) => m.imdb_id || "" },
    { key: "tmdb", label: "TMDB", width: 76, get: (m) => m.tmdb_id || "" },
    { key: "tvdb", label: "TVDB", width: 76, get: (m) => m.tvdb_id || "" },
    { key: "trakt_id", label: "Trakt", width: 76, get: (m) => m.trakt_id || "" },
    { key: "anilist_id", label: "AniList", width: 76, get: (m) => m.anilist_id || "" },
    { key: "ofdb_id", label: "OFDb", width: 76, get: (m) => m.ofdb_id || "" },
    { key: "rating_imdb", label: "IMDb rating", width: 88, get: (m) => scoreText(m.rating_imdb), sort: (m) => Number(m.rating_imdb) || 0, cls: "num" },
    { key: "rating_tmdb", label: "TMDB rating", width: 88, get: (m) => scoreText(m.rating_tmdb), sort: (m) => Number(m.rating_tmdb) || 0, cls: "num" },
    { key: "rating_rt", label: "RT", width: 56, get: (m) => scoreText(m.rating_rt, 0), sort: (m) => Number(m.rating_rt) || 0, cls: "num" },
    { key: "rating_rt_audience", label: "RT audience", width: 88, get: (m) => scoreText(m.rating_rt_audience, 0), sort: (m) => Number(m.rating_rt_audience) || 0, cls: "num" },
    { key: "rating_metacritic", label: "Metascore", width: 84, get: (m) => scoreText(m.rating_metacritic, 0), sort: (m) => Number(m.rating_metacritic) || 0, cls: "num" },
    { key: "rating_metacritic_user", label: "Metacritic user", width: 110, get: (m) => scoreText(m.rating_metacritic_user), sort: (m) => Number(m.rating_metacritic_user) || 0, cls: "num" },
    { key: "rating_trakt", label: "Trakt rating", width: 88, get: (m) => scoreText(m.rating_trakt), sort: (m) => Number(m.rating_trakt) || 0, cls: "num" },
    { key: "rating_anilist", label: "AniList rating", width: 96, get: (m) => scoreText(m.rating_anilist), sort: (m) => Number(m.rating_anilist) || 0, cls: "num" },
    { key: "rating_ofdb", label: "OFDb rating", width: 84, get: (m) => scoreText(m.rating_ofdb), sort: (m) => Number(m.rating_ofdb) || 0, cls: "num" },
    { key: "rating_tvdb", label: "TVDB rating", width: 88, get: (m) => scoreText(m.rating_tvdb), sort: (m) => Number(m.rating_tvdb) || 0, cls: "num" },
    { key: "nfo", label: "NFO", width: 56, get: (m) => (m.has_nfo ? "✓" : "—"), sort: (m) => (m.has_nfo ? 1 : 0), chip: (m) => nfoMatrixChip(m), cls: "center" },
    { key: "art", label: "Art", width: 172, get: (m) => (m.artwork || []).join(", "), sort: (m) => (m.artwork || []).length, chip: (m) => artCell(m) },
    { key: "status", label: "Status", width: 340, get: (m) => [m.status === "NEW" ? "NEW" : m.status === "IGNORED" ? "Ignored" : m.status === "PROCESSED" ? "Processed" : "", (m._kind === "show" || m._kind === "season") && m.new_count ? (Number(m.new_count) === 1 ? "1 new episode" : `${Number(m.new_count)} new episodes`) : "", (m.upgrade || m._groupUpgrade) ? "Upgrade available" : "", (m.duplicate_release || m._groupDuplicate) ? "Duplicate" : "", m.prune_held ? "Not found" : "", ...healthWords(m)].filter(Boolean).join(" "), chip: (m) => videoStatus(m) },
    { key: "multi", label: "Multi", width: 120, tv: true, get: (m) => (isMultiRow(m) ? "Multi" : ""), sort: (m) => multiSortValue(m), chip: (m) => multiColumnChip(m), cls: "center" },
    { key: "added", label: "Added", width: 92, get: (m) => fmtDate(addedRaw(m)), sort: (m) => addedTime(m) },
    { key: "modified", label: "Modified", width: 100, get: (m) => fmtDate(m.mtime), sort: (m) => Number(m.mtime) || 0 },
    { key: "probed", label: "Probed", width: 100, get: (m) => fmtDate(m.probed_at), sort: (m) => String(m.probed_at || "") },
    { key: "path", label: "Path", width: 360, get: (m) => shownPath(m), chip: (m) => pathCell(shownPath(m)) },
];
const MOVIE_DEFAULT_COLUMNS = ["lock", "status", "title", "year", "resolution", "hdr_main", "hdr_secondary", "codec", "audio_codec", "audio_channels", "subs", "runtime", "rating", "studios", "set", "size", "modified", "nfo", "art"];
const TV_DEFAULT_COLUMNS = ["lock", "status", "multi", "title", "year", "resolution", "hdr_main", "hdr_secondary", "codec", "audio_codec", "audio_channels", "subs", "runtime", "rating", "studios", "size", "modified", "nfo", "art"];
const MOVIE_PREVIOUS_DEFAULT = ["lock", "title", "year", "resolution", "hdr_main", "hdr_secondary", "codec", "audio_codec", "audio_channels", "subs", "runtime", "rating", "set", "size", "modified", "nfo", "art", "status"];
const MOVIE_OLD_DEFAULT = ["lock", "status", "title", "year", "resolution", "hdr_main", "hdr_secondary", "codec", "audio_codec", "audio_channels", "subs", "runtime", "rating", "set", "size", "modified", "nfo", "art"];
const TV_OLD_DEFAULT = ["lock", "status", "multi", "title", "year", "resolution", "hdr_main", "hdr_secondary", "codec", "audio_codec", "audio_channels", "subs", "runtime", "rating", "set", "size", "modified", "nfo", "art"];

function columnLabel(column) {
    if (!column) return "";
    if (column.key === "studios" && matrixMode() === "tv") return "Network";
    return column.label || "";
}

function normalizeMovieColumns(list) {
    const known = new Set(MOVIE_COLUMNS.map((column) => column.key));
    const out = [];
    let incoming = list;
    if (Array.isArray(list)) {
        const joined = list.join();
        if (joined === MOVIE_PREVIOUS_DEFAULT.join() || joined === MOVIE_OLD_DEFAULT.join()) {
            incoming = MOVIE_DEFAULT_COLUMNS;
        }
    }
    (Array.isArray(incoming) ? incoming : []).forEach((key) => {
        const mapped = key === "hdr" ? ["hdr_main", "hdr_secondary"] : key === "network" ? ["studios"] : [key];
        mapped.forEach((item) => {
            if (known.has(item) && !out.includes(item)) out.push(item);
        });
    });
    ["title", "year"].forEach((key) => {
        if (!out.includes(key)) out.unshift(key);
    });
    const pinned = ["title", "year"].filter((key) => out.includes(key));
    return pinned.concat(out.filter((key) => !pinned.includes(key)));
}

function normalizeTvColumns(list) {
    let incoming = list;
    if (Array.isArray(list)) {
        const joined = list.join();
        if (joined === MOVIE_DEFAULT_COLUMNS.join() || joined === TV_OLD_DEFAULT.join() || joined === MOVIE_OLD_DEFAULT.join()) {
            incoming = TV_DEFAULT_COLUMNS;
        }
    }
    return normalizeMovieColumns(incoming);
}

const QUICK_RIBBONS = new Set(["new", "latest", "upgrade", "multi"]);

// When an item was added. A show counts from its newest episode on disk (last_added), so new episodes bring it up.
function addedRaw(row) {
    return row && (row.last_added || row.date_added || row.created_at);
}

function addedTime(row) {
    const raw = addedRaw(row);
    const then = raw ? Date.parse(String(raw).replace(" ", "T")) : NaN;
    return Number.isFinite(then) ? then : 0;
}

function recentAdded(row) {
    const then = addedTime(row);
    return then > 0 && Date.now() - then < 30 * 86400000;
}

// Latest added also sorts newest first, on the Added column. Turning it off puts back the sort from before,
// unless the sort was changed in the meantime.
function latestRibbonSort(on) {
    const tv = matrixMode() === "tv";
    const name = tv ? "tvSort" : "movieSort";
    const stash = state.video.sortBeforeLatest || (state.video.sortBeforeLatest = {});
    const current = state.video[name] || { key: "title", dir: "asc" };
    let next = null;
    if (on) {
        if (current.key !== "added" || current.dir !== "desc") stash[name] = current;
        next = { key: "added", dir: "desc" };
    } else if (current.key === "added" && current.dir === "desc") {
        next = stash[name] || { key: "title", dir: "asc" };
        delete stash[name];
    }
    if (!next) return;
    state.video[name] = next;
    localStorage.setItem(tv ? "curator.tvSort" : "curator.movieSort", JSON.stringify(next));
}

const MOVIE_RIBBONS = [
    ["new", "New", (m) => m.status === "NEW"],
    ["latest", "Latest added", (m) => recentAdded(m)],
    ["upgrade", "Upgrade available", (m) => !!m.upgrade || !!m._groupUpgrade],
    ["uhd", "4K", (m) => m.resolution === "4K" || m.resolution === "8K"],
    ["fhd", "1080p", (m) => m.resolution === "1080p"],
    ["dv", "DV", (m) => m.hdr_format === "dovi"],
    ["fel", "P7 FEL", (m) => String(m.dovi_profile || "").startsWith("7") && m.dovi_el_type === "FEL"],
    ["hdr10plus", "HDR10+", (m) => m.hdr_format === "hdr10plus" || m.hdr_secondary === "HDR10+"],
    ["hdr10", "HDR10", (m) => m.hdr_format === "hdr10" || m.hdr_secondary === "HDR10"],
    ["hlg", "HLG", (m) => m.hdr_format === "hlg" || m.hdr_secondary === "HLG"],
    ["sdr", "SDR", (m) => m.hdr_format === "sdr"],
    ["nonfo", "No NFO", (m) => !m.has_nfo],
    ["nfo", "NFO changes", (m) => !!m.nfo_stale],
    ["noposter", "No poster", (m) => !(m.artwork || []).includes("poster")],
    ["noimdb", "No IMDb rating", (m) => !(Number(m.rating_imdb) > 0)],
    ["probefail", "Probe failed", (m) => !!m.probe_error],
    ["health", "Health warnings", (m) => healthWords(m).length > 0],
    ["corrupt", "Corrupt", (m) => (m.health || []).includes("corrupt")],
    ["unscraped", "Not scraped", (m) => !m.scraped_at],
    ["scrapefail", "Scrape failed", (m) => !!m.scrape_error],
    ["unmatched", "Unmatched", (m) => !m.tmdb_id && !m.imdb_id && !m.tvdb_id],
    ["locked", "Locked", (m) => !!m.locked],
    ["ignored", "Ignored", (m) => m.status === "IGNORED"],
    ["duplicate", "Duplicate", (m) => !!m.duplicate_release || !!m._groupDuplicate],
    ["held", "Not found", (m) => !!m.prune_held],
    ["nosubs", "No subtitles", (m) => !(m.sub_langs && m.sub_langs.length)],
    ["noen_subs", "Missing English subtitles", (m) => !(m.sub_langs || []).some((l) => /^en/i.test(String(l)))],
    ["multi_audio", "Multi-audio", (m) => (m.audio_langs || []).length > 1],
    ["unknown_audio", "Unknown audio language", (m) => Number(m.audio_unknown) > 0],
    ["unknown_subs", "Unknown subtitle language", (m) => Number(m.sub_unknown) > 0],
    ["notrailer", "No trailer", (m) => !m.has_trailer && !m.trailer_file],
    ["missing_trailer", "Missing trailer", (m) => m.has_local_trailer === false],
    ["missing_theme", "Missing theme song", (m) => m.has_local_theme === false],
];

function artCell(row) {
    const art = Array.isArray(row.artwork) ? row.artwork : Object.keys(row.artwork || {});
    const mark = (kind, short, title) => `<span class="vart-dot${short.length > 1 ? " is-wide" : ""}${art.includes(kind) ? " is-on" : ""}" title="${title}">${short}</span>`;
    if (row._kind === "episode" || row._kind === "missing") return mark("thumb", "T", "Thumb");
    const show = row._kind === "show" || row._kind === "season";
    const disc = show ? "" : mark("discart", "D", "Discart");
    const key = row._kind === "season" ? "" : mark("keyart", "K", "Key art");
    const character = show ? mark("characterart", "Ch", "Character art") : "";
    return `${mark("poster", "P", "Poster")}${mark("fanart", "F", "Fanart")}${mark("clearlogo", "C", "Clearlogo")}${mark("clearart", "A", "Clear art")}${mark("landscape", "L", "Landscape")}${mark("banner", "B", "Banner")}${disc}${key}${mark("squareart", "S", "Square art")}${character}`;
}

const INFO_ART = {
    movie: [["poster", "P", "Poster"], ["fanart", "F", "Fanart"], ["clearlogo", "C", "Clearlogo"], ["clearart", "A", "Clear art"], ["landscape", "L", "Landscape"], ["banner", "B", "Banner"], ["discart", "D", "Discart"], ["keyart", "K", "Key art"], ["squareart", "S", "Square art"]],
    show: [["poster", "P", "Poster"], ["fanart", "F", "Fanart"], ["clearlogo", "C", "Clearlogo"], ["clearart", "A", "Clear art"], ["landscape", "L", "Landscape"], ["banner", "B", "Banner"], ["keyart", "K", "Key art"], ["characterart", "Ch", "Character art"]],
    season: [["poster", "P", "Poster"], ["fanart", "F", "Fanart"], ["landscape", "L", "Landscape"], ["banner", "B", "Banner"]],
    episode: [["thumb", "T", "Thumb"]],
    set: [["poster", "P", "Poster"], ["fanart", "F", "Fanart"], ["clearlogo", "C", "Clearlogo"], ["clearart", "A", "Clear art"], ["landscape", "L", "Landscape"], ["banner", "B", "Banner"], ["keyart", "K", "Key art"]],
    artist: [["artistthumb", "T", "Artist thumb"], ["fanart", "F", "Fanart"], ["clearlogo", "C", "Clearlogo"], ["landscape", "L", "Landscape"], ["banner", "B", "Banner"]],
    album: [["front", "F", "Front"], ["back", "BK", "Back"], ["discart", "D", "Disc"]],
};

function artMarks(artwork, order) {
    const art = Array.isArray(artwork) ? artwork : Object.keys(artwork || {});
    const marks = (order || []).map(([kind, short, title]) => {
        const on = art.includes(kind) ? " is-on" : "";
        const wide = short.length > 1 ? " is-wide" : "";
        return `<span class="vart-dot${wide}${on}" title="${escapeHtml(title)}">${escapeHtml(short)}</span>`;
    }).join("");
    return marks ? `<span class="vart-row">${marks}</span>` : "";
}

function matrixMode() {
    return state.media === "tv" ? "tv" : "movies";
}

function matrixColumnsKey() {
    return matrixMode() === "tv" ? "tvColumns" : "movieColumns";
}

function matrixWidths() {
    return state.video[matrixMode() === "tv" ? "tvWidths" : "movieWidths"] || {};
}

function matrixSort() {
    return state.video[matrixMode() === "tv" ? "tvSort" : "movieSort"] || { key: "title", dir: "asc" };
}

function matrixFilters() {
    return state.video[matrixMode() === "tv" ? "tvFilters" : "movieFilters"] || {};
}

function movieColumns() {
    const wanted = state.video[matrixColumnsKey()] || MOVIE_DEFAULT_COLUMNS;
    const pinned = MOVIE_COLUMNS.filter((column) => column.fixed);
    const rest = wanted.filter((key) => !pinned.some((column) => column.key === key))
        .map((key) => MOVIE_COLUMNS.find((column) => column.key === key))
        .filter((column) => column && (matrixMode() === "tv" || !column.tv));
    return pinned.concat(rest);
}

function matrixColumnWidth(column) {
    let saved = Number(matrixWidths()[column.key]);
    if (column.key === "art" && saved > 0 && saved <= 120) saved = column.width;
    if (column.key === "title" && saved > 0 && saved <= 280) saved = column.width;
    return saved >= 48 ? saved : column.width;
}

function movieHaystack(movie) {
    if (!movie._hay) {
        movie._hay = [
            movie.title, movie.original_title, movie.year, movie.edition, movie.set_name, movie.imdb_id, movie.tmdb_id,
            movie.video_codec, movie.resolution, hdrLabel(movie), movie.hdr_secondary, movie.audio_main,
            (movie.genres || []).join(" "), (movie.directors || []).join(" "), (movie.studios || []).join(" "),
            (movie.countries || []).join(" "), movie.search_extra,
            langText(movie.audio_langs), movie.video_source, movie.source_format, sourceName(movie.video_source), shownPath(movie), movie.path,
        ].filter(Boolean).join(" ").toLowerCase();
    }
    return movie._hay;
}

function columnPlain(column, row) {
    try {
        const value = column.get(row);
        return value == null ? "" : String(value);
    } catch (error) {
        return "";
    }
}

function rowMatchesFilters(row, filters) {
    return Object.entries(filters || {}).every(([key, query]) => {
        const column = MOVIE_COLUMNS.find((item) => item.key === key);
        if (!column || !columnFilterActive(query)) return true;
        const plain = columnPlain(column, row);
        if (Array.isArray(query)) return query.some((value) => plain === value);
        return plain.toLowerCase().includes(String(query).toLowerCase());
    });
}

function titleSortKey(row) {
    const custom = String(row && row.sort_title || "").trim();
    if (custom) return custom.toLowerCase();
    return librarySortName(row && row.title || "").toLowerCase();
}

function sortMatrixRows(rows) {
    const sort = matrixSort();
    const column = MOVIE_COLUMNS.find((item) => item.key === sort.key) || MOVIE_COLUMNS[1];
    const value = column.sort || ((row) => columnPlain(column, row).toLowerCase());
    const dir = sort.dir === "desc" ? -1 : 1;
    return rows.slice().sort((a, b) => {
        const left = value(a);
        const right = value(b);
        if (left < right) return -dir;
        if (left > right) return dir;
        return titleSortKey(a).localeCompare(titleSortKey(b));
    });
}

function movieMatchRows(exceptKey) {
    const all = state.video.movies || [];
    const match = textMatcher(state.video.filter.movies);
    const ribbons = MOVIE_RIBBONS.filter(([key]) => libraryRibbons().has(key));
    const filters = { ...(state.video.movieFilters || {}) };
    if (exceptKey) delete filters[exceptKey];
    return all.filter((movie) => (!match || match(movieHaystack(movie))) && ribbons.every(([, , test]) => test(movie)) && rowMatchesFilters(movie, filters));
}

function visibleMovies() {
    return collapseMovieRows(sortMatrixRows(movieMatchRows()));
}

function movieVersionKey(movie) {
    if (movie.tmdb_id) return `tmdb:${movie.tmdb_id}`;
    if (movie.imdb_id) return `imdb:${String(movie.imdb_id).toLowerCase()}`;
    if (movie.title && movie.year) return `title:${String(movie.title).toLowerCase()}:${movie.year}`;
    return `id:${movie.id}`;
}

function collapseMovieRows(rows) {
    if (!videoCfg().collapse_versions) return rows;
    const groups = new Map();
    rows.forEach((movie) => {
        const key = movieVersionKey(movie);
        const list = groups.get(key) || [];
        list.push(movie);
        groups.set(key, list);
    });
    const open = state.video.openVersions || new Set();
    const seen = new Set();
    const out = [];
    rows.forEach((movie) => {
        const key = movieVersionKey(movie);
        if (seen.has(key)) return;
        seen.add(key);
        const group = groups.get(key) || [movie];
        if (group.length < 2) {
            out.push(movie);
            return;
        }
        const ranked = group.slice().sort((left, right) => (right.height || 0) - (left.height || 0) || (right.bitrate_mbps || 0) - (left.bitrate_mbps || 0));
        const best = ranked[0];
        const upgraded = group.find((item) => item.upgrade);
        const failed = group.find((item) => item.probe_error);
        const scrapeFailed = group.find((item) => item.scrape_error);
        out.push({
            ...best,
            _versions: group.length,
            _versionKey: key,
            _versionIds: ranked.map((item) => item.id),
            _markId: (upgraded || best).id,
            _groupDuplicate: group.some((item) => item.duplicate_release),
            _groupDuplicateId: (group.find((item) => item.duplicate_release) || {}).id || "",
            _groupUpgrade: !!upgraded,
            _groupUpgradePath: upgraded ? (upgraded.upgrade_path || "") : "",
            _groupProbeError: failed ? failed.probe_error : "",
            _groupScrapeError: scrapeFailed ? scrapeFailed.scrape_error : "",
        });
        if (open.has(key)) ranked.forEach((item) => out.push({ ...item, _version: true }));
    });
    return out;
}

function movieTitleHtml(movie) {
    if (movie._kind && movie._kind !== "movie") return escapeHtml(movie.title || "");
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    const showYear = cfg.ui_movie_year !== false;
    const showEdition = cfg.ui_movie_edition !== false;

    let rawTitle = String(movie.title || "").trim();
    if (showYear && movie.year && new RegExp(`\\(\\s*${movie.year}\\s*\\)\\s*$`).test(rawTitle)) {
        rawTitle = rawTitle.replace(new RegExp(`\\s*\\(\\s*${movie.year}\\s*\\)\\s*$`), "");
    }

    const bracketParts = [];
    if (showYear && movie.year) {
        bracketParts.push(String(movie.year));
    }
    if (showEdition) {
        const ed = typeof movieEdition === "function" ? movieEdition(movie) : "";
        if (ed) bracketParts.push(ed);
    }
    const extra = bracketParts.length ? ` <span class="muted">(${escapeHtml(bracketParts.join(" · "))})</span>` : "";

    const caret = movie._versions
        ? `<button type="button" class="vl-caret" data-action="video-versions" data-key="${escapeHtml(movie._versionKey)}" aria-label="Show versions">${(state.video.openVersions || new Set()).has(movie._versionKey) ? "▾" : "▸"}</button>`
        : "";
    const note = movie._versions ? ` <span class="muted">${movie._versions} versions available</span>` : "";
    const pad = movie._version ? " vm-indent-1" : "";
    const arrow = movie._version ? "↳ " : "";
    return `<span class="vl-title${pad}">${caret}${arrow}${escapeHtml(rawTitle)}${extra}${note}</span>${titleFacts(movie)}`;
}

function ribbonButton(key, label, count, on, shown) {
    return `<button type="button" class="vribbon${on ? " is-on" : ""}" data-action="video-ribbon" data-ribbon="${key}" aria-pressed="${on}" ${count || on ? "" : "disabled"}>${escapeHtml(label)} <small>${escapeHtml(String(shown === undefined ? count : shown))}</small></button>`;
}

// "12 shows, 340 episodes": what a filter counts, by kind of row (TV lists mix shows, seasons and episodes).
const RIBBON_KINDS = [["show", "show", "shows"], ["season", "season", "seasons"], ["episode", "episode", "episodes"]];

// countKey names the per-show total the server sends for an episode filter. A show whose episodes are not loaded
// yet adds that total to the episode count, so the figure covers the whole library and not just the opened shows.
function ribbonBreakdown(rows, test, countKey) {
    const counts = {};
    const opened = countKey ? state.video.showDetails : null;
    (rows || []).forEach((row) => {
        if (!test(row)) return;
        const kind = row._kind || "show";
        counts[kind] = (counts[kind] || 0) + 1;
        if (countKey && kind === "show" && !opened.has(row.id)) counts.episode = (counts.episode || 0) + (Number(row[countKey]) || 0);
    });
    const parts = RIBBON_KINDS.filter(([kind]) => counts[kind]).map(([kind, one, many]) => `${counts[kind]} ${counts[kind] === 1 ? one : many}`);
    return { total: Object.values(counts).reduce((sum, value) => sum + value, 0), text: parts.join(", ") || "0" };
}

function ribbonBarHtml(definitions, rows, quickKeys, keepAllOptions, byKind) {
    const quickSet = quickKeys || QUICK_RIBBONS;
    const countOf = (test, countKey) => (byKind ? ribbonBreakdown(rows, test, countKey).total : (rows || []).reduce((sum, row) => sum + (test(row) ? 1 : 0), 0));
    const shownOf = (test, countKey) => (byKind ? ribbonBreakdown(rows, test, countKey).text : undefined);
    const quick = definitions.filter(([key]) => quickSet.has(key)).map(([key, label, test, countKey]) => {
        return ribbonButton(key, label, countOf(test, countKey), libraryRibbons().has(key), shownOf(test, countKey));
    }).join("");
    const rest = definitions.filter(([key]) => !quickSet.has(key));
    const active = rest.filter(([key]) => libraryRibbons().has(key)).map(([key, label, test, countKey]) => {
        return ribbonButton(key, label, countOf(test, countKey), true, shownOf(test, countKey));
    }).join("");
    const options = [`<option value="">More filters</option>`].concat(rest.map(([key, label, test, countKey]) => {
        const count = countOf(test, countKey);
        const on = libraryRibbons().has(key) ? " (on)" : "";
        return `<option value="${escapeHtml(key)}" ${count || keepAllOptions || libraryRibbons().has(key) ? "" : "disabled"}>${escapeHtml(label)} (${byKind ? shownOf(test, countKey) : count})${on}</option>`;
    })).join("");
    const clear = state.media === "movies" || state.media === "tv" || state.media === "sets"
        ? `<button type="button" class="btn-ghost vribbon-clear" data-action="video-filters-clear" ${libraryFiltersOn() ? "" : "disabled"}>Clear all</button>${savedFilterControls(state.media)}`
        : "";
    return `${quick}<label class="vribbon-more"><span class="sr-only">More filters</span><select data-ribbon-pick>${options}</select></label>${clear}${active}`;
}

function savedFilterControls(media) {
    ensureSavedFilters(media);
    const rows = ((state.video.savedFilters || {})[media] || []).map((row) => savedFilterRow(row, "video-filter")).join("");
    const empty = rows ? "" : `<p class="muted">No saved filters</p>`;
    return `<button type="button" class="btn-ghost vribbon-clear" data-action="video-filter-save" ${libraryFiltersOn() ? "" : "disabled"}>Save filter</button>
        <span class="saved-filter-menu">
            <button type="button" class="btn-ghost vribbon-clear" data-action="video-filter-menu">Saved</button>
            <span class="saved-filter-list hidden" id="video-saved-filters">${empty}${rows}</span>
        </span>`;
}

const SAVED_FILTER_ACTIONS = { scrape: "Scrape what is missing", integrity: "Quick integrity check", trailers: "Download trailers" };
const SAVED_FILTER_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function savedFilterSchedule(row) {
    if (!row.action || row.action_every === "off") return "";
    const hour = `${String(row.action_hour || 0).padStart(2, "0")}:00`;
    const when = row.action_every === "week" ? `every ${SAVED_FILTER_DAYS[row.action_weekday || 0]} ${hour}` : `daily ${hour}`;
    return `${SAVED_FILTER_ACTIONS[row.action] || row.action}, ${when}`;
}

function savedFilterRow(row, prefix) {
    const tag = `${row.tag ? ` · ${row.tag}` : ""}${row.playlist ? " · Kodi playlist" : ""}`;
    const schedule = savedFilterSchedule(row);
    const title = [row.action_last_result ? `Last run: ${row.action_last_result}` : "",
        (row.unmatched_ribbons || []).length ? `Only on screen, not used by the action: ${row.unmatched_ribbons.join(", ")}` : ""]
        .filter(Boolean).join(" · ");
    const run = schedule && prefix === "video-filter"
        ? `<button type="button" class="link" data-action="video-filter-run" data-id="${escapeHtml(row.id)}" title="${escapeHtml(title || "Run the action now")}">Run now</button>`
        : "";
    return `<span class="saved-filter-row">
        <button type="button" class="link" data-action="${prefix}-apply" data-id="${escapeHtml(row.id)}">${escapeHtml(row.name)}${escapeHtml(tag)}${schedule ? `<small class="muted"> · ${escapeHtml(schedule)}</small>` : ""}</button>
        ${run}
        <button type="button" class="link filter-x" data-action="${prefix}-delete" data-id="${escapeHtml(row.id)}" title="Remove saved filter">×</button>
    </span>`;
}

async function runSavedFilterAction(id) {
    const data = await api(`/api/v1/filters/${encodeURIComponent(id)}/run`, { method: "POST", body: {} });
    notify(data.result || "Started.", "info");
    await loadSavedFilters(state.media === "tv" ? "tv" : "movies");
}

function currentVideoFilterPayload() {
    const media = state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : "movies";
    const columns = media === "tv" ? state.video.tvFilters : media === "sets" ? {} : state.video.movieFilters;
    return {
        filters: columns || {},
        ribbons: [...libraryRibbons()],
        search: (state.video.filter && state.video.filter[media]) || "",
    };
}

async function loadSavedFilters(media) {
    if (!state.video.savedFilters) state.video.savedFilters = {};
    if (!state.video.savedFilterLoads) state.video.savedFilterLoads = {};
    const boot = typeof watchBoot === "function" && (media === "movies" || media === "tv" || media === "sets") ? watchBoot("filters") : null;
    state.video.savedFilterLoads[media] = "loading";
    try {
        const data = await api(`/api/v1/filters?media=${encodeURIComponent(media)}`);
        state.video.savedFilters[media] = data.filters || [];
        state.video.savedFilterLoads[media] = true;
        const ready = media === "tv" ? state.video.shows : media === "sets" ? state.video.sets : state.video.movies;
        if (state.media === media && ready && typeof renderVideoList === "function") renderVideoList();
        if (media === "music") renderMusicSavedFilters();
        return state.video.savedFilters[media];
    } catch (error) {
        state.video.savedFilterLoads[media] = false;
        throw error;
    } finally {
        if (boot) boot.done();
    }
}

function ensureSavedFilters(media) {
    if (!state.video.savedFilterLoads) state.video.savedFilterLoads = {};
    if (state.video.savedFilterLoads[media]) return;
    state.video.savedFilterLoads[media] = true;
    loadSavedFilters(media).then(() => {
        if (state.media === media && media !== "music") renderVideoList();
        if (media === "music") renderMusicSavedFilters();
    }).catch(() => {
        state.video.savedFilterLoads[media] = false;
    });
}

function openSavedFilterModal(media) {
    state.video.filterSaveMedia = media;
    const music = media === "music";
    const noTag = music || media === "sets";
    document.getElementById("saved-filter-name").value = "";
    document.getElementById("saved-filter-tag").value = "";
    document.getElementById("saved-filter-tag-row").classList.toggle("hidden", noTag);
    const playlist = document.getElementById("saved-filter-playlist");
    if (playlist) playlist.checked = false;
    document.getElementById("saved-filter-playlist-row").classList.toggle("hidden", media === "sets");
    const actionRow = document.getElementById("saved-filter-action-row");
    if (actionRow) actionRow.classList.toggle("hidden", media !== "movies" && media !== "tv");
    const actionBox = document.getElementById("saved-filter-action");
    if (actionBox) actionBox.value = "";
    syncSavedFilterActionRow();
    document.getElementById("saved-filter-note").textContent = music
        ? "This saves the current library preset for music."
        : media === "sets"
            ? "This saves the active ribbons and search box for movie sets."
            : "The search box is saved with this view. A scan uses the ribbons and column filters when it writes the tag.";
    document.getElementById("saved-filter-modal").classList.remove("hidden");
    document.getElementById("saved-filter-name").focus();
}

async function confirmSavedFilter() {
    const media = state.video.filterSaveMedia;
    const name = document.getElementById("saved-filter-name").value.trim();
    if (!name) {
        notify("Name the filter.", "error");
        return;
    }
    const tag = (media === "music" || media === "sets") ? "" : document.getElementById("saved-filter-tag").value.trim();
    const payload = media === "music"
        ? { preset: (document.getElementById("library-filter") || {}).value || "all" }
        : currentVideoFilterPayload();
    const playlistBox = document.getElementById("saved-filter-playlist");
    const playlist = !!(playlistBox && playlistBox.checked) && media !== "sets";
    const value = (id) => (document.getElementById(id) || {}).value || "";
    const action = (media === "movies" || media === "tv") ? value("saved-filter-action") : "";
    const schedule = action ? { action, action_every: value("saved-filter-every") || "day",
        action_hour: Number(value("saved-filter-hour")) || 0, action_weekday: Number(value("saved-filter-weekday")) || 0 } : {};
    await api("/api/v1/filters", { method: "POST", body: { media, name, payload, tag: tag || null, playlist, ...schedule } });
    document.getElementById("saved-filter-modal").classList.add("hidden");
    await loadSavedFilters(media);
    if (media === "music") renderMusicSavedFilters();
    else renderVideoList();
    notify(tag ? `Saved. A scan can write the tag “${tag}”.` : "Filter saved.", "success");
}

// The schedule fields only matter with an action; the day only with "every week".
function syncSavedFilterActionRow() {
    const action = (document.getElementById("saved-filter-action") || {}).value || "";
    document.querySelectorAll("#saved-filter-action-row .saved-filter-when").forEach((node) => { node.hidden = !action; });
    const weekday = document.getElementById("saved-filter-weekday-row");
    if (weekday) weekday.hidden = !action || (document.getElementById("saved-filter-every") || {}).value !== "week";
}

document.addEventListener("change", (event) => {
    const id = event.target && event.target.id;
    if (id === "saved-filter-action" || id === "saved-filter-every") syncSavedFilterActionRow();
});

function toggleSavedFilterMenu(id) {
    const list = document.getElementById(id);
    if (!list) return;
    list.classList.toggle("hidden");
}

async function applyVideoSavedFilter(id) {
    const media = state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : "movies";
    const row = ((state.video.savedFilters || {})[media] || []).find((item) => item.id === id);
    if (!row) return;
    const payload = row.payload || {};
    if (media === "tv") state.video.tvFilters = payload.filters || {};
    else if (media === "movies") state.video.movieFilters = payload.filters || {};
    const ribbons = libraryRibbons();
    const hadLatest = ribbons.has("latest");
    ribbons.clear();
    (payload.ribbons || []).forEach((key) => ribbons.add(key));
    if (media !== "sets" && hadLatest !== ribbons.has("latest")) latestRibbonSort(ribbons.has("latest"));
    if (!state.video.filter) state.video.filter = {};
    state.video.filter[media] = payload.search || "";
    const box = document.getElementById("video-filter");
    if (box) box.value = payload.search || "";
    const menu = document.getElementById("video-saved-filters");
    if (menu) menu.classList.add("hidden");
    renderVideoList();
    const list = document.getElementById("video-list");
    if (list) list.scrollTop = 0;
}

async function deleteSavedFilter(id, media) {
    await api(`/api/v1/filters/${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadSavedFilters(media);
    if (media === "music") renderMusicSavedFilters();
    else renderVideoList();
}

function renderMusicSavedFilters() {
    const host = document.getElementById("music-saved-filters");
    if (!host) return;
    const rows = ((state.video.savedFilters || {}).music || []).map((row) => savedFilterRow(row, "music-filter")).join("");
    host.innerHTML = rows || `<p class="muted">No saved filters</p>`;
}

function applyMusicPreset(preset) {
    const select = document.getElementById("library-filter");
    if (!select) return;
    if (typeof clearMusicColumnFilters === "function") clearMusicColumnFilters();
    select.value = preset || "all";
    select.dispatchEvent(new Event("change"));
}

async function refreshSavedFiltersForLibrary() {
    const media = state.media;
    if (media !== "movies" && media !== "tv" && media !== "sets" && media !== "music") return;
    try {
        await loadSavedFilters(media);
        if (media === "music") renderMusicSavedFilters();
    } catch (error) {
        /* The ribbon still works when the list cannot load. */
    }
}

function columnFilterActive(query) {
    if (Array.isArray(query)) return query.length > 0;
    return !!String(query || "").trim();
}

function columnFilterLabel(query) {
    if (Array.isArray(query)) return query.join(", ");
    return String(query || "");
}

function libraryFiltersOn() {
    const media = state.media;
    const columns = media === "tv" ? state.video.tvFilters : media === "sets" ? {} : state.video.movieFilters;
    const typed = state.video.filter && state.video.filter[media];
    return Object.values(columns || {}).some(columnFilterActive)
        || libraryRibbons().size > 0
        || String(typed || "").trim();
}

function clearLibraryFilters() {
    if (state.media === "tv") state.video.tvFilters = {};
    else if (state.media === "movies") state.video.movieFilters = {};
    if ((state.media === "tv" || state.media === "movies") && libraryRibbons().has("latest")) latestRibbonSort(false);
    libraryRibbons().clear();
    if (state.video.filter) state.video.filter[state.media] = "";
    const box = document.getElementById("video-filter");
    if (box) box.value = "";
    const pop = document.getElementById("video-col-filter");
    if (pop) pop.classList.add("hidden");
    renderVideoList();
    const list = document.getElementById("video-list");
    if (list) list.scrollTop = 0;
}

function renderMovieRibbons() {
    document.getElementById("video-ribbons").innerHTML = ribbonBarHtml(MOVIE_RIBBONS, state.video.movies || []);
}

function matrixTemplate(columns) {
    const widths = columns.map(matrixColumnWidth);
    const total = 36 + widths.reduce((sum, width) => sum + width, 0);
    return { style: `--vm-cols:36px ${widths.map((width) => `${width}px`).join(" ")};min-width:${total}px` };
}

function matrixHeadHtml(columns) {
    const sort = matrixSort();
    const filters = matrixFilters();
    const rows = state.video.rows || [];
    const checked = rows.length > 0 && rows.every((row) => matrixChecked(row));
    const cells = columns.map((column) => {
        const mark = sort.key === column.key ? (sort.dir === "desc" ? " ▾" : " ▴") : "";
        const pinned = column.fixed ? "" : ` draggable="true"`;
        const query = filters[column.key];
        const label = columnFilterLabel(query);
        const colLabel = columnLabel(column);
        const hint = columnFilterActive(query) ? ` title="Filtered: ${escapeHtml(label)}"` : "";
        return `<span class="vm-cell vm-head-cell ${column.cls || ""}${columnFilterActive(query) ? " is-filtered" : ""}" data-col="${column.key}"${hint}${pinned}>
            <button type="button" class="vm-sort" data-action="video-sort" data-col="${column.key}" title="Sort by ${escapeHtml(colLabel)}">${escapeHtml(colLabel)}${mark}</button>
            <button type="button" class="vm-filter${columnFilterActive(query) ? " is-on" : ""}" data-action="video-col-filter" data-col="${column.key}" title="Filter ${escapeHtml(colLabel)}" aria-label="Filter ${escapeHtml(colLabel)}">▾</button>
            <span class="vm-resize" data-col="${column.key}" title="Drag to resize"></span>
        </span>`;
    }).join("");
    return `<span class="vm-cell vm-check"><input type="checkbox" data-action="video-check-all" ${checked ? "checked" : ""} title="Select the rows on screen" aria-label="Select the rows on screen"></span>${cells}`;
}

function matrixChecked(row) {
    if (!row) return false;
    if (state.media === "sets") return selectionHas("set", row.id);
    if (row._kind && row._kind !== "movie") return selectionHas(row._kind, row.id);
    return movieRowIds(row).every((id) => selectionHas("movie", id));
}

// The movies a row stands for: every version of a collapsed versions row, else the row's own movie.
function movieRowIds(row) {
    if (row && row._versions && !row._version && Array.isArray(row._versionIds) && row._versionIds.length) return row._versionIds;
    return row && row.id ? [row.id] : [];
}

function versionsAttr(row) {
    const ids = movieRowIds(row);
    return ids.length > 1 ? ` data-versions="${escapeHtml(ids.join(","))}"` : "";
}

function renderMovieMatrix() {
    const host = document.getElementById("video-list");
    const scroll = typeof pinnedListScroll === "function" ? pinnedListScroll(host) : (host ? host.scrollTop : 0);
    const columns = movieColumns();
    state.video.rows = visibleMovies();
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") {
        renderVideoPosterGrid(state.video.rows, "movie");
        renderVideoCounts(`${state.video.rows.length} of ${(state.video.movies || []).length} movies`);
        paintVideoSelection();
        return;
    }
    if (host) state.videoScrollPin = true;
    host.innerHTML = `<div class="vmatrix" style="${matrixTemplate(columns).style}">
        <div class="vm-head" role="row">${matrixHeadHtml(columns)}</div>
        <div class="vwin-rows"></div>
    </div>`;
    bindMatrixChrome(host);
    state.video.paintToken += 1;
    if (typeof pinListScroll === "function") pinListScroll(host, scroll);
    paintMovieRows();
    renderVideoCounts(`${state.video.rows.length} of ${(state.video.movies || []).length} movies`);
    paintVideoSelection();
    const expandBtn = document.getElementById("video-expand-btn");
    const collapseBtn = document.getElementById("video-collapse-btn");
    const canExpand = state.media === "movies" && !!(typeof videoCfg === "function" && videoCfg().collapse_versions);
    if (expandBtn) expandBtn.classList.toggle("hidden", !canExpand);
    if (collapseBtn) collapseBtn.classList.toggle("hidden", !canExpand);
}

function matrixCell(column, row) {
    if (column.key === "title" && row._kind && row._kind !== "movie" && typeof tvTitleCell === "function") {
        return `<span class="vm-cell" data-col="title">${tvTitleCell(row)}</span>`;
    }
    let content = column.chip ? column.chip(row) : escapeHtml(columnPlain(column, row));
    const title = column.key === "title" || column.key === "path" ? ` title="${escapeHtml(columnPlain(column, row))}"` : "";
    let plain = "";
    if (BADGE_FILTER_COLUMNS.has(column.key)) {
        content = content.replace(/<span class="vhdr /g, `<span data-action="video-badge-filter" title="Filter by this" class="vhdr vhdr-filter `);
        plain = ` data-plain="${escapeHtml(columnPlain(column, row))}"`;
    }
    return `<span class="vm-cell ${column.cls || ""}" data-col="${column.key}"${title}${plain}>${content}</span>`;
}

// Quality badges in these columns filter the list when clicked. A badge picks every value of its column that holds it:
// P7 in Main HDR picks DV P7, DV P7 FEL and DV P7 MEL, and FEL then narrows that to DV P7 FEL.
const BADGE_FILTER_COLUMNS = new Set(["resolution", "hdr_main", "hdr_profile", "hdr_el", "hdr_secondary", "codec",
    "audio_codec", "audio_channels", "audio", "source", "source_format", "three_d"]);

function badgeHolds(plain, token) {
    return plain === token || plain.startsWith(`${token} `) || plain.endsWith(` ${token}`) || plain.includes(` ${token} `);
}

function sameValues(left, right) {
    return left.length === right.length && left.every((value) => right.includes(value));
}

// The new picks for a badge click. Narrows the current picks when they overlap, widens back when they were a part of
// the badge's values, and clears the column when the badge is exactly what is already picked.
function badgeFilterPicks(current, values) {
    if (!current.length) return values;
    if (sameValues(current, values)) return [];
    const both = current.filter((value) => values.includes(value));
    if (both.length === current.length) return values;
    return both.length ? both : values;
}

function badgeFilter(badge) {
    const cell = badge.closest(".vm-cell[data-col]");
    const key = cell && cell.dataset.col;
    const column = MOVIE_COLUMNS.find((item) => item.key === key);
    if (!column) return;
    const text = String(badge.textContent || "").trim();
    const token = text === "Dolby Vision" ? "DV" : text;
    const own = cell.dataset.plain || "";
    const source = matrixMode() === "tv" && typeof visibleTvRows === "function" ? visibleTvRows(key) : movieMatchRows(key);
    let values = [...new Set(source.map((row) => columnPlain(column, row)).filter((value) => value && badgeHolds(value, token)))];
    if (!own || !badgeHolds(own, token)) values = own ? [own] : [];
    if (!values.length) return;
    writeColumnPicks(key, badgeFilterPicks(columnPicks(key), values));
}

function movieRowHtml(movie, index) {
    const checked = matrixChecked(movie);
    const selected = movie.id === state.video.movieId || checked;
    const cells = movieColumns().map((column) => matrixCell(column, movie)).join("");
    const versions = movieRowIds(movie).length;
    const label = versions > 1 ? `Select all ${versions} versions of ${movie.title || "this movie"}` : `Select ${movie.title || "movie"}`;
    const box = `<span class="vm-cell vm-check"><input type="checkbox" data-action="video-check" data-kind="movie" data-id="${escapeHtml(movie.id)}"${versionsAttr(movie)} ${checked ? "checked" : ""} aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"></span>`;
    return `<div class="vm-row${selected ? " is-selected" : ""}${movie.status === "NEW" ? " is-new" : ""}" style="top:${index * VIDEO_ROW}px" data-action="video-open-movie" data-id="${escapeHtml(movie.id)}" role="row">${box}${cells}</div>`;
}

function paintMovieRows() {
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") return paintVideoRows();
    const host = document.getElementById("video-list");
    const head = host.querySelector(".vm-head");
    paintWindow(host, state.video.rows || [], movieRowHtml, head ? head.offsetHeight : 0);
}

function renderMovieColumnsMenu() {
    const menu = document.getElementById("video-columns-menu");
    const selected = state.video[matrixColumnsKey()] || [];
    menu.innerHTML = MOVIE_COLUMNS.filter((column) => !column.fixed && (matrixMode() === "tv" || !column.tv)).map((column) =>
        `<label class="choice"><input type="checkbox" data-video-col="${column.key}" ${selected.includes(column.key) ? "checked" : ""}> ${escapeHtml(columnLabel(column))}</label>`
    ).join("") + `<p><button type="button" class="btn-ghost" data-action="video-columns-reset">Default columns</button></p>`;
}

function setMovieColumn(key, on) {
    const name = matrixColumnsKey();
    const list = (state.video[name] || []).filter((item) => item !== key);
    if (on) list.push(key);
    state.video[name] = name === "tvColumns" ? normalizeTvColumns(list) : normalizeMovieColumns(list);
    localStorage.setItem(name === "tvColumns" ? "curator.tvColumns" : "curator.movieColumns", JSON.stringify(state.video[name]));
    renderVideoList();
}

function sortMovies(key) {
    if (state.media === "sets") {
        const sort = state.video.setSort || { key: "name", dir: "asc" };
        state.video.setSort = { key, dir: sort.key === key && sort.dir === "asc" ? "desc" : "asc" };
        localStorage.setItem("curator.setSort", JSON.stringify(state.video.setSort));
        renderVideoList();
        return;
    }
    const tv = matrixMode() === "tv";
    const name = tv ? "tvSort" : "movieSort";
    const sort = state.video[name] || { key: "title", dir: "asc" };
    state.video[name] = { key, dir: sort.key === key && sort.dir === "asc" ? "desc" : "asc" };
    localStorage.setItem(tv ? "curator.tvSort" : "curator.movieSort", JSON.stringify(state.video[name]));
    renderVideoList();
}

function saveMatrixWidths() {
    const tv = matrixMode() === "tv";
    localStorage.setItem(tv ? "curator.tvWidths" : "curator.movieWidths", JSON.stringify(matrixWidths()));
}

function bindMatrixChrome(host) {
    const grid = host.querySelector(".vmatrix");
    host.querySelectorAll(".vm-resize").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const key = handle.dataset.col;
            const column = MOVIE_COLUMNS.find((item) => item.key === key);
            const startX = event.clientX;
            const start = matrixColumnWidth(column);
            const widths = matrixWidths();
            function move(next) {
                widths[key] = Math.max(48, Math.round(start + next.clientX - startX));
                grid.style.cssText = matrixTemplate(movieColumns()).style;
            }
            function end() {
                window.removeEventListener("pointermove", move);
                saveMatrixWidths();
            }
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", end, { once: true });
        });
    });
    host.querySelectorAll(".vm-head-cell[draggable='true']").forEach((cell) => {
        cell.addEventListener("dragstart", (event) => {
            state.video.dragColumn = cell.dataset.col;
            event.dataTransfer.effectAllowed = "move";
        });
        cell.addEventListener("dragover", (event) => {
            if (!state.video.dragColumn || cell.dataset.col === "title" || cell.dataset.col === "year") return;
            event.preventDefault();
        });
        cell.addEventListener("drop", (event) => {
            event.preventDefault();
            moveMatrixColumn(state.video.dragColumn, cell.dataset.col);
            state.video.dragColumn = "";
        });
    });
}

function moveMatrixColumn(from, to) {
    if (!from || !to || from === to || from === "title" || from === "year" || to === "title" || to === "year") return;
    const name = matrixColumnsKey();
    const list = (state.video[name] || []).slice();
    const fromAt = list.indexOf(from);
    const toAt = list.indexOf(to);
    if (fromAt < 0 || toAt < 0) return;
    list.splice(fromAt, 1);
    list.splice(toAt, 0, from);
    state.video[name] = name === "tvColumns" ? normalizeTvColumns(list) : normalizeMovieColumns(list);
    localStorage.setItem(name === "tvColumns" ? "curator.tvColumns" : "curator.movieColumns", JSON.stringify(state.video[name]));
    renderVideoList();
}

function openColumnFilter(button) {
    const key = button.dataset.col;
    const column = MOVIE_COLUMNS.find((item) => item.key === key);
    if (!column) return;
    const pop = document.getElementById("video-col-filter");
    const source = matrixMode() === "tv" && typeof visibleTvRows === "function" ? visibleTvRows(key) : movieMatchRows(key);
    const counts = new Map();
    source.forEach((row) => {
        const value = columnPlain(column, row);
        if (!value) return;
        counts.set(value, (counts.get(value) || 0) + 1);
    });
    const values = [...counts.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const picked = columnPicks(key);
    const allOn = !picked.length;
    pop.innerHTML = `<input type="search" id="video-col-filter-q" placeholder="Find values…" value="">
        <button type="button" class="col-opt${allOn ? " is-on" : ""}" data-action="video-col-filter-clear" data-col="${key}">
            <span class="col-check" aria-hidden="true"></span><span>All values (${source.length})</span>
        </button>
        ${values.map((value) => {
            const on = picked.includes(value);
            return `<button type="button" class="col-opt${on ? " is-on" : ""}" data-action="video-col-filter-toggle" data-col="${key}" data-value="${escapeHtml(value)}">
                <span class="col-check" aria-hidden="true"></span><span>${escapeHtml(value)} (${counts.get(value)})</span>
            </button>`;
        }).join("")}`;
    const rect = button.getBoundingClientRect();
    pop.style.left = `${Math.min(rect.left, window.innerWidth - 280)}px`;
    pop.style.top = `${rect.bottom + 4}px`;
    pop.classList.remove("hidden");
    const input = document.getElementById("video-col-filter-q");
    input.addEventListener("input", () => {
        const query = input.value.trim().toLowerCase();
        pop.querySelectorAll(".col-opt[data-value]").forEach((item) => {
            const value = String(item.dataset.value || "").toLowerCase();
            item.classList.toggle("hidden", !!query && !value.includes(query));
        });
    });
    input.focus();
}

function columnPicks(key) {
    const query = matrixFilters()[key];
    if (Array.isArray(query)) return query.map((value) => String(value));
    const text = String(query || "");
    return text ? [text] : [];
}

function writeColumnPicks(key, picks) {
    const name = matrixMode() === "tv" ? "tvFilters" : "movieFilters";
    state.video[name] = { ...(state.video[name] || {}) };
    if (picks.length) state.video[name][key] = picks;
    else delete state.video[name][key];
    // Tick the boxes first: a slow or failing list redraw must not leave the menu looking unchanged.
    paintColumnFilter(key);
    try {
        renderVideoList();
    } finally {
        paintColumnFilter(key);
    }
}

function paintColumnFilter(key) {
    const pop = document.getElementById("video-col-filter");
    if (!pop || pop.classList.contains("hidden")) return;
    const picked = columnPicks(key);
    pop.querySelectorAll(".col-opt").forEach((item) => {
        const value = item.dataset.value;
        const on = value ? picked.includes(value) : !picked.length;
        item.classList.toggle("is-on", on);
        const mark = item.querySelector(".col-check");
        if (mark) mark.textContent = "";
    });
}

function toggleColumnFilter(key, value) {
    if (!value) return;
    const picks = columnPicks(key);
    const next = picks.includes(value) ? picks.filter((item) => item !== value) : picks.concat(value);
    writeColumnPicks(key, next);
}

function clearColumnFilter(key) {
    writeColumnPicks(key, []);
}

function setColumnFilter(key, value) {
    writeColumnPicks(key, value ? [value] : []);
    document.getElementById("video-col-filter").classList.add("hidden");
}

function selectionCount(label, count) {
    return count > 1 ? `${label} (${count})` : label;
}

function paintVideoSelection() {
    const scrape = document.getElementById("video-batch-scrape");
    const reload = document.getElementById("video-batch-reload");
    if (!scrape || !reload) return;
    if (state.media === "sets") {
        const count = selectionChecked("set").size;
        ["video-batch-scrape", "video-batch-art", "video-batch-nfo", "video-batch-rename", "video-batch-subs", "video-batch-trailers", "video-batch-reload"].forEach((id) => {
            const button = document.getElementById(id);
            if (button) button.hidden = true;
        });
        const processed = document.getElementById("video-batch-processed");
        if (processed) {
            processed.hidden = !count;
            processed.textContent = selectionCount("Processed", count);
        }
        scrape.hidden = true;
        const sets = document.getElementById("video-sets-scrape");
        if (sets) sets.hidden = false;
        const setRemove = document.getElementById("video-sets-remove");
        const setDelete = document.getElementById("video-sets-delete");
        if (setRemove) {
            setRemove.hidden = !count;
            setRemove.textContent = selectionCount("Remove", count);
        }
        if (setDelete) {
            setDelete.hidden = !count;
            setDelete.textContent = selectionCount("Delete", count);
        }
        renderVideoSelectBar();
        return;
    }
    const count = matrixMode() === "tv" ? tvScopedKeys().length : selectionChecked("movie").size;
    const show = state.media === "movies" || state.media === "tv";
    ["video-batch-art", "video-batch-nfo", "video-batch-rename", "video-batch-subs", "video-batch-trailers", "video-batch-processed", "video-batch-reload"].forEach((id) => {
        const button = document.getElementById(id);
        if (button) button.hidden = !show || !count;
    });
    scrape.hidden = true;
    const art = document.getElementById("video-batch-art");
    const nfo = document.getElementById("video-batch-nfo");
    const rename = document.getElementById("video-batch-rename");
    const subs = document.getElementById("video-batch-subs");
    const trailers = document.getElementById("video-batch-trailers");
    const processed = document.getElementById("video-batch-processed");
    if (art) art.textContent = selectionCount("Artwork", count);
    if (nfo) nfo.textContent = selectionCount(".nfo", count);
    if (rename) rename.textContent = selectionCount("Rename", count);
    if (subs) subs.textContent = selectionCount("Subtitles", count);
    if (trailers) trailers.textContent = selectionCount("Trailers", count);
    if (processed) processed.textContent = selectionCount("Processed", count);
    reload.textContent = selectionCount("Rescan", count);
    const sets = document.getElementById("video-sets-scrape");
    if (sets) sets.hidden = state.media !== "sets";
    const setRemove = document.getElementById("video-sets-remove");
    const setDelete = document.getElementById("video-sets-delete");
    if (setRemove) setRemove.hidden = true;
    if (setDelete) setDelete.hidden = true;
    renderVideoSelectBar();
}

function videoSelectionFacts() {
    if (state.media === "movies") {
        const ids = selectionChecked("movie");
        const rows = (state.video.movies || []).filter((movie) => ids.has(movie.id));
        const fresh = rows.filter((movie) => movie.status === "NEW").length;
        const n = ids.size;
        return {
            n,
            noun: n === 1 ? "movie" : "movies",
            detail: fresh ? `${fresh} new` : "",
            buttons: n ? [["video-scrape-open", selectionCount("Scrape…", n), ""], ["video-batch-edit", selectionCount("Edit fields…", n), "btn-ghost", "movie"], ["video-batch-ratings", selectionCount("Update ratings", n), "btn-ghost"], ["video-batch-art", selectionCount("Artwork", n), "btn-ghost"], ["video-batch-cleanfanart", selectionCount("Clean artwork…", n), "btn-ghost"], ["video-batch-playerart", selectionCount("Update artwork in players…", n), "btn-ghost"], ["video-batch-nfo", selectionCount("Write .nfo", n), "btn-ghost"], ["video-batch-rename", selectionCount("Rename", n), "btn-ghost"], ["video-batch-subs", selectionCount("Subtitles", n), "btn-ghost"], ["video-batch-origlang", selectionCount("Original language", n), "btn-ghost"], ["video-batch-trailers", selectionCount("Trailers", n), "btn-ghost"], ["video-batch-themes", selectionCount("Theme songs", n), "btn-ghost"], ["video-batch-integrity", selectionCount("Quick integrity check", n), "btn-ghost"], ["video-batch-lock", selectionCount(videoSelectionAllLocked() ? "Unlock" : "Lock", n), "btn-ghost"], ["video-batch-processed", selectionCount("Processed", n), "btn-process"], ["video-batch-reload", n], ["video-batch-move", selectionCount("Move…", n), "btn-ghost"], ["video-select-clear", "Clear", "btn-ghost"], ["video-batch-delete", selectionCount("Remove…", n), "btn-ghost btn-remove"]] : [],
        };
    }
    if (state.media === "sets") {
        const ids = selectionChecked("set");
        const rows = (state.video.sets || []).filter((set) => ids.has(set.id));
        const movies = rows.reduce((sum, set) => sum + (Number(set.movie_count) || 0), 0);
        const n = ids.size;
        return {
            n,
            noun: n === 1 ? "set" : "sets",
            detail: movies ? `${movies} movie${movies === 1 ? "" : "s"} in the library` : "",
            buttons: n ? [["video-scrape-open", selectionCount("Scrape…", n), ""], ["video-batch-art", selectionCount("Artwork", n), "btn-ghost"], ["video-batch-cleanfanart", selectionCount("Clean artwork…", n), "btn-ghost"], ["video-batch-nfo", selectionCount("Write .nfo", n), "btn-ghost"], ["video-batch-lock", selectionCount(videoSelectionAllLocked() ? "Unlock" : "Lock", n), "btn-ghost"], ["video-batch-processed", selectionCount("Processed", n), "btn-process"], ["video-select-clear", "Clear", "btn-ghost"], ["video-set-delete", selectionCount("Remove…", n), "btn-ghost btn-remove"]] : [],
        };
    }
    if (state.media === "tv") {
        let shows = 0;
        let seasons = 0;
        let episodes = 0;
        // Everything that is ticked, and the part of it the footer actions work on (the scope boxes).
        const all = { show: 0, season: 0, episode: 0 };
        selectionChecked("tv").forEach((key) => {
            const kind = String(key).split(":")[0];
            if (all[kind] !== undefined) all[kind] += 1;
        });
        const scope = tvScope();
        shows = scope.show ? all.show : 0;
        seasons = scope.season ? all.season : 0;
        episodes = scope.episode ? all.episode : 0;
        const nouns = { show: ["show", "shows"], season: ["season", "seasons"], episode: ["episode", "episodes"] };
        const parts = [];
        const boxes = [];
        ["show", "season", "episode"].forEach((kind) => {
            if (!all[kind]) return;
            const text = `${all[kind]} ${nouns[kind][all[kind] === 1 ? 0 : 1]}`;
            parts.push(text);
            boxes.push(`<label class="scope-pick${scope[kind] ? "" : " is-off"}" title="Include the ${nouns[kind][1]} in what the buttons do"><input type="checkbox" data-tv-scope="${kind}" ${scope[kind] ? "checked" : ""}> ${text}</label>`);
        });
        if (state.video.tvCascading) {
            parts.push("counting seasons and episodes…");
            boxes.push(`<span class="muted">counting seasons and episodes…</span>`);
        }
        const total = all.show + all.season + all.episode;
        const n = shows + seasons + episodes;
        const buttons = [];
        if (n) {
            buttons.push(["video-scrape-open", selectionCount("Scrape…", n), ""]);
            if (shows) buttons.push(["video-batch-edit", selectionCount("Edit shows…", shows), "btn-ghost", "show"]);
            if (episodes) buttons.push(["video-batch-edit", selectionCount("Edit episodes…", episodes), "btn-ghost", "episode"]);
            // Seasons have no scores of their own, so only shows and episodes count here.
            if (shows + episodes) buttons.push(["video-batch-ratings", selectionCount("Update ratings", shows + episodes), "btn-ghost"]);
            buttons.push(["video-batch-art", selectionCount("Artwork", n), "btn-ghost"]);
            if (shows) buttons.push(["video-batch-cleanfanart", selectionCount("Clean artwork…", shows), "btn-ghost"]);
            if (shows) buttons.push(["video-batch-playerart", selectionCount("Update artwork in players…", shows), "btn-ghost"]);
            buttons.push(["video-batch-nfo", selectionCount("Write .nfo", n), "btn-ghost"]);
            buttons.push(["video-batch-rename", selectionCount("Rename", n), "btn-ghost"]);
            buttons.push(["video-batch-subs", selectionCount("Subtitles", n), "btn-ghost"]);
            buttons.push(["video-batch-origlang", selectionCount("Original language", n), "btn-ghost"]);
            const splitIds = typeof selectedSplitEpisodeIds === "function" ? selectedSplitEpisodeIds() : [];
            if (splitIds.length) {
                const files = splitTargets(splitIds).length;
                buttons.push(["video-batch-split", selectionCount("Split episodes", files), "btn-ghost"]);
            }
            if (shows || seasons) buttons.push(["video-batch-trailers", selectionCount("Trailers", n), "btn-ghost"]);
            if (shows || seasons || episodes) buttons.push(["video-batch-thumbs", selectionCount("Generate thumbs", episodes || n), "btn-ghost"]);
            if (shows) buttons.push(["video-batch-themes", selectionCount("Theme songs", shows), "btn-ghost"]);
            buttons.push(["video-batch-integrity", selectionCount("Quick integrity check", n), "btn-ghost"]);
            buttons.push(["video-batch-lock", selectionCount(videoSelectionAllLocked() ? "Unlock" : "Lock", n), "btn-ghost"]);
            buttons.push(["video-batch-processed", selectionCount("Processed", n), "btn-process"]);
            buttons.push(["video-batch-reload", n]);
            if (shows) buttons.push(["video-batch-move", selectionCount("Move…", shows), "btn-ghost"]);
            buttons.push(["video-select-clear", "Clear", "btn-ghost"]);
            buttons.push(["video-batch-delete", selectionCount("Remove…", n), "btn-ghost btn-remove"]);
        } else if (total) {
            buttons.push(["video-select-clear", "Clear", "btn-ghost"]);
        }
        return { n, total, noun: total === 1 ? "item" : "items", detail: parts.join(" · "), detailHtml: boxes.join(""), buttons };
    }
    return { n: 0, noun: "", detail: "", buttons: [] };
}

function renderVideoSelectBar() {
    const bar = document.getElementById("video-select-bar");
    if (!bar) return;
    paintVideoLegend();
    const facts = videoSelectionFacts();
    // With every kind un-ticked in the scope the bar stays up, so the boxes can be ticked again.
    const open = state.media !== "music" && (facts.total || facts.n) > 0;
    bar.classList.toggle("is-open", open);
    bar.setAttribute("aria-hidden", open ? "false" : "true");
    if (!open) {
        state.video.tvScope = null;
        return;
    }
    // "4 / 243" when the scope holds part of what is ticked, plain "243" when it holds all of it.
    document.getElementById("video-select-count").textContent = facts.total && facts.total !== facts.n ? `${facts.n} / ${facts.total}` : String(facts.n);
    document.getElementById("video-select-noun").textContent = facts.noun;
    const detail = document.getElementById("video-select-detail");
    if (facts.detailHtml) detail.innerHTML = facts.detailHtml;
    else detail.textContent = facts.detail;
    const primary = new Set(["video-scrape-open", "video-batch-reload", "video-batch-delete", "video-set-delete"]);
    const html = (items) => items.map(([action, label, cls, kind]) => {
        if (action === "video-batch-reload") return selectionRescanSplit(label);
        if (action === "video-batch-delete" || action === "video-set-delete") {
            // One red bin: its window asks whether to remove from the library or delete from disk.
            return `<button type="button" class="title-delete batch-trash" data-action="${action}" title="${escapeHtml(label)} - from the library or from disk" aria-label="${escapeHtml(label)}">${typeof trashSvg === "function" ? trashSvg() : "Remove"}</button>`;
        }
        return `<button type="button" class="${cls}" data-action="${action}"${kind ? ` data-kind="${escapeHtml(kind)}"` : ""}>${escapeHtml(label)}</button>`;
    }).join("");
    // The many small actions live in three drop-down menus so the footer stays one row tall.
    const groups = [
        ["Metadata", ["video-batch-edit", "video-batch-ratings", "video-batch-art", "video-batch-cleanfanart", "video-batch-playerart", "video-batch-nfo", "video-batch-rename"]],
        ["Media", ["video-batch-subs", "video-batch-origlang", "video-batch-trailers", "video-batch-thumbs", "video-batch-themes", "video-batch-split", "video-batch-integrity"]],
        ["Organize", ["video-batch-lock", "video-batch-processed", "video-batch-move"]],
    ];
    const grouped = new Set(groups.flatMap(([, actions]) => actions));
    const item = ([action, label, , kind]) => `<button type="button" class="group-item" data-action="${action}"${kind ? ` data-kind="${escapeHtml(kind)}"` : ""}>${escapeHtml(label)}</button>`;
    const menus = groups.map(([name, actions]) => {
        const rows = facts.buttons.filter((row) => actions.includes(row[0]));
        if (!rows.length) return "";
        return `<div class="scan-group rescan-split batch-group">
            <button type="button" class="btn-ghost group-btn" data-action="video-rescan-menu" aria-expanded="false">${name} ▾</button>
            <div class="scan-menu hidden">${rows.map(item).join("")}</div>
        </div>`;
    }).join("");
    const lead = facts.buttons.filter((row) => primary.has(row[0]) && !/delete/.test(row[0]));
    const tail = facts.buttons.filter((row) => primary.has(row[0]) && /delete/.test(row[0]));
    const rest = facts.buttons.filter((row) => !primary.has(row[0]) && !grouped.has(row[0]));
    document.getElementById("video-select-actions").innerHTML = `<div class="select-row select-row-main">${html(lead)}${menus}${html(rest)}${html(tail)}</div>`;
    if (typeof fitSelectBars === "function") fitSelectBars();
}

function selectionRescanSplit(count) {
    const mode = state.batchRescanMode || "deep";
    const labels = { incremental: "Incremental", full: "Full", deep: "Deep" };
    const menu = [["incremental", "Incremental"], ["full", "Full"], ["deep", "Deep"]].map(([value, name]) =>
        `<button type="button" data-action="video-rescan-mode" data-mode="${value}" class="${value === mode ? "active" : ""}">${name}</button>`
    ).join("");
    const text = `${selectionCount("Rescan", count)} | ${labels[mode] || "Deep"}`;
    return `<div class="scan-group rescan-split">
        <button type="button" class="scan-main" data-action="video-batch-reload" data-mode="${mode}" data-count="${count}">${escapeHtml(text)}</button>
        <button type="button" class="scan-caret" data-action="video-rescan-menu" aria-label="Choose scan mode" aria-expanded="false">▾</button>
        <div class="scan-menu hidden">${menu}</div>
    </div>`;
}

async function openMovie(id, keepScroll) {
    if (!keepScroll && state.video) state.video.keepCenterScroll = false;
    state.video.movieId = id;
    state.video.paintToken += 1;
    paintMovieRows();
    const center = document.getElementById("video-center");
    const token = (state.video.detailToken += 1);
    center.innerHTML = `<p class="muted vpad">Loading…</p>`;
    try {
        const movie = await api(`/api/v1/movies/${encodeURIComponent(id)}`);
        if (token !== state.video.detailToken) return;
        state.video.detail = movie;
        renderMovieInfo(movie);
    } catch (error) {
        if (state.video) state.video.keepCenterScroll = false;
        if (token === state.video.detailToken) center.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
    }
}

function videoHero(art, poster, body, owner, actions, options) {
    const wide = owner && owner.kind === "episode";
    const extra = options || {};
    const fallbacks = Array.isArray(extra.fallback)
        ? extra.fallback
        : (extra.fallback ? [extra.fallback] : []);
    const source = art || {};
    const pick = (key) => {
        if (source[key]) return source[key];
        for (const fb of fallbacks) {
            if (fb && fb[key]) return fb[key];
        }
        return "";
    };
    const banner = extra.banner !== undefined ? extra.banner : pick("banner");
    const landscape = extra.landscape !== undefined ? extra.landscape : pick("landscape");
    const logo = extra.clearlogo !== undefined ? extra.clearlogo : pick("clearlogo");
    const fanart = extra.fanart !== undefined ? extra.fanart : pick("fanart");
    const image = poster
        ? `<img class="vposter" src="${artUrl(poster, wide ? 780 : 342)}" alt="">`
        : `<div class="vposter is-empty">${wide ? "No thumbnail" : "No poster"}</div>`;
    const mark = owner && owner.missing ? `<div class="missing-sash">Episode missing</div>` : "";
    const cover = artFrame(image, owner, poster ? artUrl(poster) : "", wide ? "thumb" : "poster", mark, extra.progressHtml || "", extra.badges || "");
    const top = infoBanner({
        banner: banner ? artUrl(banner, 1000) : "",
        landscape: landscape ? artUrl(landscape, 780) : "",
        clearlogo: logo ? artUrl(logo, 500) : "",
    }, extra.actions || "");
    return `<div class="info-stack">${top}<div class="info-body">${infoFanart(fanart ? artUrl(fanart, 780) : "")}<div class="info-body-row"><div class="info-cover"><div class="vposter-col${wide ? " vthumb-col" : ""}">${cover}${actions || ""}</div></div><div class="info-copy vhero-text">${body}</div></div></div></div>`;
}

function scrapeCoverButtons(kind, item) {
    const id = escapeHtml(item.id);
    const locked = item.locked ? "disabled" : "";
    return `<button type="button" data-action="video-scrape-one" data-kind="${kind}" data-id="${id}" ${locked}>Scrape</button>`;
}

function rescanModes(kind) {
    return kind === "episode" ? [["full", "Full"], ["deep", "Deep"]] : [["incremental", "Incremental"], ["full", "Full"], ["deep", "Deep"]];
}

function rescanSplit(kind, attrs) {
    const menu = rescanModes(kind).map(([value, label]) =>
        `<button type="button" data-action="video-rescan-mode" data-mode="${value}" class="${value === "deep" ? "active" : ""}">${label}</button>`
    ).join("");
    return `<div class="scan-group rescan-split">
        <button type="button" class="scan-main" data-action="video-rescan" data-kind="${escapeHtml(kind)}" data-mode="deep" ${attrs}>Rescan | Deep</button>
        <button type="button" class="scan-caret" data-action="video-rescan-menu" aria-label="Choose scan mode" aria-expanded="false">▾</button>
        <div class="scan-menu hidden">${menu}</div>
    </div>`;
}

function coverActions(kind, item) {
    if (!item || isWanted(item)) return "";
    const id = escapeHtml(item.id);
    if (kind === "movie" || kind === "show") {
        const folder = kind === "movie" ? (item.folder || item.path) : item.path;
        const media = kind === "movie" ? "movies" : "tv";
        return `<div class="album-actions">
            ${rescanSplit(kind, `data-media="${media}" data-target="${escapeHtml(folder || "")}"`)}
            ${scrapeCoverButtons(kind, item)}
            <button type="button" data-action="video-move" data-kind="${kind}" data-id="${id}">Move…</button>
            <button type="button" data-action="video-match" data-kind="${kind}" data-id="${id}" ${item.locked ? "disabled" : ""}>Fix Match</button>
            ${item.match_undo ? `<button type="button" class="btn-ghost" data-action="video-match-undo" data-kind="${kind}" data-id="${id}" title="Put back the metadata, ${kind === "show" ? "seasons, episodes, " : ""}artwork and .nfo files from before the Fix Match of ${escapeHtml(String(item.match_undo.taken_at || "").slice(0, 10))}">Undo Fix Match</button>` : ""}
            <button type="button" data-action="video-art-fetch" data-kind="${kind}" data-id="${id}">Download missing artwork</button>
        </div>`;
    }
    if (kind === "season") {
        return `<div class="album-actions">
            ${rescanSplit("season", `data-id="${id}"`)}
            ${scrapeCoverButtons("season", item)}
            <button type="button" data-action="video-art-fetch" data-kind="season" data-id="${id}">Download missing artwork</button>
        </div>`;
    }
    if (kind === "set") {
        return `<div class="album-actions">
            <button type="button" data-action="video-scrape-one" data-kind="set" data-id="${id}" ${item.locked ? "disabled" : ""}>Scrape</button>
            <button type="button" data-action="video-match" data-kind="set" data-id="${id}" ${item.locked ? "disabled" : ""}>Fix Match</button>
            <button type="button" data-action="video-art-fetch" data-kind="set" data-id="${id}">Download missing set artwork</button>
        </div>`;
    }
    if (kind === "episode") {
        return `<div class="album-actions">
            ${rescanSplit("episode", `data-id="${id}"`)}
            ${scrapeCoverButtons("episode", item)}
            <button type="button" data-action="video-art-fetch" data-kind="episode" data-id="${id}">Download missing artwork</button>
        </div>`;
    }
    return "";
}

function renderMovieInfo(movie) {
    const art = movie.artwork || {};
    const file = movie.file || null;
    const edition = movieEdition(movie);
    const year = movie.year ? String(movie.year) : "";
    const title = infoTitle(escapeHtml(movie.title || "Untitled"), { kind: "movie", id: movie.id, locked: movie.locked });
    const genreLinks = clickableFilterLinks(movie.genres);
    const lineParts = [year ? `<button type="button" class="vlink-chip" data-action="video-filter-query" data-query="${escapeHtml(year)}">${escapeHtml(year)}</button>` : "", edition ? escapeHtml(edition) : "", escapeHtml(fmtRuntime(movie.runtime_minutes)), genreLinks].filter(Boolean);
    const line = lineParts.join(" · ");
    const rating = ratingMarks(movie);
    const setTarget = movie.set_id || movie.set_name;
    const set = movie.set_name
        ? `<button type="button" class="link" data-action="video-open-set" data-id="${escapeHtml(setTarget)}">${escapeHtml(movie.set_name)}</button>${movie.set_count ? ` <span class="muted">(${movie.set_count} movies)</span>` : ""}`
        : "";
    const heroSetBadge = movie.set_name
        ? ` <button type="button" class="tag-pill set-jump-pill" data-action="video-open-set" data-id="${escapeHtml(setTarget)}" title="Open movie set: ${escapeHtml(movie.set_name)}">Collection: ${escapeHtml(movie.set_name)}</button>`
        : "";
    const head = `${title}
        ${movie.original_title && movie.original_title !== movie.title ? `<p class="muted">${escapeHtml(movie.original_title)}</p>` : ""}
        <p class="vhero-edition">${certBadge(movie)}${line} ${rating}${heroSetBadge}</p>`;
    const body = `${brandRow(head, movie.studio_icons)}
        <div class="vchips vchips-art">${artMarks(movie.artwork, INFO_ART.movie)}${nfoChip("movie.nfo", movie.nfo_path, "movie", movie.id, movie.nfo_stale)}</div>
        <div class="vchips vchips-media">${fileChips(file ? { ...file, audio_main: briefAudio(file) } : null)}${videoStatus(movie, true)}</div>
        ${isWanted(movie) ? `<p class="muted">Waiting for the file.</p>` : ""}
        ${videoItemActions("movie", movie)}
        ${providerIdsRow(movie)}`;
    const facts = factRows([
        ["Set", set, true],
        ["Director", clickableFilterLinks(movie.directors), true],
        ["Writer", clickableFilterLinks(movie.writers), true],
        ["Studio", clickableFilterLinks(movie.studios), true],
        ["Country", clickableFilterLinks(movie.countries), true],
        ["Premiered", fmtDate(movie.premiered)],
        ["Certification", certFact(movie)],
        ["Tags", clickableFilterLinks(movie.tags), true],
        ["Top 250", movie.top250 || ""],
        ["Play count", movie.playcount || ""],
        ["Links", idLinks(movie), true],
    ]);
    const parts = (movie.parts || []).length > 1 ? `<p class="muted">Stacked in ${(movie.parts || []).length} parts: ${(movie.parts || []).map((part) => escapeHtml(part.split("/").pop())).join(", ")}</p>` : "";
    const disc = movie.disc_format ? `<p class="muted">${escapeHtml(movie.disc_format)} is a disc image folder, so there is no single video file to probe. CD1 and CD2 files are probed.</p>` : "";
    document.getElementById("video-center").innerHTML = `<article class="vinfo">
        ${videoHero(art, art.poster, body, { kind: "movie", id: movie.id }, coverActions("movie", movie), { actions: videoHeroActions("movie", movie), badges: posterFileBadges(file) })}
        <section class="vsection">${filePathBlock((movie.display_parts || []).length > 1 ? movie.display_parts : shownPath(movie, "file"))}${mediaFlagSection(movie)}${facts}</section>
        ${trailerSection(movie, { kind: "movie", id: movie.id })}
        <section class="vsection">${castHtml(movie.actors)}</section>
        ${isWanted(movie) ? "" : mediaInfoHtml(file, { kind: "movie", id: movie.id })}
        <section class="vsection"><h3>Artwork</h3>${artGallery(art, { kind: "movie", id: movie.id })}</section>
        ${isWanted(movie) ? "" : `<section class="vsection"><h3>Files</h3>${parts}${disc}
            ${factRows([["Folder", pathCell(shownPath(movie, "folder") || shownPath(movie)), true], ["NFO", movie.nfo_path ? pathCell(shownPath(movie, "nfo_path")) : "None", !!movie.nfo_path], ["Media info", file && file.mediainfo_path ? pathCell(shownPath(file, "mediainfo_path")) : "None", !!(file && file.mediainfo_path)]])}
        </section>`}
    </article>`;
    releaseCenterScroll();
}

function movieEdition(movie) {
    const edition = String(movie.edition || (movie.file && movie.file.edition) || "").trim();
    return edition && !/^none$/i.test(edition) ? edition : "";
}

function briefAudio(file) {
    const tracks = file.audio_tracks || [];
    const track = tracks.find((item) => item.default) || tracks[0];
    return track ? [track.codec, track.channels].filter(Boolean).join(" ") : "";
}

function moveMovieSelection(step) {
    const rows = state.video.rows || [];
    if (!rows.length) return;
    const index = rows.findIndex((movie) => movie.id === state.video.movieId);
    const next = Math.max(0, Math.min(rows.length - 1, index < 0 ? 0 : index + step));
    const host = document.getElementById("video-list");
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") {
        openMovie(rows[next].id);
        if (typeof vgridReveal === "function") vgridReveal(host, rows[next].id);
        const card = host && host.querySelector(`.vgrid-card[data-id="${CSS.escape(rows[next].id)}"]`);
        if (card) card.scrollIntoView({ block: "nearest" });
        return;
    }
    const head = host.querySelector(".vm-head");
    scrollRowIntoView(host, next, head ? head.offsetHeight : 0);
    openMovie(rows[next].id);
}

function noteScanStart(data) {
    if (data.queued) {
        notify(data.duplicate ? "That scan is already queued." : "Scan queued. It starts when the current scan finishes.", "info");
        return;
    }
    if (!data.started) {
        notify("A scan is already running.", "info");
        return;
    }
    applyVideoScan(data.scan || {});
    pollVideoScan();
}

async function runCoverRescan(action) {
    const mode = action.dataset.mode || "deep";
    const kind = action.dataset.kind;
    if (kind === "season") {
        const data = await api(`/api/v1/tv/seasons/${encodeURIComponent(action.dataset.id)}/rescan`, { method: "POST", body: { mode } });
        noteScanStart(data);
        return;
    }
    if (kind === "episode") {
        const data = await api(`/api/v1/tv/episodes/${encodeURIComponent(action.dataset.id)}/rescan`, { method: "POST", body: { mode: mode === "incremental" ? "deep" : mode } });
        noteScanStart(data);
        return;
    }
    const target = action.dataset.target || "";
    if (!target || target.indexOf("wanted://") === 0) {
        notify("This title has no folder to scan yet.", "info");
        return;
    }
    const data = await api("/api/v1/scan", {
        method: "POST",
        body: { media: action.dataset.media, mode, targets: [target] },
    });
    noteScanStart(data);
}

function rescanMenu(group) {
    const local = group.querySelector(":scope > .scan-menu");
    if (local) return local;
    return [...document.querySelectorAll("body > .scan-menu")].find((menu) => menu._rescanHome === group) || null;
}

function closeRescanMenus() {
    document.querySelectorAll("body > .scan-menu, .rescan-split > .scan-menu").forEach((menu) => {
        menu.classList.add("hidden");
        menu.style.position = "";
        menu.style.top = "";
        menu.style.bottom = "";
        menu.style.left = "";
        menu.style.right = "";
        menu.style.minWidth = "";
        menu.style.zIndex = "";
        menu.style.visibility = "";
        if (menu._rescanHome && menu.parentElement !== menu._rescanHome) menu._rescanHome.appendChild(menu);
    });
    document.querySelectorAll(".rescan-split .scan-caret, .rescan-split .group-btn").forEach((button) => button.setAttribute("aria-expanded", "false"));
}

function toggleRescanMenu(action) {
    const group = action.closest(".rescan-split");
    const menu = group && rescanMenu(group);
    if (!menu) return;
    const opening = menu.classList.contains("hidden");
    closeRescanMenus();
    if (!opening) return;
    menu._rescanHome = group;
    document.body.appendChild(menu);
    const rect = group.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.visibility = "hidden";
    menu.style.left = "0";
    menu.style.top = "0";
    menu.style.right = "auto";
    menu.style.bottom = "auto";
    menu.style.minWidth = `${rect.width}px`;
    menu.style.zIndex = "80";
    menu.classList.remove("hidden");
    const height = menu.offsetHeight;
    const width = menu.offsetWidth;
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUp = Boolean(group.closest(".batch-bar")) || spaceBelow < height + 12;
    let left = rect.left;
    if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
    menu.style.left = `${Math.max(8, left)}px`;
    menu.style.top = openUp ? `${Math.max(8, rect.top - height - 4)}px` : `${rect.bottom + 4}px`;
    menu.style.visibility = "";
    action.setAttribute("aria-expanded", "true");
}

function chooseRescanMode(action) {
    const menu = action.closest(".scan-menu");
    const group = action.closest(".rescan-split") || (menu && menu._rescanHome);
    const main = group && group.querySelector(".scan-main");
    if (!main) return;
    const labels = { incremental: "Incremental", full: "Full", deep: "Deep" };
    const mode = action.dataset.mode || "deep";
    main.dataset.mode = mode;
    if (main.dataset.action === "video-batch-reload" || main.dataset.action === "batch-rescan") {
        state.batchRescanMode = mode;
        main.textContent = `${selectionCount("Rescan", main.dataset.count)} | ${labels[mode] || "Deep"}`;
    } else {
        main.textContent = `Rescan | ${labels[mode] || "Deep"}`;
    }
    const buttons = menu ? menu.querySelectorAll("button") : group.querySelectorAll(".scan-menu button");
    buttons.forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
    closeRescanMenus();
}

async function deepRescanFolder(action) {
    const target = action.dataset.target || "";
    if (!target || target.indexOf("wanted://") === 0) {
        notify("This title has no folder to scan yet.", "info");
        return;
    }
    const data = await api("/api/v1/scan", {
        method: "POST",
        body: { media: action.dataset.media, mode: "deep", targets: [target] },
    });
    noteScanStart(data);
}

async function deepRescanSeason(action) {
    const data = await api(`/api/v1/tv/seasons/${encodeURIComponent(action.dataset.id)}/rescan`, { method: "POST", body: {} });
    noteScanStart(data);
}

async function deepRescanEpisode(action) {
    const data = await api(`/api/v1/tv/episodes/${encodeURIComponent(action.dataset.id)}/rescan`, { method: "POST", body: {} });
    noteScanStart(data);
}

function bindVideoAdd() {
    const form = document.getElementById("video-add-form");
    if (!form || form.dataset.bound) return;
    form.dataset.bound = "1";
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        runAction(searchVideoAdd, "Searching…");
    });
}

async function openVideoAdd() {
    if (state.media === "sets") {
        if (typeof openCreateSetModal === "function") return openCreateSetModal();
    }
    bindVideoAdd();
    const media = state.media === "tv" ? "tv" : "movies";
    const options = await api(`/api/v1/add/options?media=${encodeURIComponent(media)}`);
    const source = document.getElementById("video-add-source");
    const root = document.getElementById("video-add-root");
    source.innerHTML = (options.sources || []).map((item) =>
        `<option value="${escapeHtml(item.id)}" ${item.id === options.default ? "selected" : ""}>${escapeHtml(item.label)}</option>`
    ).join("");
    const roots = options.roots || [];
    root.innerHTML = roots.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
    root.hidden = roots.length < 2;
    const service = options.service || (media === "tv" ? "Sonarr" : "Radarr");
    document.getElementById("video-add-title").textContent = media === "tv" ? "Add a TV show to Sonarr" : "Add a movie to Radarr";
    document.getElementById("video-add-note").textContent = media === "tv"
        ? "Search TMDB or TheTVDB and pick the show. Sonarr is asked first. A wanted row is saved only when Sonarr accepts the show."
        : "Search TMDB and pick the movie. Radarr is asked first. A wanted row is saved only when Radarr accepts the movie.";
    const problem = document.getElementById("video-add-problem");
    problem.textContent = options.ready === false ? options.problem || `${service} cannot be reached.` : "";
    problem.classList.toggle("hidden", options.ready !== false);
    document.getElementById("video-add-search").checked = options.search !== false;
    document.getElementById("video-add-search-label").textContent = media === "tv"
        ? "Ask Sonarr to search for the missing episodes now"
        : "Ask Radarr to search for the movie now";
    document.getElementById("video-add-hint").textContent = `${service} adds the title either way. This only decides whether it starts looking for a release straight away. The tick follows Start a search right away under Settings, Integrations until you change it here.`;
    document.getElementById("video-add-query").value = "";
    document.getElementById("video-add-results").innerHTML = "";
    document.getElementById("video-add-modal").classList.remove("hidden");
    document.getElementById("video-add-query").focus();
}

async function searchVideoAdd() {
    const query = document.getElementById("video-add-query").value.trim();
    const source = document.getElementById("video-add-source").value;
    const media = state.media === "tv" ? "tv" : "movies";
    const box = document.getElementById("video-add-results");
    if (!query) {
        box.innerHTML = `<p class="muted">Type a title to search for.</p>`;
        return;
    }
    const params = new URLSearchParams({ media, query, source });
    const data = await api(`/api/v1/match/search?${params}`);
    const hits = data.results || [];
    box.innerHTML = hits.length ? hits.map((hit) => `<button type="button" class="vmatch-hit" data-action="video-add-pick" data-source="${escapeHtml(hit.source)}" data-id="${escapeHtml(hit.id)}" data-title="${escapeHtml(hit.title || "")}" data-year="${escapeHtml(hit.year ? String(hit.year) : "")}">
        ${hit.poster ? `<img src="${escapeHtml(hit.poster)}" alt="" referrerpolicy="no-referrer">` : ""}
        <span><strong>${escapeHtml(hit.title || "")}</strong>${hit.year ? ` <span class="muted">${escapeHtml(String(hit.year))}</span>` : ""}
        <small>${escapeHtml(hit.overview || "")}</small></span>
    </button>`).join("") : `<p class="muted">No matches.</p>`;
}

async function pickVideoAdd(action) {
    const media = state.media === "tv" ? "tv" : "movies";
    const year = action.dataset.year ? Number(action.dataset.year) : null;
    // The server lists the add in Jobs while it waits for Radarr or Sonarr; look soon so a short one is still seen.
    if (typeof schedulePoll === "function") schedulePoll(500);
    const data = await api("/api/v1/add", {
        method: "POST",
        body: {
            media,
            source: action.dataset.source,
            id: action.dataset.id,
            title: action.dataset.title,
            year: Number.isFinite(year) ? year : null,
            root: document.getElementById("video-add-root").value,
            search: document.getElementById("video-add-search").checked,
        },
    });
    document.getElementById("video-add-modal").classList.add("hidden");
    notify(data.message || "Added.", data.wanted || data.action ? "success" : "info");
    state.video.stale[media === "tv" ? "tv" : "movies"] = true;
    return loadVideo(media);
}
