// Syntax builder for the Jinja2 rename patterns (Settings, Files). The pieces are clicked together and
// written back into the pattern box. Nothing is saved until Save settings is pressed.

const PB_MEDIA = [
    ["media.quality", "Quality", "plain"],
    ["media.source", "Source (BluRay, WEB-DL)", "text"],
    ["media.resolution", "Resolution", "plain"],
    ["media.audio_codec", "Audio codec", "text"],
    ["media.audio_channels", "Audio channels", "plain"],
    ["media.hdr", "HDR format", "text"],
    ["media.video_codec", "Video codec", "text"],
    ["media.hybrid", "Hybrid", "plain"],
    ["media.format", "Format", "plain"],
    ["media.release_group", "Release group", "plain"],
];
const PB_FIELDS = {
    movie: [
        ["movie.title", "Title", "text"], ["movie.year", "Year", "plain"], ["movie.edition", "Edition", "text"],
        ["movie.id.tmdb", "TMDB id", "plain"], ["movie.id.imdb", "IMDb id", "plain"], ["movie.set", "Movie set", "text"],
    ],
    moviePart: [["movie.part", "Part (part1, part2)", "plain"]],
    show: [["show.title", "Show title", "text"], ["show.year", "Show year", "plain"], ["show.id.tvdb", "TVDB id", "plain"]],
    episode: [
        ["episode.season", "Season number", "num"], ["episode.season_raw", "Season number (no padding)", "plain"],
        ["episode.number", "Episode number(s)", "num"], ["episode.title", "Episode title", "text"],
    ],
    media: PB_MEDIA,
};
const PB_GROUPS = {
    movie_folder: [["Movie", "movie"], ["Media", "media"]],
    movie_file: [["Movie", "movie"], ["Part", "moviePart"], ["Media", "media"]],
    show_folder: [["Show", "show"]],
    season_folder: [["Season", "episode"]],
    episode_file: [["Show", "show"], ["Episode", "episode"], ["Media", "media"]],
};

// Presets. f = field, t = text, r = raw Jinja2. Fields carry: sep (text placed before), opt (skip when empty),
// dot, san, pad.
const pbF = (expr, o = {}) => ({ type: "field", expr, sep: "", opt: false, dot: false, san: false, pad: 0, ...o });
const pbT = (value) => ({ type: "text", value });
const pbR = (value) => ({ type: "raw", value });
const PB_MEDIA_DOTTED = [
    pbF("media.quality", { sep: ".", opt: true }), pbF("media.source", { sep: ".", opt: true, dot: true }),
    pbF("media.resolution", { sep: ".", opt: true }), pbF("media.audio_codec", { sep: ".", opt: true, dot: true }),
    pbF("media.audio_channels", { sep: ".", opt: true }), pbF("media.hdr", { sep: ".", opt: true, dot: true }),
    pbF("media.video_codec", { sep: ".", opt: true, dot: true }),
];
const PB_GROUP = pbF("media.release_group", { sep: "-", opt: true });
const PB_PRESETS = {
    movie_folder: [
        ["Title (Year)", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(")")]],
        ["Title (Year) [tmdbid-123]", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(")"), pbF("movie.id.tmdb", { sep: " [tmdbid-", opt: true }), pbR("{% if movie.id.tmdb %}]{% endif %}")]],
        ["Title (Year) {imdb-tt123}", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(")"), pbF("movie.id.imdb", { sep: " {imdb-", opt: true }), pbR("{% if movie.id.imdb %}}{% endif %}")]],
        ["Title.Year.Edition.Resolution.Source-ReleaseGroup", [pbF("movie.title", { dot: true }), pbF("movie.year", { sep: ".", opt: true }), pbF("movie.edition", { sep: ".", opt: true, dot: true }), pbF("media.resolution", { sep: ".", opt: true }), pbF("media.source", { sep: ".", opt: true, dot: true }), PB_GROUP]],
        ["Title.Year plus full media info-ReleaseGroup", [pbF("movie.title", { dot: true }), pbF("movie.year", { sep: ".", opt: true }), ...PB_MEDIA_DOTTED, PB_GROUP]],
    ],
    movie_file: [
        ["Title (Year)", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(")")]],
        ["Title (Year) - Resolution", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(") - "), pbF("media.resolution", { opt: true })]],
        ["Title (Year) - part1", [pbF("movie.title", { san: true }), pbT(" ("), pbF("movie.year"), pbT(")"), pbF("movie.part", { sep: " - ", opt: true })]],
        ["Title.Year.Resolution.Source-ReleaseGroup", [pbF("movie.title", { dot: true }), pbF("movie.year", { sep: ".", opt: true }), pbF("media.resolution", { sep: ".", opt: true }), pbF("media.source", { sep: ".", opt: true, dot: true }), pbF("movie.part", { sep: ".", opt: true }), PB_GROUP]],
        ["Title.Year plus full media info-ReleaseGroup", [pbF("movie.title", { dot: true }), pbF("movie.year", { sep: ".", opt: true }), ...PB_MEDIA_DOTTED, pbF("movie.part", { sep: ".", opt: true }), PB_GROUP]],
    ],
    show_folder: [
        ["Show Title (Year)", [pbF("show.title", { san: true }), pbF("show.year", { sep: " (", opt: true }), pbR("{% if show.year %}){% endif %}")]],
        ["Show Title (Year) [tvdbid-123]", [pbF("show.title", { san: true }), pbF("show.year", { sep: " (", opt: true }), pbR("{% if show.year %}){% endif %}"), pbF("show.id.tvdb", { sep: " [tvdbid-", opt: true }), pbR("{% if show.id.tvdb %}]{% endif %}")]],
        ["Show.Title.Year", [pbF("show.title", { dot: true }), pbF("show.year", { sep: ".", opt: true })]],
        ["Show.Title.Year.tvdbid-123", [pbF("show.title", { dot: true }), pbF("show.year", { sep: ".", opt: true }), pbF("show.id.tvdb", { sep: ".tvdbid-", opt: true })]],
    ],
    season_folder: [
        ["Season 1 / Specials", [pbR("{% if episode.season_raw == 0 %}Specials{% else %}Season {{ episode.season_raw }}{% endif %}")]],
        ["Season 01 / Specials", [pbR("{% if episode.season_raw == 0 %}Specials{% else %}Season {{ episode.season | pad(2) }}{% endif %}")]],
        ["S01", [pbT("S"), pbF("episode.season", { pad: 2 })]],
        ["Season.01", [pbT("Season."), pbF("episode.season", { pad: 2 })]],
    ],
    episode_file: [
        ["Show.S01E01.Episode.Title", [pbF("show.title", { dot: true }), pbT(".S"), pbF("episode.season", { pad: 2 }), pbT("E"), pbF("episode.number", { pad: 2 }), pbF("episode.title", { sep: ".", opt: true, dot: true })]],
        ["Show - S01E01 - Episode Title", [pbF("show.title", { san: true }), pbT(" - S"), pbF("episode.season", { pad: 2 }), pbT("E"), pbF("episode.number", { pad: 2 }), pbF("episode.title", { sep: " - ", opt: true, san: true })]],
        ["Show.S01E01.Title.Resolution.Source-ReleaseGroup", [pbF("show.title", { dot: true }), pbT(".S"), pbF("episode.season", { pad: 2 }), pbT("E"), pbF("episode.number", { pad: 2 }), pbF("episode.title", { sep: ".", opt: true, dot: true }), pbF("media.resolution", { sep: ".", opt: true }), pbF("media.source", { sep: ".", opt: true, dot: true }), PB_GROUP]],
        ["Show.S01E01.Title plus full media info-ReleaseGroup", [pbF("show.title", { dot: true }), pbT(".S"), pbF("episode.season", { pad: 2 }), pbT("E"), pbF("episode.number", { pad: 2 }), pbF("episode.title", { sep: ".", opt: true, dot: true }), ...PB_MEDIA_DOTTED, PB_GROUP]],
        ["1x01 - Episode Title", [pbF("episode.season_raw"), pbT("x"), pbF("episode.number", { pad: 2 }), pbF("episode.title", { sep: " - ", opt: true, san: true })]],
    ],
};

const pb = { key: null, tokens: [], timer: null };

function pbCondition(expr) {
    return expr === "media.hdr" ? "media.hdr and media.hdr != 'SDR'" : expr;
}

function pbBuild(tokens) {
    return tokens.map((token) => {
        if (token.type === "text" || token.type === "raw") return token.value;
        const filters = [];
        if (token.san) filters.push("sanitize");
        if (token.dot) filters.push("dot");
        if (token.pad) filters.push(`pad(${token.pad})`);
        const body = `${token.sep || ""}{{ ${token.expr}${filters.map((name) => ` | ${name}`).join("")} }}`;
        return token.opt ? `{% if ${pbCondition(token.expr)} %}${body}{% endif %}` : body;
    }).join("");
}

function pbFieldKind(expr) {
    for (const rows of Object.values(PB_FIELDS)) {
        const row = rows.find((item) => item[0] === expr);
        if (row) return row[2];
    }
    return "plain";
}

function pbEnsureModal() {
    let modal = document.getElementById("pattern-builder-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "pattern-builder-modal";
    modal.className = "modal hidden";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "pattern-builder-title");
    modal.innerHTML = `<div class="modal-content pattern-builder">
        <div class="modal-header">
            <h2 id="pattern-builder-title">Syntax builder</h2>
            <button type="button" class="btn-ghost" data-pb-close>Close</button>
        </div>
        <div class="modal-body" id="pattern-builder-body"></div>
    </div>`;
    document.body.appendChild(modal);
    return modal;
}

function pbRender() {
    const body = document.getElementById("pattern-builder-body");
    if (!body) return;
    const label = (VIDEO_PATTERNS.find((row) => row[0] === pb.key) || [pb.key, pb.key])[1];
    document.getElementById("pattern-builder-title").textContent = `Syntax builder: ${label}`;
    const groups = (PB_GROUPS[pb.key] || []).map(([title, group]) => `<div class="pb-group"><span class="pb-group-title">${escapeHtml(title)}</span>
        ${PB_FIELDS[group].map(([expr, name]) => `<button type="button" class="btn-ghost pb-chip" data-pb-add="${escapeHtml(expr)}" title="${escapeHtml(expr)}">${escapeHtml(name)}</button>`).join("")}</div>`).join("");
    const presets = (PB_PRESETS[pb.key] || []).map(([name], index) => `<button type="button" class="btn-ghost pb-chip" data-pb-preset="${index}">${escapeHtml(name)}</button>`).join("");
    const rows = pb.tokens.map((token, index) => {
        const move = `<button type="button" class="btn-ghost pb-small" data-pb-up="${index}" aria-label="Move up">↑</button><button type="button" class="btn-ghost pb-small" data-pb-down="${index}" aria-label="Move down">↓</button><button type="button" class="btn-ghost pb-small" data-pb-del="${index}" aria-label="Remove">✕</button>`;
        if (token.type === "text") {
            return `<div class="pb-row"><span class="pb-kind">Text</span><input type="text" class="pb-input" data-pb-text="${index}" value="${escapeHtml(token.value)}" placeholder="Free text or a separator, for example ' - ' or '.'" spellcheck="false">${move}</div>`;
        }
        if (token.type === "raw") {
            return `<div class="pb-row"><span class="pb-kind">Rule</span><code class="pb-raw">${escapeHtml(token.value)}</code>${move}</div>`;
        }
        const kind = pbFieldKind(token.expr);
        return `<div class="pb-row"><span class="pb-kind mono">${escapeHtml(token.expr)}</span>
            <label class="pb-opt">Before <input type="text" class="pb-input pb-sep" data-pb-sep="${index}" value="${escapeHtml(token.sep)}" placeholder="separator" spellcheck="false"></label>
            <label class="pb-opt"><input type="checkbox" data-pb-flag="opt" data-pb-i="${index}" ${token.opt ? "checked" : ""}> Skip when empty</label>
            ${kind === "text" ? `<label class="pb-opt"><input type="checkbox" data-pb-flag="dot" data-pb-i="${index}" ${token.dot ? "checked" : ""}> Dots</label>
            <label class="pb-opt"><input type="checkbox" data-pb-flag="san" data-pb-i="${index}" ${token.san ? "checked" : ""}> Clean</label>` : ""}
            ${kind === "num" ? `<label class="pb-opt"><input type="checkbox" data-pb-flag="pad" data-pb-i="${index}" ${token.pad ? "checked" : ""}> Two digits</label>` : ""}
            ${move}</div>`;
    }).join("");
    body.innerHTML = `<p class="muted">Click a piece to add it, or start from a ready-made pattern. Add free text or separators between the pieces. Skip when empty drops the separator too when a value is missing. Dots joins words with periods. Clean removes characters a file name cannot hold.</p>
        <div class="pb-section"><span class="pb-group-title">Ready-made</span><div class="pb-chips">${presets}</div></div>
        <div class="pb-section">${groups}<div class="pb-group"><span class="pb-group-title">Text</span><button type="button" class="btn-ghost pb-chip" data-pb-add-text>+ Free text</button></div></div>
        <div class="pb-section"><span class="pb-group-title">Your pattern</span>
            <div class="pb-rows">${rows || '<p class="muted">Nothing yet. Pick a piece above.</p>'}</div></div>
        <div class="pb-section"><span class="pb-group-title">Result</span>
            <textarea class="pb-output mono" id="pb-output" rows="3" readonly spellcheck="false">${escapeHtml(pbBuild(pb.tokens))}</textarea>
            <p class="pattern-example muted" id="pb-example-line">Example: <span class="mono" id="pb-example"></span></p></div>
        <div class="pb-actions"><button type="button" class="btn-primary" data-pb-use>Use this pattern</button> <button type="button" class="btn-ghost" data-pb-clear>Clear</button> <button type="button" class="btn-ghost" data-pb-close>Cancel</button></div>`;
    pbExample();
}

function pbExample() {
    clearTimeout(pb.timer);
    pb.timer = setTimeout(async () => {
        const out = document.getElementById("pb-example");
        if (!out) return;
        const built = pbBuild(pb.tokens);
        document.getElementById("pb-output").value = built;
        if (!built) { out.textContent = ""; return; }
        try {
            const data = await api("/api/v1/files/patterns", { method: "POST", body: { rename: { [pb.key]: built } } });
            const problem = (data.errors || {})[pb.key];
            out.textContent = problem || (data.examples || {})[pb.key] || "";
            document.getElementById("pb-example-line").classList.toggle("is-bad", !!problem);
        } catch (error) {
            out.textContent = "";
        }
    }, 200);
}

function pbOpen(key) {
    pb.key = key;
    pb.tokens = [];
    pbEnsureModal().classList.remove("hidden");
    pbRender();
}

function pbClose() {
    const modal = document.getElementById("pattern-builder-modal");
    if (modal) modal.classList.add("hidden");
}

function pbSwap(index, other) {
    if (other < 0 || other >= pb.tokens.length) return;
    [pb.tokens[index], pb.tokens[other]] = [pb.tokens[other], pb.tokens[index]];
}

document.addEventListener("click", (event) => {
    const el = event.target.closest && event.target.closest("[data-pattern-builder], [data-pb-close], [data-pb-add], [data-pb-add-text], [data-pb-preset], [data-pb-up], [data-pb-down], [data-pb-del], [data-pb-use], [data-pb-clear]");
    if (!el) return;
    const data = el.dataset;
    if (data.patternBuilder) return pbOpen(data.patternBuilder);
    if ("pbClose" in data) return pbClose();
    if (data.pbAdd) {
        const first = !pb.tokens.length;
        const expr = data.pbAdd;
        const sepDefault = !first && /^media\./.test(expr) ? "." : "";
        const kind = pbFieldKind(expr);
        pb.tokens.push(pbF(expr, { sep: expr === "media.release_group" && !first ? "-" : sepDefault, opt: /^media\./.test(expr), dot: kind === "text", pad: kind === "num" ? 2 : 0 }));
    } else if ("pbAddText" in data) {
        pb.tokens.push(pbT(" - "));
    } else if (data.pbPreset !== undefined) {
        pb.tokens = JSON.parse(JSON.stringify(PB_PRESETS[pb.key][Number(data.pbPreset)][1]));
    } else if (data.pbUp !== undefined) {
        pbSwap(Number(data.pbUp), Number(data.pbUp) - 1);
    } else if (data.pbDown !== undefined) {
        pbSwap(Number(data.pbDown), Number(data.pbDown) + 1);
    } else if (data.pbDel !== undefined) {
        pb.tokens.splice(Number(data.pbDel), 1);
    } else if ("pbClear" in data) {
        pb.tokens = [];
    } else if ("pbUse" in data) {
        const input = document.getElementById(`video-pattern-${pb.key}`);
        if (input) {
            input.value = pbBuild(pb.tokens);
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return pbClose();
    }
    pbRender();
});

document.addEventListener("input", (event) => {
    const el = event.target;
    if (!el.dataset) return;
    if (el.dataset.pbText !== undefined) pb.tokens[Number(el.dataset.pbText)].value = el.value;
    else if (el.dataset.pbSep !== undefined) pb.tokens[Number(el.dataset.pbSep)].sep = el.value;
    else return;
    pbExample();
});

document.addEventListener("change", (event) => {
    const el = event.target;
    if (!el.dataset || !el.dataset.pbFlag) return;
    const token = pb.tokens[Number(el.dataset.pbI)];
    token[el.dataset.pbFlag] = el.dataset.pbFlag === "pad" ? (el.checked ? 2 : 0) : el.checked;
    pbRender();
});
