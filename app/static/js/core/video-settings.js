const VIDEO_SOURCE_LABELS = { tmdb: "TMDB", tvdb: "TheTVDB", tvmaze: "TVMaze", omdb: "OMDb", rottentomatoes: "Rotten Tomatoes", metacritic: "Metacritic", trakt: "Trakt", anilist: "AniList", ofdb: "OFDb", fanart: "Fanart.tv" };
const VIDEO_ART_LABELS = {
    poster: "Poster", fanart: "Fanart", clearlogo: "Clear logo", clearart: "Clear art", banner: "Banner",
    extrafanart: "Extra fanart (extrafanart/)", extrathumbs: "Extra thumbs (extrathumbs/)",
    landscape: "Landscape", discart: "Disc art", keyart: "Key art (textless poster)", characterart: "Character art",
    squareart: "Square art",
};
const VIDEO_ALL_SOURCES = {
    movie_sources: ["tmdb", "tvdb", "omdb", "rottentomatoes", "metacritic", "trakt", "anilist", "ofdb", "fanart"],
    tv_sources: ["tmdb", "tvdb", "tvmaze", "omdb", "rottentomatoes", "metacritic", "trakt", "anilist", "ofdb", "fanart"],
    art_sources: ["fanart", "tmdb", "tvdb"],
    tv_art_sources: ["fanart", "tmdb", "tvdb", "tvmaze"],
};

function videoCfg() {
    return ((state.settings || {}).video) || {};
}

function videoKeyField(field, id, label, envName, note) {
    const status = state.clearKeys[field] ? "cleared" : (((state.settings || {}).key_status || {})[field] || "");
    const set = status === "saved" || status === "environment";
    const noun = /password/i.test(label) ? "Password" : "Key";
    const cue = status === "cleared"
        ? `<span class="muted">This ${noun.toLowerCase()} will be cleared on save.</span>`
        : set
            ? `<span class="key-set">•••••••• ${noun} is set${status === "environment" ? ` from ${escapeHtml(envName)}` : ""}.</span>`
            : `<span class="muted">Not set. You can also set ${escapeHtml(envName)} in docker-compose.</span>`;
    const clear = status === "saved" ? `<button type="button" class="btn-ghost" data-action="clear-key" data-field="${field}">Clear</button>` : "";
    const service = field.replace(/_key$/, "");
    const test = VIDEO_SOURCE_LABELS[service]
        ? `<button type="button" class="btn-ghost key-test" data-action="test-key" data-service="${service}" data-input="${id}" data-field="${field}" data-label="${escapeHtml(VIDEO_SOURCE_LABELS[service])}">Test</button>`
        : "";
    return `<div class="key-row"><label>${escapeHtml(label)}
        <input id="${id}" type="password" autocomplete="new-password" value="" data-video-key="${field}" placeholder="${set && status !== "cleared" ? "••••••••" : `Paste a ${noun.toLowerCase()}`}">
    </label>
    ${test}</div>
    ${cue} ${clear}${typeof connectionErrorHtml === "function" ? connectionErrorHtml(service) : ""}${note ? `<p class="muted">${note}</p>` : ""}`;
}

function videoKeyFields() {
    return `${videoKeyField("tmdb_key", "tmdb-key", "TMDB API key or read access token", "TMDB_API_KEY", "Required for movies, movie sets and TV. Free at themoviedb.org, Settings, API.")}
            ${videoKeyField("tvdb_key", "tvdb-key", "TheTVDB v4 API key (optional)", "TVDB_API_KEY", "Optional. TV works with TMDB alone. TheTVDB's v4 API needs a paid subscription for personal keys. Add one to use TheTVDB for movie metadata and artwork, as the main TV source, or as a fallback for DVD and absolute order.")}
            ${videoKeyField("omdb_key", "omdb-key", "OMDb API key", "OMDB_API_KEY", "Adds IMDb, Rotten Tomatoes and Metacritic ratings and English movie details (plot, cast, crew, genres, runtime). A free key allows 1,000 lookups a day. Curator stops asking for the rest of that day once OMDb says the quota is used up.")}
            <label class="choice"><input type="checkbox" id="omdb-patron" ${videoCfg().omdb_patron ? "checked" : ""}> OMDb Patron</label>
            <p class="muted">Turn this on when this key is an OMDb Patron key. Curator then keeps asking after 1,000 lookups in a day.</p>
            ${openSubtitlesFields()}
            ${videoKeyField("crawlbase_token", "crawlbase-token", "Crawlbase JS token", "CRAWLBASE_TOKEN", "Optional. Rotten Tomatoes and Metacritic draw their scores in the browser. When a title page has no scores in the HTML, this token loads the rendered page. Leave it empty to use the search feed and any scores already in the page.")}`;
}

function openSubtitlesFields() {
    const cfg = videoCfg();
    return `<h3>OpenSubtitles.com</h3>
            ${videoKeyField("opensubtitles_key", "opensubtitles-key", "OpenSubtitles API key", "OPENSUBTITLES_API_KEY", "Free at opensubtitles.com, under Consumers. Needed to search for subtitles.")}
            <label class="field">Username <input id="video-subs-username" type="text" autocomplete="off" spellcheck="false" value="${escapeHtml(cfg.subs_username || "")}"></label>
            ${videoKeyField("opensubtitles_password", "opensubtitles-password", "Password", "OPENSUBTITLES_PASSWORD", "Downloading needs the account's login. A free account has a daily download limit.")}
            <p><button type="button" class="btn-ghost key-test" data-action="video-subs-test">Test</button></p>
            <label class="field">Subtitle languages <input id="video-subs-languages" type="text" spellcheck="false" value="${escapeHtml(cfg.subs_languages || "en")}" placeholder="en, nb, pt-br"></label>
            <p class="muted">Two-letter codes, separated by commas. Used by Find subtitles and by downloading during a scan.</p>
            <label class="field">Hearing-impaired subtitles ${videoSelect("video-subs-hearing", cfg.subs_hearing_impaired || "exclude", [["exclude", "Skip them"], ["include", "Allow them"], ["only", "Only these"]])}</label>`;
}

function videoChainNudge() {
    return `<span class="priority-nudges">
        <button type="button" class="icon-btn" data-action="video-chain-move" data-dir="-1" title="Move up" aria-label="Move up">${priorityArrow("up")}</button>
        <button type="button" class="icon-btn" data-action="video-chain-move" data-dir="1" title="Move down" aria-label="Move down">${priorityArrow("down")}</button>
    </span>`;
}

function metaRows(level) {
    const rows = ((typeof SCRAPE_FIELDS !== "undefined" && SCRAPE_FIELDS[level]) || []).slice();
    if (level === "show" && !rows.some(([key]) => key === "year")) {
        const aired = rows.findIndex(([key]) => key === "aired");
        rows.splice(aired >= 0 ? aired + 1 : rows.length, 0, ["year", "Year"]);
    }
    return rows;
}

function metaFieldChecks(level, storageKey) {
    const rows = metaRows(level);
    const saved = videoCfg()[storageKey];
    const on = (key) => !Array.isArray(saved) || saved.includes(key);
    return `<div class="scrape-picks">${rows.map(([key, label]) =>
        `<label class="choice"><input type="checkbox" data-meta-field="${storageKey}" value="${escapeHtml(key)}" ${on(key) ? "checked" : ""}> ${escapeHtml(label)}</label>`
    ).join("")}</div>`;
}

function videoChain(key) {
    const cfg = videoCfg();
    const saved = Object.prototype.hasOwnProperty.call(cfg, key) ? cfg[key] : (key === "tv_art_sources" ? cfg.art_sources : null);
    const chosen = Array.isArray(saved) ? saved : (VIDEO_ALL_SOURCES[key] || []);
    const all = chosen.concat(VIDEO_ALL_SOURCES[key].filter((name) => !chosen.includes(name)));
    const rows = all.map((name) => `<div class="priority-item${chosen.includes(name) ? "" : " is-off"}" draggable="true" data-source="${escapeHtml(name)}">
        ${priorityGrip()}
        <label class="choice"><input type="checkbox" data-chain-on ${chosen.includes(name) ? "checked" : ""}> ${escapeHtml(VIDEO_SOURCE_LABELS[name])}</label>
        ${videoChainNudge()}
    </div>`).join("");
    return `<div class="priority-list" data-video-chain="${key}">${rows}</div>`;
}

function videoArtChecks(key, kinds) {
    const on = videoCfg()[key] || {};
    const widths = videoCfg().min_width || {};
    return `<div class="vart-grid">${kinds.map((kind) => `<label class="choice"><input type="checkbox" data-video-art="${key}" value="${kind}" ${on[kind] ? "checked" : ""}> ${escapeHtml(VIDEO_ART_LABELS[kind])}</label>
        ${key === "season_art" || kind === "extrafanart" || kind === "extrathumbs" ? "<span></span>" : `<label class="vart-min">min width <input type="number" min="0" max="8000" step="10" data-video-min="${kind}" value="${Number(widths[kind]) || 0}"></label>`}`).join("")}</div>`;
}

const SCRAPE_LOCALES = [
    ["en-US", "English (US)"], ["en-GB", "English (UK)"], ["de-DE", "German"], ["fr-FR", "French"],
    ["es-ES", "Spanish"], ["es-MX", "Spanish (Mexico)"], ["it-IT", "Italian"], ["nl-NL", "Dutch"],
    ["sv-SE", "Swedish"], ["nb-NO", "Norwegian"], ["da-DK", "Danish"], ["fi-FI", "Finnish"],
    ["pl-PL", "Polish"], ["pt-PT", "Portuguese"], ["pt-BR", "Portuguese (Brazil)"], ["ru-RU", "Russian"],
    ["ja-JP", "Japanese"], ["ko-KR", "Korean"], ["zh-CN", "Chinese (Simplified)"], ["zh-TW", "Chinese (Traditional)"],
    ["cs-CZ", "Czech"], ["hu-HU", "Hungarian"], ["tr-TR", "Turkish"], ["el-GR", "Greek"],
    ["he-IL", "Hebrew"], ["ar-SA", "Arabic"], ["th-TH", "Thai"], ["hi-IN", "Hindi"],
];
const CERT_COUNTRIES = [
    ["US", "United States"], ["GB", "United Kingdom"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"],
    ["IT", "Italy"], ["NL", "Netherlands"], ["SE", "Sweden"], ["NO", "Norway"], ["DK", "Denmark"],
    ["FI", "Finland"], ["PL", "Poland"], ["PT", "Portugal"], ["BR", "Brazil"], ["RU", "Russia"],
    ["JP", "Japan"], ["KR", "South Korea"], ["CN", "China"], ["AU", "Australia"], ["CA", "Canada"],
    ["NZ", "New Zealand"], ["IE", "Ireland"], ["CH", "Switzerland"], ["AT", "Austria"], ["BE", "Belgium"],
    ["MX", "Mexico"], ["IN", "India"],
];
const CERT_RATINGS = {
    US: { movie: ["G", "PG", "PG-13", "R", "NC-17", "NR"], tv: ["TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA", "NR"] },
    GB: { movie: ["U", "PG", "12A", "12", "15", "18", "R18"], tv: ["U", "PG", "12", "15", "18"] },
    DE: { movie: ["0", "6", "12", "16", "18"], tv: ["0", "6", "12", "16", "18"] },
    FR: { movie: ["U", "10", "12", "16", "18"], tv: ["TP", "-10", "-12", "-16", "-18"] },
    ES: { movie: ["APTA", "7", "12", "16", "18"], tv: ["APTA", "7", "12", "16", "18"] },
    IT: { movie: ["T", "VM14", "VM18"], tv: ["T", "VM14", "VM18"] },
    NL: { movie: ["AL", "6", "9", "12", "14", "16", "18"], tv: ["AL", "6", "9", "12", "14", "16", "18"] },
    SE: { movie: ["Btl", "7", "11", "15"], tv: ["Btl", "7", "11", "15"] },
    NO: { movie: ["A", "6", "9", "12", "15", "18"], tv: ["A", "6", "9", "12", "15", "18"] },
    DK: { movie: ["A", "7", "11", "15"], tv: ["A", "7", "11", "15"] },
    FI: { movie: ["S", "K-7", "K-12", "K-16", "K-18"], tv: ["S", "K-7", "K-12", "K-16", "K-18"] },
    PL: { movie: ["b.o.", "7", "12", "16", "18"], tv: ["b.o.", "7", "12", "16", "18"] },
    PT: { movie: ["M/3", "M/6", "M/12", "M/14", "M/16", "M/18"], tv: ["M/3", "M/6", "M/12", "M/14", "M/16", "M/18"] },
    BR: { movie: ["L", "10", "12", "14", "16", "18"], tv: ["L", "10", "12", "14", "16", "18"] },
    RU: { movie: ["0+", "6+", "12+", "16+", "18+"], tv: ["0+", "6+", "12+", "16+", "18+"] },
    JP: { movie: ["G", "PG12", "R15+", "R18+"], tv: ["G", "PG12", "R15+", "R18+"] },
    KR: { movie: ["ALL", "12", "15", "19"], tv: ["ALL", "7", "12", "15", "19"] },
    CN: { movie: ["6", "12", "15", "18"], tv: ["6", "12", "15", "18"] },
    AU: { movie: ["E", "G", "PG", "M", "MA15+", "R18+"], tv: ["P", "C", "G", "PG", "M", "MA15+", "AV15+", "R18+"] },
    CA: { movie: ["G", "PG", "14A", "18A", "R"], tv: ["C", "C8", "G", "PG", "14+", "18+"] },
    NZ: { movie: ["G", "PG", "M", "R13", "R16", "R18"], tv: ["G", "PG", "M", "16", "18"] },
    IE: { movie: ["G", "PG", "12", "15", "16", "18"], tv: ["G", "PG", "12", "15", "18"] },
    CH: { movie: ["0", "6", "12", "16", "18"], tv: ["0", "6", "12", "16", "18"] },
    AT: { movie: ["6", "10", "12", "14", "16"], tv: ["6", "10", "12", "14", "16"] },
    BE: { movie: ["AL", "6", "9", "12", "16"], tv: ["AL", "6", "9", "12", "16"] },
    MX: { movie: ["AA", "A", "B", "B15", "C", "D"], tv: ["AA", "A", "B", "B15", "C", "D"] },
    IN: { movie: ["U", "UA", "A", "S"], tv: ["U", "UA", "A"] },
};
const ORIGIN_LANGUAGES = [
    ["en", "English"], ["de", "German"], ["fr", "French"], ["es", "Spanish"], ["it", "Italian"],
    ["nl", "Dutch"], ["sv", "Swedish"], ["no", "Norwegian"], ["da", "Danish"], ["fi", "Finnish"],
    ["pl", "Polish"], ["pt", "Portuguese"], ["ru", "Russian"], ["ja", "Japanese"], ["ko", "Korean"],
    ["zh", "Chinese"], ["cs", "Czech"], ["hu", "Hungarian"], ["tr", "Turkish"], ["el", "Greek"],
    ["he", "Hebrew"], ["ar", "Arabic"], ["th", "Thai"], ["hi", "Hindi"],
];
// The languages a track or a subtitle file can be given. The values are the codes stored in files, the same ones
// the server keeps in curator/video/languages.py, so nothing has to be typed and nothing is refused.
const TRACK_LANGUAGES = [
    ["ara", "Arabic"], ["bul", "Bulgarian"], ["chi", "Chinese"], ["hrv", "Croatian"], ["cze", "Czech"],
    ["dan", "Danish"], ["nld", "Dutch"], ["eng", "English"], ["est", "Estonian"], ["fin", "Finnish"],
    ["fra", "French"], ["deu", "German"], ["gre", "Greek"], ["heb", "Hebrew"], ["hin", "Hindi"],
    ["hun", "Hungarian"], ["isl", "Icelandic"], ["ita", "Italian"], ["jpn", "Japanese"], ["kor", "Korean"],
    ["lav", "Latvian"], ["lit", "Lithuanian"], ["nor", "Norwegian"], ["nno", "Norwegian Nynorsk"], ["pol", "Polish"], ["por", "Portuguese"],
    ["rum", "Romanian"], ["rus", "Russian"], ["srp", "Serbian"], ["slk", "Slovak"], ["slv", "Slovenian"],
    ["spa", "Spanish"], ["swe", "Swedish"], ["tha", "Thai"], ["tur", "Turkish"], ["ukr", "Ukrainian"],
    ["vie", "Vietnamese"],
];
const ART_LANGS = [
    ["en", "English"], ["de", "German"], ["fr", "French"], ["es", "Spanish"], ["it", "Italian"],
    ["nl", "Dutch"], ["sv", "Swedish"], ["no", "Norwegian"], ["da", "Danish"], ["fi", "Finnish"],
    ["pl", "Polish"], ["pt", "Portuguese"], ["ru", "Russian"], ["ja", "Japanese"], ["ko", "Korean"],
    ["zh", "Chinese"], ["cs", "Czech"], ["hu", "Hungarian"], ["tr", "Turkish"], ["el", "Greek"],
    ["he", "Hebrew"], ["ar", "Arabic"], ["th", "Thai"], ["hi", "Hindi"], ["none", "Textless"],
];

function withCurrentOption(options, current) {
    if (!current || options.some(([key]) => key === current)) return options;
    return [[current, current], ...options];
}

function videoSelect(id, value, options) {
    return `<select id="${id}">${options.map(([key, label]) => `<option value="${key}" ${key === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select>`;
}

function artLanguageFields(cfg) {
    const saved = Array.isArray(cfg.art_languages) ? cfg.art_languages : ["en", "", "", ""];
    const labels = ["Primary", "Then try", "Then try", "Then try"];
    return labels.map((label, index) => {
        const current = saved[index] || (index === 0 ? "en" : "");
        const options = index === 0 ? ART_LANGS : [["", "None"], ...ART_LANGS];
        return `<label class="field">${label} ${videoSelect(`video-art-lang-${index}`, current, withCurrentOption(options, current))}</label>`;
    }).join("");
}

function videoCheck(id, value, label) {
    return `<label class="choice"><input type="checkbox" id="${id}" ${value ? "checked" : ""}> ${escapeHtml(label)}</label>`;
}

function sortTheControl(example) {
    const on = (state.settings || {}).sort_ignore_the !== false;
    return `<h3>Library</h3>
        <label class="choice"><input type="checkbox" data-sort-ignore-the ${on ? "checked" : ""}> Ignore a leading The, A, or An when sorting the library</label>
        <p class="muted">${escapeHtml(example)} Turn this off to list that name under T. The same choice is on the Music tab and applies to every library.</p>`;
}

function scanFillControl(kind) {
    const cfg = videoCfg();
    const fill = cfg.scan_fill_missing !== false;
    const limited = !!cfg.scan_limited_art;
    const trailers = kind === "tv" ? !!cfg.scan_download_tv_trailers : !!cfg.scan_download_trailers;
    const themes = kind === "tv" ? !!cfg.scan_download_tv_themes : !!cfg.scan_download_themes;
    const trailerNote = kind === "tv"
        ? "During the metadata and artwork lookup, a TV scan downloads a YouTube trailer for a show or a season that does not have one on disk yet. A trailer already there is kept, unless it is below the quality set under Files and YouTube has a taller copy. Several trailers download at once. An incremental deep scan does this for shows that are new or changed. A full or deep scan does it for every show or season that already has a trailer link. When the lookup is off, the trailer step runs on its own."
        : "During the metadata and artwork lookup, a movie scan downloads a YouTube trailer for a movie that does not have one on disk yet. A trailer already there is kept, unless it is below the quality set under Files and YouTube has a taller copy. Several trailers download at once. An incremental deep scan does this for movies that are new or changed. A full or deep scan does it for every movie that already has a trailer link. When the lookup is off, the trailer step runs on its own.";
    const subs = kind === "tv" ? !!cfg.subs_download_tv : !!cfg.subs_download_movies;
    const subsNote = `After the lookup, a ${kind === "tv" ? "TV" : "movie"} scan searches OpenSubtitles.com for each language in the list under API keys, for every ${kind === "tv" ? "episode" : "movie"} that has no subtitle in that language, embedded or beside the file. The best match is saved next to the video as a .srt: a subtitle made for this exact file first, then trusted uploaders, then the most downloaded. Forced subtitles do not count as having one. An incremental scan does this for ${kind === "tv" ? "shows" : "movies"} that are new or changed; a full or deep scan checks every one. The account's daily download quota applies, and the scan stops asking when it is used up. Needs the API key, username and password under API keys.`;
    const themeNote = kind === "tv"
        ? "During the metadata and artwork lookup, a TV scan downloads a local theme.mp3 into the show folder for any show that does not have one on disk yet. An existing theme song is kept. An incremental scan does this for shows that are new or changed; a full or deep scan checks every show in the scanned folders. When the lookup is off, the theme song step runs on its own."
        : "During the metadata and artwork lookup, a movie scan downloads a local theme.mp3 into the movie folder for any movie that does not have one on disk yet. An existing theme song is kept. An incremental scan does this for movies that are new or changed; a full or deep scan checks every movie in the scanned folders. When the lookup is off, the theme song step runs on its own.";
    return `<h3>During a scan</h3>
        <label class="choice"><input type="checkbox" data-video-scan-fill ${fill ? "checked" : ""}> Download missing metadata and artwork during a scan</label>
        <p class="muted">After the folders are read, an incremental deep scan is a deep lookup of the new and changed files. A full scan reads every file and looks up one that is new, changed, or missing an enabled field or image. A file that already has every enabled field and image, and has not changed, is left alone. A deep scan looks up every item in the file or mount it was given. Overwrite metadata and Overwrite artwork, below, decide whether an existing value is replaced. Locked items and locked fields stay as they are. Turn this off to leave a scan as a local read and a probe. The same choice is on the Movies and TV tabs.</p>
        <label class="choice"><input type="checkbox" data-video-scan-limited ${limited ? "checked" : ""}> Limited artwork search during scan</label>
        <p class="muted">When this is on, the lookup only downloads a missing poster. When it is off, it downloads every artwork type that is checked for movies or shows and is still missing. The same choice is on the Movies and TV tabs.</p>
        <label class="choice"><input type="checkbox" data-video-scan-trailers ${trailers ? "checked" : ""}> Download trailers during a scan</label>
        <p class="muted">${trailerNote}</p>
        <label class="choice"><input type="checkbox" data-video-scan-subs ${subs ? "checked" : ""}> Download missing subtitles from OpenSubtitles.com during a scan</label>
        <p class="muted">${subsNote}</p>
        <label class="choice"><input type="checkbox" data-video-scan-themes ${themes ? "checked" : ""}> Download theme songs (theme.mp3) during a scan</label>
        <p class="muted">${themeNote}</p>
        ${kind === "movies" ? `<label class="choice"><input type="checkbox" data-video-scan-iso ${cfg.scan_iso ? "checked" : ""}> Scan .iso files</label>
        <p class="muted">On by default. A movie scan opens each .iso with ffprobe and MediaInfo and reads the real video, audio, and subtitle streams. Turn this off to read only the disc file name. A Blu-ray or UHD disc is tens of gigabytes, and reading it seeks through the whole image, so a scan takes longer while this is on. A TV scan always reads the disc file name.</p>` : ""}
        <label class="choice"><input type="checkbox" data-video-scan-rewrite-nfo ${cfg.scan_rewrite_nfo ? "checked" : ""}> Rewrite .nfo files at the end of a scan</label>
        <p class="muted">The last stage of a scan always writes an .nfo that is missing, from what the library already holds. When this is on, that stage also replaces every .nfo in the scanned folders. A .nfo.bak is kept when that backup option is on. A webhook scan only covers the folders it was given. The same choice is on the Movies and TV tabs.</p>`;
}

function extraFanartCount() {
    const count = Number(videoCfg().extrafanart_count);
    const value = count >= 1 ? count : 10;
    return `<label class="field">Maximum extra fanart
            <input type="number" min="1" max="20" data-video-extrafanart-count value="${value}">
        </label>
        <p class="muted">How many images a scrape or scan saves in extrafanart/. The main fanart file is separate. The same number is on the Movies and TV tabs, and the value on the tab you save from is kept.</p>`;
}

function overwriteSaved(media, side) {
    const cfg = videoCfg();
    const block = (cfg.policies || {})[media] || {};
    const value = block[side];
    if (value === true || value === "overwrite") return true;
    if (value === false || value === "merge" || value === "missing") return false;
    return cfg.overwrite_policy === "overwrite" || cfg.overwrite_policy === true;
}

function policyFields(media, note) {
    const meta = overwriteSaved(media, "metadata");
    const art = overwriteSaved(media, "artwork");
    return `<h3>Overwrite during a scan</h3>
        <label class="choice"><input type="checkbox" id="policy-${media}-metadata" ${meta ? "checked" : ""}> Overwrite metadata</label>
        <label class="choice"><input type="checkbox" id="policy-${media}-artwork" ${art ? "checked" : ""}> Overwrite artwork</label>
        <p class="muted">${note}</p>`;
}

function videoSettingsHtml() {
    const cfg = videoCfg();
    return `
        <section class="settings-section" data-tab="movies">${sortTheControl("The Matrix is listed under M.")}
            <h3>UI Elements</h3>
            ${videoCheck("video-ui-movie-year", cfg.ui_movie_year !== false, "Show release year in title")}
            ${videoCheck("video-ui-movie-edition", cfg.ui_movie_edition !== false, "Show edition in title")}
            ${videoCheck("video-ui-movie-date-added", cfg.ui_movie_date_added !== false, "Show date added")}
            ${videoCheck("video-ui-movie-processed", cfg.ui_movie_processed !== false, "Show processed/unprocessed checkmark")}
            ${videoCheck("video-ui-movie-poster-badges", cfg.ui_movie_poster_badges !== false, "Show resolution, HDR and audio badges on the poster")}
            ${videoCheck("video-ui-movie-art-badges", cfg.ui_movie_art_badges !== false, "Show resolution and aspect ratio badges on artwork")}
            <label class="choice"><input type="checkbox" data-video-collapse ${cfg.collapse_versions ? "checked" : ""}> Collapse versions of the same movie into one row</label>
            <p class="muted">Movies that share a TMDB id, an IMDb id, or the same title and year sit on one row. The row shows the highest-resolution copy. Expand it to see the other versions.</p>
            ${scanFillControl("movies")}
            <h3>Movie scrapers</h3>
            <p class="muted">Sources are asked in parallel. For each field the first source in this order that has a value wins; ratings and ids from every source are kept. Drag a row to change the order. TMDB is required for movies.</p>
            ${videoChain("movie_sources")}
            <h3>Metadata fields</h3>
            <p class="muted">A scan writes the fields that are checked and leaves the others alone. The scrape dialog opens with these same boxes. A change in that dialog applies only to that scrape.</p>
            ${metaFieldChecks("movie", "movie_fields")}
            <h3>Language</h3>
            <p class="muted">Metadata language is used for plots, titles and tags. A movie, show or episode can set its own language in Edit, and that one wins. Certification country picks the rating shown as the certification, such as R. Every country's rating is still stored.</p>
            <label class="field">Metadata language ${videoSelect("video-language", cfg.language || "en-US", withCurrentOption(SCRAPE_LOCALES, cfg.language || "en-US"))}</label>
            <label class="field">Certification country ${videoSelect("video-country", cfg.country || "US", withCurrentOption(CERT_COUNTRIES, cfg.country || "US"))}</label>
            <h3>Artwork languages</h3>
            <p class="muted">Artwork is tried in this order. Primary is English unless you pick another. The three rows under it are optional. Textless is an image with no title on it. The same order is used for movies and TV.</p>
            ${artLanguageFields(cfg)}
            <label class="field">Default rating ${videoSelect("video-default-rating", cfg.default_rating || "themoviedb", [["themoviedb", "TMDB"], ["imdb", "IMDb"], ["trakt", "Trakt"], ["tvdb", "TheTVDB"], ["tomatometerallcritics", "Rotten Tomatoes"], ["tomatometeravguseraudience", "RT audience"], ["metacritic", "Metacritic"], ["metacriticuser", "Metacritic user"], ["anilist", "AniList"], ["ofdb", "OFDb"]])}</label>
            <h3>Artwork sources</h3>
            <p class="muted">Images are taken from the first source in this order that has one. Drag a row to change the order. An unchecked source is not asked, and it drops to the bottom. Movies and sets use this list. TV has its own list on the TV tab.</p>
            ${videoChain("art_sources")}
            <h3>Movie artwork</h3>
            <p class="muted">Images narrower than the minimum width are skipped. Fanart.tv sizes are fixed; TMDB reports real sizes.</p>
            ${videoArtChecks("movie_art", ["poster", "fanart", "extrafanart", "extrathumbs", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart"])}
            ${extraFanartCount()}
            <h3>Writing</h3>
            ${policyFields("movies", "A scan fills the movie fields and images that are checked above and still empty. Turn a box on to replace those existing values. An image is replaced only when the new one is larger. A replaced .nfo is copied to .nfo.bak when the backup option below is on. CMM_OVERWRITE_ALL starts both boxes on, for Movies, TV, and Sets, until you save.")}
            <label class="field">.nfo dialect ${videoSelect("video-dialect", cfg.nfo_dialect || "kodi", [["kodi", "Kodi 22"], ["emby", "Emby / Jellyfin (adds lockdata, flat ratings)"], ["plex", "Plex (XBMCnfo agents, adds guid)"]])}</label>
            <label class="field">Movie .nfo name ${videoSelect("video-nfo-name", cfg.movie_nfo_name || "filename", [["filename", "<video name>.nfo"], ["movie", "movie.nfo in the movie folder"]])}</label>
            ${videoCheck("video-write-nfo", cfg.write_nfo !== false, "Write .nfo files after a scrape")}
            ${videoCheck("video-download-art", cfg.download_artwork !== false, "Download artwork next to the files")}
            ${videoCheck("video-nfo-backup", cfg.nfo_backup !== false, "Keep a .nfo.bak when a rewrite replaces a file")}
            ${videoCheck("video-write-on-edit", cfg.write_on_edit !== false, "Rewrite the .nfo after an inline edit")}
            ${videoCheck("video-actor-thumbs", cfg.actor_thumbs !== false, "Include actor photo links")}
            ${videoCheck("video-keywords", !!cfg.keywords_as_tags, "Save TMDB keywords as tags")}
            <label class="field">Items scraped at once <input id="video-concurrency" type="number" min="1" max="12" value="${Number(cfg.concurrency) || 4}"></label>
            <h3>On Radarr import</h3>
            ${videoCheck("video-trailer-webhook", !!cfg.trailer_on_webhook, "Download the movie trailer")}
            <p class="muted">After a Radarr import has been scanned and scraped, the movie trailer is downloaded from the YouTube link the scraper saved. A movie that already has a trailer is only fetched again when the file is below the quality set under General and YouTube has a taller copy.</p>
        </section>
        <section class="settings-section" data-tab="sets">${sortTheControl("The Godfather Collection is listed under G.")}
            <h3>UI Elements</h3>
            ${videoCheck("video-ui-set-processed", cfg.ui_set_processed !== false, "Show processed/unprocessed checkmark")}
            ${videoCheck("video-ui-set-poster-badges", cfg.ui_set_poster_badges !== false, "Show the movie count badge on the poster")}
            ${videoCheck("video-ui-set-art-badges", cfg.ui_set_art_badges !== false, "Show resolution and aspect ratio badges on artwork")}
            <h3>Movie sets</h3>
            <p class="muted">Scraping a movie that belongs to a TMDB collection puts it in that set, unless the set field is locked. Sets from .nfo files are kept.</p>
            <h3>Central set folder</h3>
            <label class="field">Movie set information folder
                <span class="path-field"><input id="video-set-folder" value="${escapeHtml(cfg.set_folder || "")}" placeholder="/movies/_Sets" spellcheck="false"><button type="button" class="btn-ghost" data-action="browse-set-folder">Browse</button></span>
            </label>
            <p class="muted">Curator writes one folder per set here, named after the set (for example <code>Alien Collection/poster.jpg</code>), with the set artwork and a <code>set.nfo</code>. Point Kodi's Settings, Media, Videos, "Movie set information folder" at the same folder. Browse lists folders the container can see. The folder must already exist. A folder inside a movie library folder works, and so does a separate mount. CMM_SET_FOLDER in docker-compose is used when this box is empty. Leave both empty to skip set artwork.</p>
            <h3>Set artwork</h3>
            <p class="muted">From TMDB collection images and Fanart.tv (when its key is set). Minimum widths are shared with movie artwork.</p>
            ${videoArtChecks("set_art", ["poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "squareart"])}
            ${policyFields("sets", "A scan fills an empty set overview and the set images that are checked. Turn a box on to replace those existing values. An image is replaced only when the new one is larger. A movie scrape that updates its set uses these switches.")}
            ${videoCheck("video-set-nfo", cfg.set_nfo !== false, "Write set.nfo with the set title, original title, and overview")}
            <p class="muted">Set art is written when a movie in the set is scraped, or from the Sets tab with Scrape.</p>
        </section>
        <section class="settings-section" data-tab="tv">${sortTheControl("The Office is listed under O.")}
            <h3>UI Elements</h3>
            ${videoCheck("video-ui-tv-year", cfg.ui_tv_year !== false, "Show year in title")}
            ${videoCheck("video-ui-tv-seasons", cfg.ui_tv_seasons !== false, "Show number of seasons")}
            ${videoCheck("video-ui-tv-episodes", cfg.ui_tv_episodes !== false, "Show number of episodes")}
            ${videoCheck("video-ui-tv-date-added", cfg.ui_tv_date_added !== false, "Show date added")}
            ${videoCheck("video-ui-tv-processed", cfg.ui_tv_processed !== false, "Show processed/unprocessed checkmark")}
            ${videoCheck("video-ui-tv-progress", cfg.ui_tv_progress !== false, "Show season and episode completeness progress bars under posters")}
            ${videoCheck("video-ui-tv-poster-badges", cfg.ui_tv_poster_badges !== false, "Show season, episode and file badges on the poster")}
            ${videoCheck("video-ui-tv-art-badges", cfg.ui_tv_art_badges !== false, "Show resolution and aspect ratio badges on artwork")}
            ${scanFillControl("tv")}
            <h3>TV scrapers</h3>
            <p class="muted">TV folders are chosen under General, Library folders. Each subfolder of a TV folder is a show. TMDB is the default and only needs its free API key. TheTVDB is optional: its v4 API needs a paid subscription for personal use, and when it has no key it is skipped. TVMaze needs no key. Drag a row to change the order.</p>
            ${videoChain("tv_sources")}
            <h3>Metadata fields</h3>
            <p class="muted">A scan writes the fields that are checked and leaves the others alone. The scrape dialog opens with these same boxes. A change in that dialog applies only to that scrape.</p>
            <h4>Shows</h4>
            ${metaFieldChecks("show", "show_fields")}
            <h4>Seasons</h4>
            ${metaFieldChecks("season", "season_fields")}
            <h4>Episodes</h4>
            ${metaFieldChecks("episode", "episode_fields")}
            <label class="field">Main source for shows ${videoSelect("video-tv-primary", cfg.tv_primary || "tmdb", [["tmdb", "TMDB (default)"], ["tvdb", "TheTVDB (needs a key)"]])}</label>
            <label class="field">Episode order ${videoSelect("video-episode-order", cfg.episode_order || "aired", [["aired", "Aired"], ["dvd", "DVD"], ["absolute", "Absolute"]])}</label>
            <p class="muted">With TMDB, DVD and absolute order come from TMDB episode groups. When a show has no such group, TheTVDB is used if it has a key; otherwise episode details are left alone and the scrape log says so. A show can override the order in its edit form.</p>
            <h3>Artwork sources</h3>
            <p class="muted">Images are taken from the first source in this order that has one. Drag a row to change the order. An unchecked source is not asked, and it drops to the bottom. Shows, seasons, and episodes use this list. TVMaze supplies posters, banners, backgrounds, and episode stills.</p>
            ${videoChain("tv_art_sources")}
            <h3>Show artwork</h3>
            ${videoArtChecks("tv_art", ["poster", "fanart", "extrafanart", "extrathumbs", "clearlogo", "clearart", "banner", "landscape", "characterart", "squareart"])}
            ${extraFanartCount()}
            <h3>Season artwork</h3>
            ${videoArtChecks("season_art", ["poster", "banner", "landscape", "fanart"])}
            ${videoCheck("video-episode-thumbs", cfg.episode_thumbs !== false, "Episode thumbnails (<video name>-thumb.jpg)")}
            ${videoCheck("video-scan-gen-ep-thumb", cfg.scan_generate_ep_thumb !== false, "Generate episode thumb if missing during TV scan (uses ffmpeg, samples from mid-file, avoids black frames)")}
            <h3>Episode split</h3>
            <p class="muted">Used when a multi-episode Matroska file is split without re-encoding. A chapter start inside the chapter window is the cut. When there is no chapter, black and silence are searched in the detection window, then once in the wide window. The source file is kept beside the parts.</p>
            <label class="field">Chapter window (seconds) <input id="video-split-chapter-window" type="number" min="1" max="120" step="1" value="${splitNum(cfg.split_chapter_window, 15)}"></label>
            <label class="field">Black and silence window (seconds) <input id="video-split-detect-window" type="number" min="1" max="120" step="1" value="${splitNum(cfg.split_detect_window, 15)}"></label>
            <label class="field">Wide window (seconds) <input id="video-split-wide-window" type="number" min="1" max="300" step="1" value="${splitNum(cfg.split_wide_window, 45)}"></label>
            <label class="field">Cut on the black picture at ${videoSelect("video-split-cut-at", cfg.split_cut_at || "start", [["start", "Its first frame"], ["middle", "Its middle"], ["end", "Its last frame"]])}</label>
            <label class="field">Minimum black (seconds) <input id="video-split-black-seconds" type="number" min="0.05" max="5" step="0.05" value="${splitNum(cfg.split_black_seconds, 0.3)}"></label>
            <label class="field">Black picture threshold <input id="video-split-black-pic" type="number" min="0.5" max="1" step="0.01" value="${splitNum(cfg.split_black_pic, 0.98)}"></label>
            <label class="field">Black pixel threshold <input id="video-split-black-pix" type="number" min="0" max="1" step="0.01" value="${splitNum(cfg.split_black_pix, 0.1)}"></label>
            <label class="field">Silence level (dB) <input id="video-split-silence-db" type="number" min="-90" max="-10" step="1" value="${splitNum(cfg.split_silence_db, -50)}"></label>
            <label class="field">Minimum silence (seconds) <input id="video-split-silence-seconds" type="number" min="0.05" max="5" step="0.05" value="${splitNum(cfg.split_silence_seconds, 0.4)}"></label>
            <label class="field">Minimum overlap (seconds) <input id="video-split-overlap" type="number" min="0.05" max="5" step="0.05" value="${splitNum(cfg.split_overlap_seconds, 0.25)}"></label>
            <label class="field">Ambiguous when both overlaps are within (seconds of the expected time) <input id="video-split-ambiguous-anchor" type="number" min="0.5" max="30" step="0.5" value="${splitNum(cfg.split_ambiguous_anchor, 5)}"></label>
            <label class="field">and within (seconds of each other) <input id="video-split-ambiguous-apart" type="number" min="0.5" max="30" step="0.5" value="${splitNum(cfg.split_ambiguous_apart, 3)}"></label>
            <label class="field">Shortest part (seconds) <input id="video-split-min-part" type="number" min="1" max="600" step="1" value="${splitNum(cfg.split_min_part, 30)}"></label>
            ${videoCheck("video-scan-split-notify", cfg.scan_split_notify === true, "After splitting, send library update to the players (also removes any old entry from Kodi when its file is gone)")}
            ${policyFields("tv", "Shows, seasons, and episodes use these. A scan fills the checked fields and images that are empty. Turn a box on to replace those existing values. An image is replaced only when the new one is larger. The .nfo dialect and the other writing options stay on the Movies tab.")}
            <h3>On Sonarr import</h3>
            ${videoCheck("video-trailer-sonarr", !!cfg.trailer_on_sonarr_season, "Download the season trailers")}
            <p class="muted">After a Sonarr import has been scanned and scraped, a trailer is downloaded for each season that received episodes, when the scraper has saved a YouTube link for it. A season that already has a trailer is only fetched again when the file is below the quality set under General and YouTube has a taller copy.</p>
        </section>
        ${videoFilesSettingsHtml(cfg)}`;
}

function musicRenameSettingsHtml(cfg) {
    const folder = cfg.rename_folder_pattern || "%albumartist%/[%year%] %album%$if(%multidisc%,/CD%discnumber%)";
    const file = cfg.rename_file_pattern || "Disc %discnumber% - $num(%tracknumber%,2) - %title%";
    return `<h4>Music renaming patterns</h4>
            <p class="muted">Folder and file patterns for music. Batch commit uses these same patterns. Tokens: <code>%albumartist%</code>, <code>%albumartists%</code>, <code>%artist%</code>, <code>%artists%</code>, <code>%album%</code>, <code>%year%</code>, <code>%title%</code>, <code>%tracknumber%</code>, <code>%discnumber%</code>, <code>%totaldiscs%</code>, <code>%multidisc%</code>, <code>%format%</code>, <code>%edition%</code>, <code>%releasegroup%</code>, <code>$num(%tracknumber%,2)</code>, <code>$decade(%year%)</code>, <code>$if(%multidisc%,/CD%discnumber%)</code>. <code>%multidisc%</code> is set only when the release has more than one disc, so a one-disc album stays in the album folder. A multi-disc release adds <code>CD1</code>, <code>CD2</code>, and so on. The example is Radiohead, In Rainbows, disc 1 of 2, track 1, 15 Step.</p>
            <label class="field">Folder structure <input id="music-rename-folder" class="mono" spellcheck="false" value="${escapeHtml(folder)}"></label>
            <p><button type="button" class="btn-ghost" data-music-builder="music-rename-folder">Syntax builder</button></p>
            <label class="field">Audio file name <input id="music-rename-file" class="mono" spellcheck="false" value="${escapeHtml(file)}"></label>
            <p><button type="button" class="btn-ghost" data-music-builder="music-rename-file">Syntax builder</button></p>
            <p class="pattern-example muted">Example: <span class="mono" id="music-rename-example"></span></p>`;
}

const VIDEO_PATTERNS = [
    ["movie_folder", "Movie folder", "Used only when the movie has a folder of its own."],
    ["movie_file", "Movie file", "Without the extension. movie.part is part1, part2 for stacked files."],
    ["show_folder", "Show folder", ""],
    ["season_folder", "Season folder", "When the pattern renders an empty name, episodes stay directly in the show folder."],
    ["episode_file", "Episode file", "A file holding several episodes uses a Kodi range, such as S01E01-E04, and leaves the title off. A file that continues into the next season uses S01E05-E08S02E01-E04."],
];

function videoFilesSettingsHtml(cfg) {
    const rename = cfg.rename || {};
    return `<section class="settings-section" data-tab="files"><h3>Rename patterns</h3>
            <p class="muted">Rename from the right-click menu of a movie, show, season or episode. You see every change before anything moves.</p>
            ${musicRenameSettingsHtml(cfg)}
            <h4>Movie renaming patterns</h4>
            <p class="muted">Jinja2 patterns, one path part each. Words are joined with periods, and the release group stays at the end as <code>-ReleaseGroup</code>. The Syntax builder button under each box builds a pattern from clickable pieces. Fields: <code>movie.title</code>, <code>movie.year</code>, <code>movie.edition</code>, <code>movie.id.tmdb</code>, <code>movie.id.imdb</code>, <code>movie.part</code>, <code>movie.set</code>; <code>show.title</code>, <code>show.year</code>, <code>show.id.tvdb</code>; <code>episode.season</code>, <code>episode.number</code>, <code>episode.title</code>, <code>episode.season_raw</code>; <code>media.quality</code>, <code>media.source</code>, <code>media.resolution</code>, <code>media.audio_codec</code>, <code>media.audio_channels</code>, <code>media.hdr</code>, <code>media.video_codec</code>, <code>media.hybrid</code>, <code>media.format</code>, <code>media.release_group</code>. Filters: <code>sanitize</code>, <code>dot</code> and <code>pad(2)</code>. <code>dot</code> joins words with periods, so Hide and Seek and DTS-HD MA become Hide.and.Seek and DTS-HD.MA. <code>episode.number</code> lists every episode in the file, so a double episode is E02-03 and four episodes are E01-02-03-04. A spaced hyphen, as in <code>Title - Episode Name</code>, is not a release group. Clear a box to get the default back. The line under each box is this pattern filled with Avatar: Fire and Ash, or with a sample episode.</p>
            ${VIDEO_PATTERNS.filter(([key]) => key.startsWith("movie")).map(([key, label, note]) => `<label class="field pattern-field">${escapeHtml(label)}
                <textarea id="video-pattern-${key}" rows="2" spellcheck="false" data-video-pattern="${key}">${escapeHtml(rename[key] || "")}</textarea>
            </label>
            <p><button type="button" class="btn-ghost" data-pattern-builder="${key}">Syntax builder</button></p>
            <p class="pattern-example muted">Example: <span class="mono" data-pattern-out="${key}"></span></p>
            ${note ? `<p class="muted">${escapeHtml(note)}</p>` : ""}`).join("")}
            <h4>TV Show renaming patterns</h4>
            ${VIDEO_PATTERNS.filter(([key]) => !key.startsWith("movie")).map(([key, label, note]) => `<label class="field pattern-field">${escapeHtml(label)}
                <textarea id="video-pattern-${key}" rows="2" spellcheck="false" data-video-pattern="${key}">${escapeHtml(rename[key] || "")}</textarea>
            </label>
            <p><button type="button" class="btn-ghost" data-pattern-builder="${key}">Syntax builder</button></p>
            <p class="pattern-example muted">Example: <span class="mono" data-pattern-out="${key}"></span></p>
            ${note ? `<p class="muted">${escapeHtml(note)}</p>` : ""}`).join("")}
            <label class="field noise-field"><span>Filename words to ignore</span>
                <textarea id="video-filename-noise" rows="2" spellcheck="false">${escapeHtml(cfg.filename_noise == null ? "xpost, repost" : cfg.filename_noise)}</textarea>
            </label>
            <p class="muted">Words that sit after the release group and are not the group. <code>Name-CiNEPHiLES-xpost</code> stays CiNEPHiLES when xpost is listed. Separate words with a comma or a new line. Leave the box empty to ignore none of them. Quality words such as WEB-DL are already left out.</p>
            <h3>Subtitles</h3>
            <label class="field">Language codes ${videoSelect("video-sub-standard", cfg.sub_lang_standard || "iso639-2", [["iso639-2", "Three letters (eng, deu, pob)"], ["iso639-1", "Two letters (en, de, pt-br)"]])}</label>
            ${videoCheck("video-sub-rename", cfg.sub_rename !== false, "Rename sidecars to <video>.<language>[.forced][.default][.sdh][.commentary].<ext>")}
            ${videoCheck("video-sub-charset", cfg.sub_charset !== false, "Convert text subtitles to UTF-8 without BOM")}
            <label class="field">Line endings ${videoSelect("video-sub-endings", cfg.sub_line_endings || "lf", [["lf", "LF (Linux, Kodi)"], ["crlf", "CRLF (Windows)"]])}</label>
            ${videoCheck("video-sub-webhook", cfg.sub_on_webhook !== false, "Normalize subtitles after Radarr, Sonarr and Bazarr imports")}
            ${videoCheck("video-sub-purge", !!cfg.sub_purge_duplicates, "Remove duplicate subtitles")}
            <p class="muted">A sidecar whose text is the same as another sidecar of the video, or as a subtitle track inside the video, is deleted (compared by SHA-256, ignoring encoding and line endings). The best-named copy is kept. Checking the tracks inside a video reads the whole file. When this is off, duplicates are only listed in the log. Default from CMM_PURGE_DUPLICATE_SUBS.</p>
            <p class="muted">Subtitles without a recognisable language keep their name. When the new name is taken, the file is left alone and the log says so.</p>
            <h3>Subtitle sync</h3>
            ${videoCheck("video-subs-sync-after", cfg.subs_sync_after === true, "Sync a downloaded subtitle with the audio when it was not made for this exact file")}
            <p class="muted">Applies to subtitles from OpenSubtitles.com, from Find subtitles and from a scan. A subtitle matched by file hash is left as it is. Otherwise Curator runs the automatic sync (alass, fine-tune) and shifts the subtitle, unless the change it proposes is large, which is more often alass being fooled than a real error. A manual download syncs in the background and shows in the Jobs list.</p>
            ${videoCheck("video-sub-sync-notify", cfg.sub_sync_notify === true, "After syncing or exporting a subtitle, tell the players and Bazarr (players update their library; Bazarr re-reads the subtitles of that movie or show)")}
            <label class="field">Video preview copies, keep at most (GB, 0 = no limit) <input id="video-preview-cache-gb" type="number" min="0" max="500" step="0.5" value="${cfg.preview_cache_gb ?? 5}"></label>
            <label class="field">Recognised subtitle text, keep at most (MB, 0 = no limit) <input id="video-ocr-cache-mb" type="number" min="0" max="5000" step="10" value="${cfg.ocr_cache_mb ?? 100}"></label>
            <div id="sub-cache-info" class="muted">Loading cache sizes…</div>
            <p class="muted">Preview copies are small H.264 videos made only for videos a browser cannot play. Recognised text is what OCR read from VobSub and PGS pictures. Both can be rebuilt, and the least recently used files go first when a limit is passed. Picture subtitles need tesseract; add languages with the TESSERACT_LANGS build argument.</p>
            <h3>Extras</h3>
            <label class="field">Extras layout ${videoSelect("video-extras-layout", cfg.extras_layout || "kodi", [["kodi", "Kodi: <movie>-trailer next to the movie, the rest in Extras/"], ["plex", "Plex and Jellyfin: Trailers/, Featurettes/, Deleted Scenes/ …"]])}</label>
            <h3>Trailers</h3>
            <p class="muted">Trailer quality is set under General, Trailer download quality. Downloading after an import is set on the Movies tab (On Radarr import) and the TV Shows tab (On Sonarr import).</p>
            <p class="muted">Trailers come from the YouTube link the scraper saved, downloaded with yt-dlp and saved in the extras layout above. A movie is named like the movie file with -trailer. A show is tvshow-trailer.mp4 in the show folder. A season is Season 01-trailer.mp4 in the season folder, or in the show folder when the season has no folder of its own. Open a movie, show or season to play the local file, or the YouTube link until it is downloaded. Download trailer is on that page and on the right-click menu.</p>
            <h3>Theme songs</h3>
            ${videoCheck("video-theme-webhook", !!cfg.theme_on_webhook, "Download theme.mp3 after a Radarr or Sonarr import")}
            <p class="muted">Theme songs are saved as <code>theme.mp3</code> in the movie or show folder for Kodi, Plex, Emby, and Jellyfin. You can also download or play theme songs from the movie or show detail page and right-click menu.</p>
            <h3>Export</h3>
            <label class="field">Export format ${videoSelect("video-export-format", cfg.export_format || "csv", [["csv", "CSV (spreadsheets)"], ["xml", "XML"]])}</label>
            <p class="muted">Export in the toolbar saves what the shown list holds right now: the filter and ribbons apply, and so does the path picked in the Scan menu. TV exports one row per episode of the shown shows. Every metadata and media info field is included.</p>
        </section>`;
}

function sectionChecked(root, tab, selector) {
    const section = root.querySelector(`.settings-section[data-tab="${tab}"]`);
    const box = section && section.querySelector(selector);
    return !!(box && box.checked);
}

function visibleControl(root, selector) {
    const nodes = [...root.querySelectorAll(selector)];
    return nodes.find((node) => {
        const section = node.closest(".settings-section");
        return section && !section.classList.contains("hidden");
    }) || nodes[0] || null;
}

function visibleChecked(root, selector) {
    const box = visibleControl(root, selector);
    return !!(box && box.checked);
}

function splitNum(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
}

function visibleNumber(root, selector, fallback) {
    const input = visibleControl(root, selector);
    const number = input ? Number(input.value) : fallback;
    return Number.isFinite(number) && number > 0 ? number : fallback;
}

function readVideoSettings(root) {
    if (!root.querySelector("#video-dialect")) return;
    const video = { ...videoCfg() };
    root.querySelectorAll("[data-video-chain]").forEach((list) => {
        video[list.dataset.videoChain] = [...list.querySelectorAll("[data-source]")]
            .filter((item) => item.querySelector("[data-chain-on]").checked)
            .map((item) => item.dataset.source);
    });
    ["movie_fields", "show_fields", "season_fields", "episode_fields"].forEach((key) => {
        const boxes = [...root.querySelectorAll(`[data-meta-field="${key}"]`)];
        if (boxes.length) video[key] = boxes.filter((box) => box.checked).map((box) => box.value);
    });
    ["movie_art", "tv_art", "season_art", "set_art"].forEach((key) => {
        video[key] = {};
        root.querySelectorAll(`[data-video-art="${key}"]`).forEach((input) => { video[key][input.value] = input.checked; });
    });
    video.min_width = { ...(video.min_width || {}) };
    root.querySelectorAll("[data-video-min]").forEach((input) => { video.min_width[input.dataset.videoMin] = Number(input.value) || 0; });
    const value = (id) => (document.getElementById(id) || {}).value;
    const checked = (id) => !!(document.getElementById(id) || {}).checked;
    Object.assign(video, {
        language: value("video-language"), country: value("video-country"),
        art_languages: [0, 1, 2, 3].map((index) => value(`video-art-lang-${index}`) || ""),
        default_rating: value("video-default-rating"),
        nfo_dialect: value("video-dialect"), movie_nfo_name: value("video-nfo-name"),
        write_nfo: checked("video-write-nfo"), download_artwork: checked("video-download-art"), nfo_backup: checked("video-nfo-backup"),
        scan_fill_missing: visibleChecked(root, "[data-video-scan-fill]"),
        scan_limited_art: visibleChecked(root, "[data-video-scan-limited]"),
        scan_download_trailers: sectionChecked(root, "movies", "[data-video-scan-trailers]"),
        scan_download_tv_trailers: sectionChecked(root, "tv", "[data-video-scan-trailers]"),
        subs_download_movies: sectionChecked(root, "movies", "[data-video-scan-subs]"),
        subs_download_tv: sectionChecked(root, "tv", "[data-video-scan-subs]"),
        subs_username: value("video-subs-username"),
        subs_languages: value("video-subs-languages") || "en",
        subs_hearing_impaired: value("video-subs-hearing") || "exclude",
        scan_download_themes: sectionChecked(root, "movies", "[data-video-scan-themes]"),
        scan_download_tv_themes: sectionChecked(root, "tv", "[data-video-scan-themes]"),
        scan_rewrite_nfo: visibleChecked(root, "[data-video-scan-rewrite-nfo]"),
        scan_split_notify: checked("video-scan-split-notify"),
        sub_sync_notify: checked("video-sub-sync-notify"),
        subs_sync_after: checked("video-subs-sync-after"),
        preview_cache_gb: Math.max(0, Number(value("video-preview-cache-gb")) || 0),
        ocr_cache_mb: Math.max(0, Number(value("video-ocr-cache-mb")) || 0),
        scan_iso: visibleChecked(root, "[data-video-scan-iso]"),
        collapse_versions: sectionChecked(root, "movies", "[data-video-collapse]"),
        ui_movie_year: checked("video-ui-movie-year"),
        ui_movie_edition: checked("video-ui-movie-edition"),
        ui_movie_date_added: checked("video-ui-movie-date-added"),
        ui_movie_processed: checked("video-ui-movie-processed"),
        ui_movie_art_badges: checked("video-ui-movie-art-badges"),
        ui_movie_poster_badges: checked("video-ui-movie-poster-badges"),
        ui_tv_poster_badges: checked("video-ui-tv-poster-badges"),
        ui_set_poster_badges: checked("video-ui-set-poster-badges"),
        ui_music_poster_badges: checked("video-ui-music-poster-badges"),
        ui_tv_year: checked("video-ui-tv-year"),
        ui_tv_seasons: checked("video-ui-tv-seasons"),
        ui_tv_episodes: checked("video-ui-tv-episodes"),
        ui_tv_date_added: checked("video-ui-tv-date-added"),
        ui_tv_processed: checked("video-ui-tv-processed"),
        ui_tv_progress: checked("video-ui-tv-progress"),
        ui_tv_art_badges: checked("video-ui-tv-art-badges"),
        ui_set_art_badges: checked("video-ui-set-art-badges"),
        ui_set_processed: checked("video-ui-set-processed"),
        ui_music_art_badges: checked("video-ui-music-art-badges"),
        ui_music_edition_badge: checked("video-ui-music-edition-badge"),
        ui_music_date_added: checked("video-ui-music-date-added"),
        ui_music_processed: checked("video-ui-music-processed"),
        export_format_music: value("video-export-format-music") || "csv",
        omdb_patron: checked("omdb-patron"),
        extrafanart_count: visibleNumber(root, "[data-video-extrafanart-count]", 10),
        write_on_edit: checked("video-write-on-edit"), actor_thumbs: checked("video-actor-thumbs"), keywords_as_tags: checked("video-keywords"),
        concurrency: Number(value("video-concurrency")) || 4,
        policies: ["movies", "tv", "sets"].reduce((out, media) => {
            out[media] = {
                metadata: checked(`policy-${media}-metadata`),
                artwork: checked(`policy-${media}-artwork`),
            };
            return out;
        }, {}),
        probe_workers: Math.max(1, Math.min(20, Number(value("probe-workers")) || Number(video.probe_workers) || 20)),
        tv_primary: value("video-tv-primary"),
        episode_order: value("video-episode-order"), episode_thumbs: checked("video-episode-thumbs"), scan_generate_ep_thumb: checked("video-scan-gen-ep-thumb"),
        set_folder: (value("video-set-folder") || "").trim(), set_nfo: checked("video-set-nfo"),
        sub_lang_standard: value("video-sub-standard"), sub_rename: checked("video-sub-rename"),
        sub_charset: checked("video-sub-charset"), sub_line_endings: value("video-sub-endings"),
        sub_on_webhook: checked("video-sub-webhook"), sub_purge_duplicates: checked("video-sub-purge"), extras_layout: value("video-extras-layout"),
        trailer_resolution: value("video-trailer-resolution"), trailer_on_webhook: checked("video-trailer-webhook"), trailer_on_sonarr_season: checked("video-trailer-sonarr"),
        theme_on_webhook: checked("video-theme-webhook"),
        export_format: value("video-export-format") || "csv",
        filename_noise: (value("video-filename-noise") || "").trim(),
        split_chapter_window: Number(value("video-split-chapter-window")),
        split_detect_window: Number(value("video-split-detect-window")),
        split_wide_window: Number(value("video-split-wide-window")),
        split_cut_at: value("video-split-cut-at"),
        split_black_seconds: Number(value("video-split-black-seconds")),
        split_black_pic: Number(value("video-split-black-pic")),
        split_black_pix: Number(value("video-split-black-pix")),
        split_silence_db: Number(value("video-split-silence-db")),
        split_silence_seconds: Number(value("video-split-silence-seconds")),
        split_overlap_seconds: Number(value("video-split-overlap")),
        split_ambiguous_anchor: Number(value("video-split-ambiguous-anchor")),
        split_ambiguous_apart: Number(value("video-split-ambiguous-apart")),
        split_min_part: Number(value("video-split-min-part")),
        trakt_sync_mode: value("trakt-sync-mode") || video.trakt_sync_mode,
        trakt_sync_hours: Number(value("trakt-sync-hours")) || 0,
    });
    video.rename = {};
    root.querySelectorAll("[data-video-pattern]").forEach((input) => { video.rename[input.dataset.videoPattern] = input.value.trim(); });
    state.settings.video = video;
    root.querySelectorAll("[data-video-key]").forEach((input) => {
        if (input.value.trim()) state.settings[input.dataset.videoKey] = input.value;
    });
}

function schedulePatternExamples() {
    clearTimeout(state.patternExampleTimer);
    state.patternExampleTimer = setTimeout(() => {
        paintPatternExamples();
        paintMusicRenameExample();
    }, 300);
}

async function paintMusicRenameExample() {
    const node = document.getElementById("music-rename-example");
    const folder = document.getElementById("music-rename-folder");
    const file = document.getElementById("music-rename-file");
    if (!node || !folder || !file) return;
    try {
        const data = await api("/api/rename/example", {
            method: "POST",
            body: { rename_folder_pattern: folder.value, rename_file_pattern: file.value },
        });
        node.textContent = data.error || data.path || "";
        const line = node.closest(".pattern-example");
        if (line) line.classList.toggle("is-bad", !!data.error);
    } catch (error) {
        node.textContent = "";
    }
}

async function paintPatternExamples() {
    if (!document.querySelector("[data-pattern-out]")) return;
    const rename = {};
    document.querySelectorAll("[data-video-pattern]").forEach((input) => { rename[input.dataset.videoPattern] = input.value; });
    let data;
    try {
        data = await api("/api/v1/files/patterns", { method: "POST", body: { rename } });
    } catch (error) {
        return;
    }
    document.querySelectorAll("[data-pattern-out]").forEach((node) => {
        const key = node.dataset.patternOut;
        const problem = (data.errors || {})[key];
        const line = node.closest(".pattern-example");
        node.textContent = problem || (data.examples || {})[key] || "";
        if (line) line.classList.toggle("is-bad", !!problem);
    });
}

document.addEventListener("input", (event) => {
    if (event.target.matches && (event.target.matches("[data-video-pattern]") || event.target.id === "music-rename-folder" || event.target.id === "music-rename-file")) schedulePatternExamples();
});

document.addEventListener("change", (event) => {
    if (!event.target.matches) return;
    ["data-sort-ignore-the", "data-video-scan-fill", "data-video-scan-limited", "data-video-scan-rewrite-nfo", "data-video-scan-iso", "data-video-collapse"].forEach((name) => {
        if (!event.target.matches(`[${name}]`)) return;
        document.querySelectorAll(`[${name}]`).forEach((box) => { box.checked = event.target.checked; });
    });
    if (event.target.matches("[data-chain-on]")) {
        const row = event.target.closest(".priority-item");
        if (row) row.classList.toggle("is-off", !event.target.checked);
    }
});

function moveVideoChain(button) {
    const item = button.closest(".priority-item");
    if (!item) return;
    if (Number(button.dataset.dir) < 0 && item.previousElementSibling) item.parentNode.insertBefore(item, item.previousElementSibling);
    else if (Number(button.dataset.dir) > 0 && item.nextElementSibling) item.parentNode.insertBefore(item.nextElementSibling, item);
}


function formatCacheBytes(bytes) {
    const units = ["B", "KB", "MB", "GB"];
    let n = Number(bytes) || 0, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

async function loadSubCacheInfo() {
    const box = document.getElementById("sub-cache-info");
    if (!box) return;
    try {
        const data = await api("/api/v1/subs/cache");
        const row = (which, label) => {
            const c = data.caches[which] || { files: 0, bytes: 0, limit_bytes: 0 };
            const cap = c.limit_bytes ? ` of ${formatCacheBytes(c.limit_bytes)}` : "";
            return `<div>${label}: ${formatCacheBytes(c.bytes)}${cap} in ${c.files} file${c.files === 1 ? "" : "s"}
                <button type="button" class="ghost" data-sub-cache-clear="${which}">Clear</button></div>`;
        };
        const ocr = data.tesseract
            ? `Picture subtitle OCR is ready. Languages installed: ${escapeHtml((data.languages || []).join(", ") || "none")}.`
            : "Picture subtitle OCR is not available: tesseract is not installed in this container.";
        const auto = data.alass ? "Automatic sync (alass) is ready." : "Automatic sync is not available: alass is not installed in this container.";
        box.innerHTML = `${ocr}<div>${auto}</div>${row("preview", "Video previews")}${row("ocr", "Recognised text")}`;
        box.querySelectorAll("[data-sub-cache-clear]").forEach((button) => {
            button.addEventListener("click", async () => {
                button.disabled = true;
                try { await api("/api/v1/subs/cache/clear", { method: "POST", body: { which: button.dataset.subCacheClear } }); } catch (error) { /* shown by api() */ }
                loadSubCacheInfo();
            });
        });
    } catch (error) {
        box.textContent = "Cache sizes are not available.";
    }
}
