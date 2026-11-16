/* The music library list as a table.
   A title bar with a master box sits over the list. Its columns sort, filter, resize and move the way the
   movie and TV tables do. tree.js draws the rows; this file knows what each column shows. */

function musicRead(key, fallback) {
    try {
        const value = JSON.parse(localStorage.getItem(key) || "null");
        return value == null ? fallback : value;
    } catch (error) {
        return fallback;
    }
}

function musicWrite(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        /* The choice lasts until the page is closed. */
    }
}

const MUSIC_TYPE_NAMES = { album: "Album", ep: "EP", single: "Single", live: "Live", compilation: "Compilation", unknown: "" };

function musicRateLabel(hz, unit = true) {
    const value = Number(hz) || 0;
    if (!value) return "";
    const khz = value / 1000;
    const text = Number.isInteger(khz) ? String(khz) : String(Math.round(khz * 10) / 10);
    return unit ? `${text} kHz` : text;
}

/* "FLAC 24/96" for lossless, "MP3 320" for lossy, "Mixed" when the tracks differ. */
function musicQualityLabel(album) {
    const format = String((album && album.audio_format) || "");
    if (!format) return "";
    if (format.includes("/")) return album.audio_lossless ? "Mixed lossless" : "Mixed";
    const depth = Number(album.audio_bit_depth) || 0;
    const rate = Number(album.audio_sample_rate) || 0;
    const kbps = Number(album.audio_bitrate) || 0;
    if (album.audio_lossless) return depth && rate ? `${format} ${depth}/${musicRateLabel(rate, false)}` : format;
    return kbps ? `${format} ${kbps}` : format;
}

function musicQualityTitle(album) {
    const format = String((album && album.audio_format) || "");
    if (!format) return "";
    const parts = [format, album.audio_bit_depth ? `${album.audio_bit_depth}-bit` : "", album.audio_sample_rate ? musicRateLabel(album.audio_sample_rate) : "",
        album.audio_bitrate ? `${album.audio_bitrate} kb/s` : ""].filter(Boolean);
    return `${parts.join(", ")}. ${album.audio_lossless ? "Lossless" : "Not lossless"}. The weakest track sets the bit depth and sample rate; the bitrate is the average.`;
}

function musicMatchLabel(album) {
    const tier = (album && album.match_tier) || "unmatched";
    if (tier === "gold") return "100% match";
    if (tier === "silver") return "Partial match";
    return "Unmatched";
}

function musicMatchRank(album) {
    const tier = (album && album.match_tier) || "unmatched";
    const ratio = Number(album && album.match_ratio) || 0;
    return (tier === "gold" ? 3000 : tier === "silver" ? 2000 : 1000) + ratio;
}

function musicProcessedLabel(row) {
    return row.status === "IGNORED" ? "Ignored" : row.status === "PROCESSED" ? "Processed" : "Not processed";
}

function musicProcessedHtml(row) {
    if (row.status === "IGNORED") return `<span class="tag-pill" title="Left out of scans and scrapes">Ignored</span>`;
    return row.status === "PROCESSED"
        ? `<span class="process-mark ok" title="Processed">✓</span>`
        : `<span class="process-mark bad" title="Not processed">✕</span>`;
}

function musicDateWords(value) {
    const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : "";
}

function musicCoverLabel(row) {
    const width = Number(row && row.artwork_width) || 0;
    const height = Number(row && row.artwork_height) || 0;
    if (width && height) return `${width}×${height}`;
    return row && row.has_artwork ? "Yes" : "";
}

function musicSum(artist, field) {
    return (artist.albums || []).reduce((sum, album) => sum + (Number(album[field]) || 0), 0);
}

function musicArtistFormats(artist) {
    const found = new Set();
    (artist.albums || []).forEach((album) => String(album.audio_format || "").split("/").filter(Boolean).forEach((name) => found.add(name)));
    return [...found].sort().join("/");
}

const MUSIC_COLUMNS = [
    { key: "name", label: "Artist / album", width: 340, fixed: true, filter: false,
        get: (a) => a.title || "" },
    { key: "status", label: "Status", width: 240,
        get: (a) => albumStatusTokens(a).join(", "), tokens: (a) => albumStatusTokens(a), sort: (a) => albumStatusTokens(a).join(", ").toLowerCase() || null,
        html: (a) => (albumStatusHtml(a) ? `<span class="tree-pills">${albumStatusHtml(a)}</span>` : ""),
        artistHtml: (artist) => (artistStatusHtml(artist) ? `<span class="tree-pills">${artistStatusHtml(artist)}</span>` : ""),
        artistSort: (artist) => artistStatusTokens(artist).join(", ").toLowerCase() || null },
    { key: "year", label: "Year", width: 68, cls: "num",
        get: (a) => String(sortYear(a) || ""), sort: (a) => sortYear(a) || null },
    { key: "type", label: "Type", width: 96,
        get: (a) => MUSIC_TYPE_NAMES[a.type] || "", sort: (a) => (MUSIC_TYPE_NAMES[a.type] || "").toLowerCase() || null },
    { key: "edition", label: "Edition", width: 120, ui: "ui_music_edition_badge",
        get: (a) => a.version || "", sort: (a) => String(a.version || "").toLowerCase() || null },
    { key: "tracks", label: "Tracks", width: 78, cls: "num",
        get: (a) => (a.total_tracks ? String(a.total_tracks) : ""), sort: (a) => Number(a.total_tracks) || null,
        artistGet: (artist) => String(musicSum(artist, "total_tracks") || ""), artistSort: (artist) => musicSum(artist, "total_tracks") || null },
    { key: "length", label: "Length", width: 84, cls: "num", filter: false,
        get: (a) => fmtDuration(a.duration_seconds), sort: (a) => Number(a.duration_seconds) || null,
        artistGet: (artist) => fmtDuration(musicSum(artist, "duration_seconds")), artistSort: (artist) => musicSum(artist, "duration_seconds") || null },
    { key: "format", label: "Format", width: 84,
        get: (a) => a.audio_format || "", tokens: (a) => String(a.audio_format || "").split("/").filter(Boolean), sort: (a) => a.audio_format || null,
        html: (a) => String(a.audio_format || "").split("/").filter(Boolean).map((format) => musicBadge("format", format, format.toUpperCase(), musicFormatClass(format))).join(""),
        artistGet: (artist) => musicArtistFormats(artist),
        artistHtml: (artist) => musicArtistFormats(artist).split("/").filter(Boolean).map((format) => musicBadge("format", format, format.toUpperCase(), musicFormatClass(format))).join("") },
    { key: "quality", label: "Quality", width: 128,
        get: (a) => musicQualityLabel(a), sort: (a) => (a.audio_format ? Number(a.quality_rank) || 0 : null),
        html: (a) => musicBadge("quality", musicQualityLabel(a), musicQualityLabel(a), a.audio_lossless ? "badge-lossless" : "badge-audio"), title: (a) => musicQualityTitle(a) },
    { key: "bit_depth", label: "Bits", width: 66, cls: "num",
        get: (a) => (a.audio_bit_depth ? String(a.audio_bit_depth) : ""), sort: (a) => Number(a.audio_bit_depth) || null,
        html: (a) => (a.audio_bit_depth ? musicBadge("bit_depth", String(a.audio_bit_depth), `${a.audio_bit_depth}-bit`, "badge-channels") : "") },
    { key: "sample_rate", label: "Sample rate", width: 112, cls: "num",
        get: (a) => musicRateLabel(a.audio_sample_rate), sort: (a) => Number(a.audio_sample_rate) || null,
        html: (a) => musicBadge("sample_rate", musicRateLabel(a.audio_sample_rate), musicRateLabel(a.audio_sample_rate), "badge-channels") },
    { key: "bitrate", label: "Bitrate", width: 98, cls: "num",
        get: (a) => (a.audio_bitrate ? `${a.audio_bitrate} kb/s` : ""), sort: (a) => Number(a.audio_bitrate) || null,
        html: (a) => (a.audio_bitrate ? musicBadge("bitrate", `${a.audio_bitrate} kb/s`, `${a.audio_bitrate} kb/s`, "badge-audio") : "") },
    { key: "match", label: "Match", width: 120,
        get: (a) => musicMatchLabel(a), sort: (a) => musicMatchRank(a),
        html: (a) => `<span class="match-icon ${escapeHtml(a.match_tier || "unmatched")}">${matchIcon(a.match_tier)}</span> ${escapeHtml(a.match_tier === "silver" && a.match_ratio ? `${a.match_ratio}% match` : musicMatchLabel(a))}` },
    { key: "country", label: "Country", width: 92, align: "center",
        get: (a) => a.country || "", sort: (a) => String(a.country || "").toLowerCase() || null,
        html: (a) => countryFlag(a.country) || escapeHtml(a.country || "") },
    { key: "label", label: "Label", width: 150,
        get: (a) => a.label || "", sort: (a) => String(a.label || "").toLowerCase() || null },
    { key: "catalog", label: "Catalog no.", width: 110,
        get: (a) => a.catalog || "", sort: (a) => String(a.catalog || "").toLowerCase() || null },
    { key: "release_status", label: "Release status", width: 100,
        get: (a) => a.release_status || "", sort: (a) => String(a.release_status || "").toLowerCase() || null },
    { key: "added", label: "Added", width: 92, ui: "ui_music_date_added",
        get: (a) => musicDateWords(a.created_at), tokens: (a) => [musicDateWords(a.created_at).slice(0, 7)].filter(Boolean), sort: (a) => timeStamp(a.created_at) || null,
        artistGet: (artist) => musicDateWords(artist.created_at), artistSort: (artist) => musicArtistAdded(artist) || null },
    { key: "modified", label: "Modified", width: 92,
        get: (a) => musicDateWords(a.updated_at), tokens: (a) => [musicDateWords(a.updated_at).slice(0, 7)].filter(Boolean), sort: (a) => timeStamp(a.updated_at) || null,
        artistGet: (artist) => musicDateWords(artist.updated_at), artistSort: (artist) => timeStamp(artist.updated_at) || null },
    { key: "processed", label: "Processed", width: 106, align: "center", ui: "ui_music_processed",
        get: (a) => musicProcessedLabel(a), sort: (a) => (a.status === "PROCESSED" ? 2 : a.status === "IGNORED" ? 1 : 0),
        html: (a) => musicProcessedHtml(a), artistHtml: (artist) => musicProcessedHtml(artist),
        artistGet: (artist) => musicProcessedLabel(artist), artistSort: (artist) => (artist.status === "PROCESSED" ? 2 : artist.status === "IGNORED" ? 1 : 0) },
    { key: "cover", label: "Cover", width: 96,
        get: (a) => musicCoverLabel(a) || "No cover", sort: (a) => (Number(a.artwork_width) || 0) * (Number(a.artwork_height) || 0) || null,
        artistGet: (artist) => musicCoverLabel(artist), artistSort: (artist) => (Number(artist.artwork_width) || 0) * (Number(artist.artwork_height) || 0) || null },
    { key: "nfo", label: "NFO", width: 66, align: "center",
        get: (a) => (a.has_nfo ? "Yes" : "No"), sort: (a) => (a.has_nfo ? 1 : 0),
        html: (a) => (a.has_nfo ? "✓" : "—"), artistHtml: (artist) => (artist.has_nfo ? "✓" : "—"),
        artistSort: (artist) => (artist.has_nfo ? 1 : 0) },
    { key: "path", label: "Path", width: 360, filter: false,
        get: (a) => a.path || "", sort: (a) => String(a.path || "").toLowerCase() || null,
        artistGet: (artist) => artist.path || "" },
];
const MUSIC_LOSSLESS = new Set(["flac", "alac", "wav", "aiff", "aif", "ape", "wv", "dsd", "dsf", "dff"]);

function musicFormatClass(format) {
    return MUSIC_LOSSLESS.has(String(format || "").toLowerCase()) ? "badge-lossless" : "badge-audio";
}

/* A quality badge in the info panel colours. Clicking it filters the column on its value. */
function musicBadge(key, value, text, cls) {
    if (!value) return "";
    return `<span class="vhdr vhdr-filter ${cls}" data-action="music-col-badge" data-col="${key}" data-value="${escapeHtml(value)}" title="Filter by this">${escapeHtml(text)}</span>`;
}

/* A badge sets its column's filter to its value. Clicking the badge that is the whole filter clears it. Badges in
   different columns combine: FLAC in Format, then 24-bit in Bits, keeps 24-bit FLAC albums. */
function musicBadgeFilter(key, value) {
    if (!key || !value) return;
    const picks = musicFilterPicks(key);
    writeMusicFilterPicks(key, picks.length === 1 && picks[0] === value ? [] : [value]);
}

/* An artist counts from its newest album, so a new album brings the artist up when sorting on Added. */
function musicArtistAdded(artist) {
    return Math.max(timeStamp(artist && artist.created_at), ...((artist && artist.albums) || []).map((album) => timeStamp(album.created_at)));
}

/* Latest added sorts on Added, newest first. Leaving it puts back the earlier sort when Added is still the sort. */
function musicLatestSort(on) {
    const current = musicActiveSort();
    if (on) {
        if (!current || current.key !== "added" || current.dir !== "desc") state.musicSortBeforeLatest = current;
        state.musicSort = { key: "added", dir: "desc" };
    } else if (current && current.key === "added" && current.dir === "desc") {
        state.musicSort = state.musicSortBeforeLatest || null;
        state.musicSortBeforeLatest = null;
    } else {
        return;
    }
    musicWrite("curator.musicSort", state.musicSort);
}

const MUSIC_DEFAULT_COLUMNS = ["status", "tracks", "format", "quality", "sample_rate", "bitrate", "edition", "added", "processed", "country"];

function musicColumnByKey(key) {
    return MUSIC_COLUMNS.find((column) => column.key === key) || null;
}

function normalizeMusicColumns(list) {
    const out = [];
    (Array.isArray(list) ? list : []).forEach((key) => {
        const column = musicColumnByKey(key);
        if (column && !column.fixed && !out.includes(key)) out.push(key);
    });
    return out;
}

function musicColumnHidden(column) {
    if (!column.ui || typeof videoCfg !== "function") return false;
    return videoCfg()[column.ui] === false;
}

function musicColumns() {
    const wanted = (state.musicColumns || MUSIC_DEFAULT_COLUMNS).map(musicColumnByKey).filter((column) => column && !musicColumnHidden(column));
    return [MUSIC_COLUMNS[0]].concat(wanted);
}

function musicColumnWidth(column) {
    const saved = Number((state.musicWidths || {})[column.key]);
    return saved >= 48 ? saved : column.width;
}

function musicTemplate(columns) {
    const widths = columns.map(musicColumnWidth);
    return { cols: widths.map((width) => `${width}px`).join(" "), total: widths.reduce((sum, width) => sum + width, 0) };
}

/* What a row shows in one column. The cell is the same for an album and for an artist; an artist's
   cell is blank where a total would mean nothing. */
function musicAlbumCellHtml(column, album) {
    const content = column.html ? column.html(album) : escapeHtml(column.get(album));
    const hint = column.title ? column.title(album) : (column.key === "path" ? album.path : "");
    const title = hint ? ` title="${escapeHtml(hint)}"` : "";
    const align = column.cls || (column.align === "center" ? "center" : "");
    return `<span class="mm-cell ${align}" data-col="${column.key}"${title}>${content}</span>`;
}

function musicArtistCellHtml(column, artist) {
    let content = "";
    if (column.artistHtml) content = column.artistHtml(artist);
    else if (column.artistGet) content = escapeHtml(column.artistGet(artist));
    const hint = column.key === "path" ? artist.path : "";
    const title = hint ? ` title="${escapeHtml(hint)}"` : "";
    const align = column.cls || (column.align === "center" ? "center" : "");
    return `<span class="mm-cell ${align}" data-col="${column.key}"${title}>${content}</span>`;
}

function musicBlankCellsHtml(columns, fill) {
    return columns.slice(1).map((column) => `<span class="mm-cell" data-col="${column.key}">${fill && fill[column.key] ? fill[column.key] : ""}</span>`).join("");
}

/* ── Sorting and filtering ─────────────────────────────────────────────────────────── */

function musicActiveSort() {
    const sort = state.musicSort;
    return sort && musicColumnByKey(sort.key) ? sort : null;
}

function musicBlank(value) {
    return value == null || value === "" || (typeof value === "number" && Number.isNaN(value));
}

function musicCompare(left, right) {
    if (typeof left === "number" && typeof right === "number") return left - right;
    return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
}

function musicSortList(items, keyOf, dir, tie) {
    return items.slice().sort((x, y) => {
        const a = keyOf(x);
        const b = keyOf(y);
        const blankA = musicBlank(a);
        const blankB = musicBlank(b);
        if (blankA !== blankB) return blankA ? 1 : -1;
        if (!blankA) {
            const order = musicCompare(a, b);
            if (order) return dir * order;
        }
        return tie(x, y);
    });
}

/* The best of an artist's albums for the sort: the lowest value when the order is rising, the highest when falling. */
function musicArtistKey(column, artist, albums, dir) {
    if (column.artistSort) return column.artistSort({ ...artist, albums });
    const values = albums.map((album) => column.sort(album)).filter((value) => !musicBlank(value));
    if (!values.length) return null;
    return values.reduce((best, value) => (dir * musicCompare(value, best) < 0 ? value : best));
}

/* rows: [{ artist, albums }] already in the default order. A column sort puts the albums of each artist in order, then
   the artists by their best album. Rows without a value for the column go last whichever way it runs. */
function musicApplyColumnSort(rows) {
    const sort = musicActiveSort();
    if (!sort) return rows;
    const column = musicColumnByKey(sort.key);
    const dir = sort.dir === "desc" ? -1 : 1;
    const albumTie = (a, b) => {
        const years = (sortYear(a) || 9999) - (sortYear(b) || 9999);
        return years || librarySortName(a.title).localeCompare(librarySortName(b.title), undefined, { sensitivity: "base" });
    };
    const artistTie = (a, b) => compareArtistNames(a.artist.name, b.artist.name);
    if (column.key === "name") return rows.slice().sort((a, b) => dir * artistTie(a, b));
    const sorted = rows.map((row) => ({ ...row, albums: musicSortList(row.albums, (album) => column.sort(album), dir, albumTie) }));
    const keyed = new Map(sorted.map((row) => [row, musicArtistKey(column, row.artist, row.albums, dir)]));
    return musicSortList(sorted, (row) => keyed.get(row), dir, artistTie);
}

function musicColumnTokens(column, album) {
    let tokens;
    try {
        tokens = column.tokens ? column.tokens(album) : [column.get(album)];
    } catch (error) {
        tokens = [];
    }
    return (tokens || []).map((token) => String(token)).filter(Boolean);
}

function musicFilterActive(picks) {
    return Array.isArray(picks) && picks.length > 0;
}

function musicFilterEntries(except) {
    return Object.entries(state.musicFilters || {}).filter(([key, picks]) => key !== except && musicFilterActive(picks) && musicColumnByKey(key));
}

function musicAlbumPasses(album, entries) {
    return entries.every(([key, picks]) => {
        const tokens = musicColumnTokens(musicColumnByKey(key), album);
        return picks.some((pick) => tokens.includes(pick));
    });
}

/* The search box, on the loaded list: the same rule the server used. An artist whose name matches keeps every album;
   otherwise only albums (and missing releases) whose title matches stay, and an artist with none left is dropped. */
function musicSearchArtists(artists, query) {
    const needle = String(query == null ? state.query || "" : query).trim().toLowerCase();
    if (!needle) return artists;
    const hit = (text) => String(text || "").toLowerCase().includes(needle);
    const found = [];
    for (const artist of artists || []) {
        if (hit(artist.name)) {
            found.push(artist);
            continue;
        }
        const albums = (artist.albums || []).filter((album) => hit(album.title));
        const missing = (artist.missing_releases || []).filter((release) => hit(release.title));
        if (!albums.length && !missing.length) continue;
        const row = { ...artist, albums };
        if (artist.missing_releases) row.missing_releases = missing;
        found.push(row);
    }
    return found;
}

/* Artists with only the albums that pass the search and every column filter. An artist with none left is dropped. */
function applyMusicColumnFilters(artists, except) {
    artists = musicSearchArtists(artists);
    const entries = musicFilterEntries(except);
    if (!entries.length) return artists;
    return artists
        .map((artist) => ({ ...artist, albums: (artist.albums || []).filter((album) => musicAlbumPasses(album, entries)) }))
        .filter((artist) => artist.albums.length);
}

function musicColumnFiltersOn() {
    return musicFilterEntries().length > 0;
}

function clearMusicColumnFilters() {
    if (!musicColumnFiltersOn()) return false;
    state.musicFilters = {};
    return true;
}

/* ── Title bar ─────────────────────────────────────────────────────────────────────── */

function musicHeadHtml(columns) {
    const sort = musicActiveSort() || {};
    const template = musicTemplate(columns);
    const cells = columns.map((column) => {
        const mark = sort.key === column.key ? (sort.dir === "desc" ? " ▾" : " ▴") : "";
        const picks = (state.musicFilters || {})[column.key];
        const filtered = musicFilterActive(picks);
        const pinned = column.fixed ? "" : ` draggable="true"`;
        const box = column.key === "name"
            ? `<input type="checkbox" class="mm-master" data-action="music-col-check-all" title="Select the albums on screen" aria-label="Select the albums on screen">`
            : "";
        const filter = column.filter === false ? "" : `<button type="button" class="vm-filter${filtered ? " is-on" : ""}" data-action="music-col-filter" data-col="${column.key}" title="Filter ${escapeHtml(column.label)}" aria-label="Filter ${escapeHtml(column.label)}">▾</button>`;
        const hint = filtered ? ` title="Filtered: ${escapeHtml(picks.join(", "))}"` : "";
        const align = column.cls === "num" ? " num" : column.align === "center" ? " center" : "";
        return `<span class="vm-cell vm-head-cell mm-head-cell${align}${filtered ? " is-filtered" : ""}" data-col="${column.key}"${hint}${pinned}>
            ${box}<button type="button" class="vm-sort" data-action="music-col-sort" data-col="${column.key}" title="Sort by ${escapeHtml(column.label)}">${escapeHtml(column.label)}${mark}</button>${filter}
            <span class="vm-resize" data-col="${column.key}" title="Drag to resize"></span>
        </span>`;
    }).join("");
    return `<div class="vm-head mm-head-row" role="row" style="--vm-cols:${template.cols};min-width:${template.total}px">${cells}</div>`;
}

/* show=false hides the bar: the poster grid, an empty library, the loading screen. */
function renderMusicHead(show) {
    const head = document.getElementById("music-head");
    if (!head) return;
    head.classList.toggle("hidden", !show);
    if (!show) return;
    head.innerHTML = musicHeadHtml(musicColumns());
    bindMusicHead(head);
    syncMusicHeadScroll();
    syncMusicMasterBox();
}

function syncMusicHeadScroll() {
    const head = document.getElementById("music-head");
    const tree = document.getElementById("tree");
    if (!head || !tree) return;
    head.style.paddingRight = `${Math.max(0, tree.offsetWidth - tree.clientWidth)}px`;
    head.scrollLeft = tree.scrollLeft;
}

function musicShownAlbumIds() {
    return applyMusicColumnFilters(state.artists || []).flatMap((artist) => (artist.albums || []).map((album) => album.id));
}

function syncMusicMasterBox() {
    const box = document.querySelector("#music-head .mm-master");
    if (!box) return;
    const ids = musicShownAlbumIds();
    const picked = ids.filter((id) => state.selected.has(id)).length;
    box.disabled = ids.length === 0;
    box.checked = ids.length > 0 && picked === ids.length;
    box.indeterminate = picked > 0 && picked < ids.length;
}

/* The master box adds the albums on screen to the selection, or takes them out. Albums a filter hides keep their tick. */
function selectShown(on) {
    musicShownAlbumIds().forEach((id) => selectionSet("album", id, on));
    state.contextAlbumIds = null;
    renderTree();
    renderBatchBar();
    if (typeof refreshOpenLookup === "function") refreshOpenLookup();
}

function setMusicSort(key) {
    const sort = musicActiveSort();
    const rising = sort && sort.key === key && sort.dir === "asc";
    state.musicSort = { key, dir: rising ? "desc" : "asc" };
    musicWrite("curator.musicSort", state.musicSort);
    renderTree();
}

function clearMusicSort() {
    if (!state.musicSort) return;
    state.musicSort = null;
    musicWrite("curator.musicSort", null);
}

function saveMusicColumns() {
    musicWrite("curator.musicColumns", state.musicColumns);
}

function setMusicColumn(key, on) {
    const list = (state.musicColumns || []).filter((item) => item !== key);
    if (on) list.push(key);
    state.musicColumns = normalizeMusicColumns(list);
    saveMusicColumns();
    renderTree();
}

function moveMusicColumn(from, to) {
    if (!from || !to || from === to) return;
    const list = (state.musicColumns || []).slice();
    const fromAt = list.indexOf(from);
    const toAt = list.indexOf(to);
    if (fromAt < 0 || toAt < 0) return;
    list.splice(fromAt, 1);
    list.splice(toAt, 0, from);
    state.musicColumns = normalizeMusicColumns(list);
    saveMusicColumns();
    renderTree();
}

function renderMusicColumnsMenu() {
    const menu = document.getElementById("music-columns-menu");
    if (!menu) return;
    const selected = state.musicColumns || [];
    menu.innerHTML = MUSIC_COLUMNS.filter((column) => !column.fixed && !musicColumnHidden(column)).map((column) =>
        `<label class="choice"><input type="checkbox" data-music-col="${column.key}" ${selected.includes(column.key) ? "checked" : ""}> ${escapeHtml(column.label)}</label>`
    ).join("") + `<p><button type="button" class="btn-ghost" data-action="music-col-reset">Default columns</button></p>`;
}

function closeMusicColumns() {
    const menu = document.getElementById("music-columns-menu");
    const button = document.getElementById("music-columns-btn");
    if (menu) menu.classList.add("hidden");
    if (button) button.setAttribute("aria-expanded", "false");
}

function toggleMusicColumns() {
    const menu = document.getElementById("music-columns-menu");
    if (!menu) return;
    const opening = menu.classList.contains("hidden");
    if (opening) renderMusicColumnsMenu();
    menu.classList.toggle("hidden", !opening);
    const button = document.getElementById("music-columns-btn");
    if (button) button.setAttribute("aria-expanded", opening ? "true" : "false");
}

function applyMusicTemplate() {
    const columns = musicColumns();
    const template = musicTemplate(columns);
    const head = document.querySelector("#music-head .mm-head-row");
    if (head) {
        head.style.setProperty("--vm-cols", template.cols);
        head.style.minWidth = `${template.total}px`;
    }
    const spacer = document.querySelector("#tree .tree-spacer");
    if (spacer) {
        spacer.style.setProperty("--mm-cols", template.cols);
        spacer.style.minWidth = `${template.total}px`;
    }
}

function bindMusicHead(head) {
    head.querySelectorAll(".vm-resize").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const key = handle.dataset.col;
            const column = musicColumnByKey(key);
            if (!column) return;
            const startX = event.clientX;
            const start = musicColumnWidth(column);
            state.musicWidths = state.musicWidths || {};
            const move = (next) => {
                state.musicWidths[key] = Math.max(48, Math.round(start + next.clientX - startX));
                applyMusicTemplate();
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", () => {
                window.removeEventListener("pointermove", move);
                musicWrite("curator.musicWidths", state.musicWidths);
            }, { once: true });
        });
    });
    head.querySelectorAll(".mm-head-cell[draggable='true']").forEach((cell) => {
        cell.addEventListener("dragstart", (event) => {
            state.musicDragColumn = cell.dataset.col;
            event.dataTransfer.effectAllowed = "move";
        });
        cell.addEventListener("dragover", (event) => {
            if (state.musicDragColumn && cell.dataset.col !== "name") event.preventDefault();
        });
        cell.addEventListener("drop", (event) => {
            event.preventDefault();
            moveMusicColumn(state.musicDragColumn, cell.dataset.col);
            state.musicDragColumn = "";
        });
    });
}

/* ── Column filter pop-up ──────────────────────────────────────────────────────────── */

function musicFilterPicks(key) {
    const picks = (state.musicFilters || {})[key];
    return Array.isArray(picks) ? picks.map(String) : [];
}

function writeMusicFilterPicks(key, picks) {
    state.musicFilters = { ...(state.musicFilters || {}) };
    if (picks.length) state.musicFilters[key] = picks;
    else delete state.musicFilters[key];
    // Tick the boxes first: a slow redraw must not leave the menu looking unchanged.
    paintMusicColumnFilter(key);
    try {
        renderTree();
    } finally {
        paintMusicColumnFilter(key);
    }
}

function paintMusicColumnFilter(key) {
    const pop = document.getElementById("music-col-filter");
    if (!pop || pop.classList.contains("hidden")) return;
    const picked = musicFilterPicks(key);
    pop.querySelectorAll(".col-opt").forEach((item) => {
        const value = item.dataset.value;
        item.classList.toggle("is-on", value ? picked.includes(value) : !picked.length);
    });
}

function openMusicColumnFilter(button) {
    const key = button.dataset.col;
    const column = musicColumnByKey(key);
    const pop = document.getElementById("music-col-filter");
    if (!column || !pop) return;
    // The values offered are the ones left by the other filters, so the counts stay honest.
    const albums = applyMusicColumnFilters(state.artists || [], key).flatMap((artist) => artist.albums || []);
    const counts = new Map();
    albums.forEach((album) => musicColumnTokens(column, album).forEach((token) => counts.set(token, (counts.get(token) || 0) + 1)));
    const values = [...counts.keys()].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const picked = musicFilterPicks(key);
    pop.innerHTML = `<input type="search" id="music-col-filter-q" placeholder="Find values…" value="">
        <button type="button" class="col-opt${picked.length ? "" : " is-on"}" data-action="music-col-filter-clear" data-col="${key}">
            <span class="col-check" aria-hidden="true"></span><span>All values (${albums.length})</span>
        </button>
        ${values.map((value) => `<button type="button" class="col-opt${picked.includes(value) ? " is-on" : ""}" data-action="music-col-filter-toggle" data-col="${key}" data-value="${escapeHtml(value)}">
            <span class="col-check" aria-hidden="true"></span><span>${escapeHtml(value)} (${counts.get(value)})</span>
        </button>`).join("")}`;
    const rect = button.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 280))}px`;
    pop.style.top = `${rect.bottom + 4}px`;
    pop.classList.remove("hidden");
    const input = document.getElementById("music-col-filter-q");
    input.addEventListener("input", () => {
        const query = input.value.trim().toLowerCase();
        pop.querySelectorAll(".col-opt[data-value]").forEach((item) => {
            item.classList.toggle("hidden", !!query && !String(item.dataset.value || "").toLowerCase().includes(query));
        });
    });
    input.focus();
}

function toggleMusicColumnFilter(key, value) {
    if (!value) return;
    const picks = musicFilterPicks(key);
    writeMusicFilterPicks(key, picks.includes(value) ? picks.filter((item) => item !== value) : picks.concat(value));
}

function onMusicColumnAction(name, action) {
    if (name === "music-col-sort") return setMusicSort(action.dataset.col);
    if (name === "music-col-check-all") return selectShown(!!action.checked);
    if (name === "music-col-filter") return openMusicColumnFilter(action);
    if (name === "music-col-filter-toggle") return toggleMusicColumnFilter(action.dataset.col, action.dataset.value || "");
    if (name === "music-col-badge") return musicBadgeFilter(action.dataset.col, action.dataset.value || "");
    if (name === "music-col-filter-clear") return writeMusicFilterPicks(action.dataset.col, []);
    if (name === "music-col-columns") return toggleMusicColumns();
    if (name === "music-col-clear-filters") {
        clearMusicColumnFilters();
        return renderTree();
    }
    if (name === "music-col-reset") {
        state.musicColumns = MUSIC_DEFAULT_COLUMNS.slice();
        saveMusicColumns();
        renderMusicColumnsMenu();
        return renderTree();
    }
}

function bindMusicColumns() {
    const menu = document.getElementById("music-columns-menu");
    if (menu) {
        menu.addEventListener("change", (event) => {
            const key = event.target.dataset.musicCol;
            if (key) setMusicColumn(key, event.target.checked);
        });
    }
    document.addEventListener("click", (event) => {
        const columns = document.getElementById("music-columns-menu");
        if (columns && !columns.classList.contains("hidden") && !event.target.closest("#music-columns-menu, #music-columns-btn")) closeMusicColumns();
        const pop = document.getElementById("music-col-filter");
        if (pop && !pop.classList.contains("hidden") && !event.target.closest("#music-col-filter, #music-head .vm-filter")) pop.classList.add("hidden");
    });
    const tree = document.getElementById("tree");
    if (tree) tree.addEventListener("scroll", syncMusicHeadScroll, { passive: true });
    window.addEventListener("resize", syncMusicHeadScroll);
}

state.musicColumns = normalizeMusicColumns(musicRead("curator.musicColumns", MUSIC_DEFAULT_COLUMNS));
state.musicWidths = musicRead("curator.musicWidths", {});
state.musicSort = musicRead("curator.musicSort", null);
state.musicFilters = {};
