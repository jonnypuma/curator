// Syntax builder for the music rename patterns (Settings, Files). Same idea as the movie and TV builder, but it
// writes the %token% / $function() syntax. Nothing is saved until Save settings is pressed.

const MB_FIELDS = [
    ["albumartist", "Album artist"], ["albumartists", "Album artists"], ["artist", "Artist"], ["artists", "Artists"],
    ["album", "Album"], ["year", "Year"], ["edition", "Edition"], ["releasegroup", "Release group"], ["format", "Format"],
    ["title", "Track title"], ["tracknumber", "Track number"], ["discnumber", "Disc number"], ["totaldiscs", "Total discs"],
];
const MB_NUMBERS = new Set(["tracknumber", "discnumber"]);
const mbF = (name, o = {}) => ({ type: "field", name, before: "", after: "", opt: false, pad: 0, ...o });
const mbT = (value) => ({ type: "text", value });
const mbR = (value) => ({ type: "raw", value });
const MB_CD = mbR("$if(%multidisc%,/CD%discnumber%)");
const MB_PRESETS = {
    "music-rename-folder": [
        ["Album Artist/[Year] Album (CD folders)", [mbF("albumartist"), mbT("/["), mbF("year"), mbT("] "), mbF("album"), MB_CD]],
        ["Album Artist/Album (Year)", [mbF("albumartist"), mbT("/"), mbF("album"), mbF("year", { before: " (", after: ")", opt: true }), MB_CD]],
        ["Album Artist/Year - Album", [mbF("albumartist"), mbT("/"), mbF("year"), mbT(" - "), mbF("album"), MB_CD]],
        ["Album Artist/Album", [mbF("albumartist"), mbT("/"), mbF("album"), MB_CD]],
    ],
    "music-rename-file": [
        ["Disc 1 - 01 - Title", [mbT("Disc "), mbF("discnumber"), mbT(" - "), mbF("tracknumber", { pad: 2 }), mbT(" - "), mbF("title")]],
        ["01 - Title", [mbF("tracknumber", { pad: 2 }), mbT(" - "), mbF("title")]],
        ["01 Title", [mbF("tracknumber", { pad: 2 }), mbT(" "), mbF("title")]],
        ["Artist - Title", [mbF("artist"), mbT(" - "), mbF("title")]],
    ],
};
const mb = { target: null, tokens: [], timer: null };

function mbBuild(tokens) {
    return tokens.map((token) => {
        if (token.type !== "field") return token.value;
        const core = token.pad ? `$num(%${token.name}%,${token.pad})` : `%${token.name}%`;
        if (token.opt) return `$if(%${token.name}%,${token.before}${core}${token.after})`;
        return `${token.before}${core}${token.after}`;
    }).join("");
}

function mbEnsureModal() {
    let modal = document.getElementById("music-builder-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "music-builder-modal";
    modal.className = "modal hidden";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "music-builder-title");
    modal.innerHTML = `<div class="modal-content pattern-builder">
        <div class="modal-header"><h2 id="music-builder-title">Syntax builder</h2><button type="button" class="btn-ghost" data-mb-close>Close</button></div>
        <div class="modal-body" id="music-builder-body"></div></div>`;
    document.body.appendChild(modal);
    return modal;
}

function mbRender() {
    const body = document.getElementById("music-builder-body");
    if (!body) return;
    const folder = mb.target === "music-rename-folder";
    document.getElementById("music-builder-title").textContent = `Syntax builder: Music ${folder ? "folder structure" : "file name"}`;
    const presets = (MB_PRESETS[mb.target] || []).map(([name], i) => `<button type="button" class="btn-ghost pb-chip" data-mb-preset="${i}">${escapeHtml(name)}</button>`).join("");
    const chips = MB_FIELDS.map(([name, label]) => `<button type="button" class="btn-ghost pb-chip" data-mb-add="${name}" title="%${name}%">${escapeHtml(label)}</button>`).join("");
    const extras = `<button type="button" class="btn-ghost pb-chip" data-mb-add-text>+ Free text</button>${folder ? `<button type="button" class="btn-ghost pb-chip" data-mb-add-text="/">+ Folder separator /</button><button type="button" class="btn-ghost pb-chip" data-mb-add-raw="$if(%multidisc%,/CD%discnumber%)">+ CD folder for multi-disc</button>` : ""}`;
    const rows = mb.tokens.map((token, i) => {
        const move = `<button type="button" class="btn-ghost pb-small" data-mb-up="${i}" aria-label="Move up">↑</button><button type="button" class="btn-ghost pb-small" data-mb-down="${i}" aria-label="Move down">↓</button><button type="button" class="btn-ghost pb-small" data-mb-del="${i}" aria-label="Remove">✕</button>`;
        if (token.type === "text") return `<div class="pb-row"><span class="pb-kind">Text</span><input type="text" class="pb-input" data-mb-text="${i}" value="${escapeHtml(token.value)}" placeholder="Free text or a separator" spellcheck="false">${move}</div>`;
        if (token.type === "raw") return `<div class="pb-row"><span class="pb-kind">Rule</span><code class="pb-raw">${escapeHtml(token.value)}</code>${move}</div>`;
        return `<div class="pb-row"><span class="pb-kind mono">%${escapeHtml(token.name)}%</span>
            <label class="pb-opt">Before <input type="text" class="pb-input pb-sep" data-mb-before="${i}" value="${escapeHtml(token.before)}" spellcheck="false"></label>
            <label class="pb-opt">After <input type="text" class="pb-input pb-sep" data-mb-after="${i}" value="${escapeHtml(token.after)}" spellcheck="false"></label>
            <label class="pb-opt"><input type="checkbox" data-mb-flag="opt" data-mb-i="${i}" ${token.opt ? "checked" : ""}> Skip when empty</label>
            ${MB_NUMBERS.has(token.name) ? `<label class="pb-opt"><input type="checkbox" data-mb-flag="pad" data-mb-i="${i}" ${token.pad ? "checked" : ""}> Two digits</label>` : ""}
            ${move}</div>`;
    }).join("");
    body.innerHTML = `<p class="muted">Click a piece to add it, or start from a ready-made pattern. Before and After put text around a value; Skip when empty drops that text too when the value is missing.</p>
        <div class="pb-section"><span class="pb-group-title">Ready-made</span><div class="pb-chips">${presets}</div></div>
        <div class="pb-section"><div class="pb-group"><span class="pb-group-title">Fields</span>${chips}</div><div class="pb-group"><span class="pb-group-title">Other</span>${extras}</div></div>
        <div class="pb-section"><span class="pb-group-title">Your pattern</span><div class="pb-rows">${rows || '<p class="muted">Nothing yet. Pick a piece above.</p>'}</div></div>
        <div class="pb-section"><span class="pb-group-title">Result</span>
            <textarea class="pb-output mono" id="mb-output" rows="2" readonly spellcheck="false">${escapeHtml(mbBuild(mb.tokens))}</textarea>
            <p class="pattern-example muted" id="mb-example-line">Example: <span class="mono" id="mb-example"></span></p></div>
        <div class="pb-actions"><button type="button" class="btn-primary" data-mb-use>Use this pattern</button> <button type="button" class="btn-ghost" data-mb-clear>Clear</button> <button type="button" class="btn-ghost" data-mb-close>Cancel</button></div>`;
    mbExample();
}

function mbExample() {
    clearTimeout(mb.timer);
    mb.timer = setTimeout(async () => {
        const out = document.getElementById("mb-example");
        if (!out) return;
        const built = mbBuild(mb.tokens);
        document.getElementById("mb-output").value = built;
        const folderBox = document.getElementById("music-rename-folder");
        const fileBox = document.getElementById("music-rename-file");
        if (!built || !folderBox || !fileBox) { out.textContent = ""; return; }
        const folder = mb.target === "music-rename-folder";
        try {
            const data = await api("/api/rename/example", { method: "POST", body: {
                rename_folder_pattern: folder ? built : folderBox.value,
                rename_file_pattern: folder ? fileBox.value : built,
            } });
            out.textContent = data.error || data.path || "";
            document.getElementById("mb-example-line").classList.toggle("is-bad", !!data.error);
        } catch (error) {
            out.textContent = "";
        }
    }, 200);
}

function mbClose() {
    const modal = document.getElementById("music-builder-modal");
    if (modal) modal.classList.add("hidden");
}

document.addEventListener("click", (event) => {
    const el = event.target.closest && event.target.closest("[data-music-builder], [data-mb-close], [data-mb-add], [data-mb-add-text], [data-mb-add-raw], [data-mb-preset], [data-mb-up], [data-mb-down], [data-mb-del], [data-mb-use], [data-mb-clear]");
    if (!el) return;
    const d = el.dataset;
    if (d.musicBuilder) {
        mb.target = d.musicBuilder;
        mb.tokens = [];
        mbEnsureModal().classList.remove("hidden");
        return mbRender();
    }
    if ("mbClose" in d) return mbClose();
    if (d.mbAdd) mb.tokens.push(mbF(d.mbAdd, { pad: MB_NUMBERS.has(d.mbAdd) && mb.target === "music-rename-file" ? 2 : 0 }));
    else if ("mbAddText" in d) mb.tokens.push(mbT(d.mbAddText || " - "));
    else if (d.mbAddRaw) mb.tokens.push(mbR(d.mbAddRaw));
    else if (d.mbPreset !== undefined) mb.tokens = JSON.parse(JSON.stringify(MB_PRESETS[mb.target][Number(d.mbPreset)][1]));
    else if (d.mbUp !== undefined || d.mbDown !== undefined) {
        const i = Number(d.mbUp !== undefined ? d.mbUp : d.mbDown);
        const j = d.mbUp !== undefined ? i - 1 : i + 1;
        if (j >= 0 && j < mb.tokens.length) [mb.tokens[i], mb.tokens[j]] = [mb.tokens[j], mb.tokens[i]];
    } else if (d.mbDel !== undefined) mb.tokens.splice(Number(d.mbDel), 1);
    else if ("mbClear" in d) mb.tokens = [];
    else if ("mbUse" in d) {
        const input = document.getElementById(mb.target);
        if (input) {
            input.value = mbBuild(mb.tokens);
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return mbClose();
    }
    mbRender();
});

document.addEventListener("input", (event) => {
    const el = event.target;
    if (!el.dataset) return;
    if (el.dataset.mbText !== undefined) mb.tokens[Number(el.dataset.mbText)].value = el.value;
    else if (el.dataset.mbBefore !== undefined) mb.tokens[Number(el.dataset.mbBefore)].before = el.value;
    else if (el.dataset.mbAfter !== undefined) mb.tokens[Number(el.dataset.mbAfter)].after = el.value;
    else return;
    mbExample();
});

document.addEventListener("change", (event) => {
    const el = event.target;
    if (!el.dataset || !el.dataset.mbFlag) return;
    const token = mb.tokens[Number(el.dataset.mbI)];
    token[el.dataset.mbFlag] = el.dataset.mbFlag === "pad" ? (el.checked ? 2 : 0) : el.checked;
    mbRender();
});
