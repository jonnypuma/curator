const langState = {
    offset: 0,
    total: 0,
    limit: 1000,
    files: [],
    picks: {},
    timer: 0,
    searched: false,
};

function openLanguageDefaults() {
    document.getElementById("language-modal").classList.remove("hidden");
    paintLanguageNote();
    return loadLanguageOptions();
}

async function loadLanguageOptions() {
    const data = await api("/api/v1/language-defaults");
    const lang = document.getElementById("lang-lang");
    const scope = document.getElementById("lang-scope");
    if (lang && !lang.options.length) {
        lang.innerHTML = (data.languages || []).map((item) =>
            `<option value="${escapeHtml(item.code)}" ${item.code === "eng" ? "selected" : ""}>${escapeHtml(item.label)}</option>`
        ).join("");
    }
    if (scope) {
        const current = scope.value;
        scope.innerHTML = `<option value="">Entire library</option>${(data.scopes || []).map((item) =>
            `<option value="${escapeHtml(item.path)}">${escapeHtml(item.label)}</option>`
        ).join("")}`;
        scope.value = current;
    }
    const filename = document.getElementById("lang-filename");
    if (filename && !filename.dataset.bound) {
        filename.dataset.bound = "1";
        filename.addEventListener("input", paintLanguageList);
    }
    const mode = document.getElementById("lang-mode");
    if (mode && !mode.dataset.bound) {
        mode.dataset.bound = "1";
        mode.addEventListener("change", paintLanguageNote);
    }
    if (data.save && data.save.status === "running") watchLanguageSave();
}

function onLanguageAction(name, action) {
    if (name === "lang-search") return runAction(() => searchLanguageDefaults(0), "Searching languages…");
    if (name === "lang-page") return runAction(() => searchLanguageDefaults(langState.offset + (Number(action.dataset.dir) * langState.limit)), "Searching languages…");
    if (name === "lang-save") return runAction(() => saveLanguageDefaults(), "Saving…");
    if (name === "lang-save-one") return runAction(() => saveLanguageDefaults([action.dataset.file]), "Saving…");
    if (name === "lang-pick") return toggleLanguagePick(action);
}

async function searchLanguageDefaults(offset) {
    langState.offset = Math.max(0, offset || 0);
    langState.picks = {};
    const host = document.getElementById("lang-list");
    const status = document.getElementById("lang-status");
    if (host) host.innerHTML = `<p class="muted">Searching…</p>`;
    if (status) status.textContent = "";
    const data = await api("/api/v1/language-defaults/search", {
        method: "POST",
        body: {
            mode: document.getElementById("lang-mode").value,
            lang: document.getElementById("lang-lang").value,
            filename: document.getElementById("lang-filename").value.trim(),
            scope: document.getElementById("lang-scope").value,
            offset: langState.offset,
        },
    });
    langState.files = data.files || [];
    langState.total = data.total || 0;
    langState.limit = data.limit || 1000;
    langState.offset = data.offset || 0;
    langState.searched = true;
    paintLanguageNote();
    paintLanguageList();
}

function visibleLanguageFiles() {
    const needle = document.getElementById("lang-filename").value.trim().toLowerCase();
    return (langState.files || []).filter((file) => !needle || `${file.name} ${file.path}`.toLowerCase().includes(needle));
}

function paintLanguageNote() {
    const note = document.getElementById("lang-note");
    if (!note) return;
    const mode = document.getElementById("lang-mode");
    const which = mode ? mode.value : "not_default";
    const lead = which === "is_default"
        ? "Search finds files where this language is already the default audio or subtitle track."
        : which === "contains"
            ? "Search finds any file that contains this language."
            : "Search finds files that contain this language and whose default audio track is a different language. A subtitle counts as the default only when that one track is flagged. Extra tracks of the same language stay in the list and are not defaults.";
    note.textContent = `${lead} A filename narrows the search, and typing after Search narrows this page. More than 1000 matches use Previous 1000 and Next 1000. Click a track again to undo that choice. Save all updates the MKV files on this page and prefers a full subtitle, then SDH, then Forced. Other containers stay unchanged. Unscanned files stay out of the list until a scan probes them.`;
}

function paintLanguageList() {
    const host = document.getElementById("lang-list");
    const pager = document.getElementById("lang-pager");
    const status = document.getElementById("lang-status");
    if (!host) return;
    const rows = visibleLanguageFiles();
    const lang = document.getElementById("lang-lang").value;
    if (!langState.searched) {
        host.innerHTML = `<p class="muted">Search to list videos.</p>`;
    } else if (!langState.files.length) {
        host.innerHTML = `<p class="muted">No videos match.</p>`;
    } else if (!rows.length) {
        host.innerHTML = `<p class="muted">No file on this page matches that filename.</p>`;
    } else {
        host.innerHTML = rows.map((file) => languageFileHtml(file, lang)).join("");
    }
    if (status && !langState.timer) {
        const from = langState.total ? langState.offset + 1 : 0;
        const to = Math.min(langState.offset + (langState.files || []).length, langState.total);
        status.textContent = langState.searched && langState.total ? `${langState.total} files. Showing ${from}–${to}. ${rows.length} on screen.` : "";
    }
    if (pager) {
        const previous = langState.offset > 0;
        const next = langState.offset + langState.limit < langState.total;
        pager.innerHTML = previous || next
            ? `${previous ? `<button type="button" data-action="lang-page" data-dir="-1">Previous 1000</button>` : ""}
               ${next ? `<button type="button" data-action="lang-page" data-dir="1">Next 1000</button>` : ""}`
            : "";
    }
}

function languageFileHtml(file, lang) {
    const pick = langState.picks[file.id] || {};
    const audio = languageBadges(file, "audio", file.audio || [], pick.audio, lang);
    const subs = languageBadges(file, "subtitle", file.subtitles || [], pick.subtitle, lang);
    return `<article class="lang-file">
        <div class="lang-file-head"><div>
            <h3>${escapeHtml(file.name || file.title || "Video")}</h3>
            <p class="muted mono">${escapeHtml(file.path || "")}</p>
        </div>${file.mkv ? `<button type="button" data-action="lang-save-one" data-file="${escapeHtml(file.id)}">Save</button>` : ""}</div>
        <p class="lang-line"><span>Audio</span>${audio || `<span class="muted">None</span>`}</p>
        <p class="lang-line"><span>Subs</span>${subs || `<span class="muted">None</span>`}</p>
        ${file.mkv ? "" : `<p class="muted">Not an MKV, so Save leaves it unchanged.</p>`}
    </article>`;
}

function languageBadges(file, kind, tracks, pending, lang) {
    return (tracks || []).map((track) => {
        const on = pending === track.index;
        const label = `${kind === "audio" ? audioTrackLabel(track) : subtitleBadge(track)}${track.default ? " · Default" : ""}`;
        const mine = String(track.lang || "").toLowerCase() === String(lang || "").toLowerCase();
        const classes = ["lang-badge", track.default ? "is-default" : "", on ? "is-pending" : "", mine && !track.default ? "is-lang" : ""].filter(Boolean).join(" ");
        if (!file.mkv) return `<span class="${classes}">${escapeHtml(label)}</span>`;
        return `<button type="button" class="${classes}" data-action="lang-pick" data-file="${escapeHtml(file.id)}" data-track="${kind}" data-index="${track.index}">${escapeHtml(label)}</button>`;
    }).join("");
}

function audioTrackLabel(track) {
    return [track.codec, track.lang, track.channels].filter(Boolean).join(" ");
}

function subtitleBadge(track) {
    const flags = (track.flags || []).filter((flag) => flag === "sdh" || flag === "hi" || flag === "forced");
    return [track.lang || "und", ...flags].filter(Boolean).join(" ");
}

function toggleLanguagePick(action) {
    const id = action.dataset.file;
    const kind = action.dataset.track;
    const index = Number(action.dataset.index);
    const pick = langState.picks[id] || {};
    if (pick[kind] === index) delete pick[kind];
    else pick[kind] = index;
    if (pick.audio == null && pick.subtitle == null) delete langState.picks[id];
    else langState.picks[id] = pick;
    paintLanguageList();
}

async function saveLanguageDefaults(only) {
    const rows = visibleLanguageFiles().filter((file) => file.mkv && (!only || only.includes(String(file.id))));
    if (!rows.length) throw new Error("No MKV files on this page to save");
    const picks = {};
    rows.forEach((file) => {
        if (langState.picks[file.id]) picks[file.id] = langState.picks[file.id];
    });
    const lang = document.getElementById("lang-lang").value;
    await api("/api/v1/language-defaults/save", {
        method: "POST",
        body: { lang, ids: rows.map((file) => file.id), picks },
    });
    langState.saved = { lang, ids: rows.map((file) => file.id), picks };
    // The button stays busy until the whole save has run.
    await new Promise((resolve) => {
        langState.finish = resolve;
        watchLanguageSave();
    });
}

function applySavedLanguageDefaults(saved) {
    if (!saved) return;
    const wanted = String(saved.lang || "").toLowerCase();
    const plain = (track) => !(track.flags || []).length;
    const rank = (track) => (plain(track) ? 0 : (track.flags || []).includes("forced") && !(track.flags || []).some((flag) => flag === "sdh" || flag === "hi") ? 2 : 1);
    const mark = (tracks, index) => (tracks || []).forEach((track) => { track.default = track.index === index; });
    (langState.files || []).forEach((file) => {
        if (!saved.ids.includes(file.id) || !file.mkv) return;
        const pick = saved.picks[file.id] || {};
        const mine = (tracks) => (tracks || []).filter((track) => String(track.lang || "").toLowerCase() === wanted);
        const picked = pick.audio != null || pick.subtitle != null;
        const audio = pick.audio != null ? pick.audio : (picked ? null : (mine(file.audio)[0] || {}).index);
        const subtitle = pick.subtitle != null ? pick.subtitle
            : (picked ? null : ([...mine(file.subtitles)].sort((a, b) => rank(a) - rank(b))[0] || {}).index);
        if (audio != null) mark(file.audio, audio);
        if (subtitle != null) mark(file.subtitles, subtitle);
        delete langState.picks[file.id];
    });
}

function finishLanguageWait() {
    const finish = langState.finish;
    langState.finish = null;
    if (finish) finish();
}

function watchLanguageSave() {
    if (langState.timer) return;
    langState.timer = window.setInterval(pollLanguageSave, 1000);
    pollLanguageSave();
}

async function pollLanguageSave() {
    const modal = document.getElementById("language-modal");
    if (!modal || modal.classList.contains("hidden")) {
        window.clearInterval(langState.timer);
        langState.timer = 0;
        finishLanguageWait();
        return;
    }
    const data = await api("/api/v1/language-defaults/save");
    const status = document.getElementById("lang-status");
    if (status) {
        const problems = (data.failed || []).length ? ` ${data.failed[0]}` : "";
        const total = Number(data.total) || 0;
        const percent = total ? Math.min(100, Math.round(((data.processed || 0) / total) * 100)) : 0;
        status.innerHTML = `<span class="lang-progress-text">${escapeHtml(`${data.message || ""}${problems}`)}</span>`
            + (data.status === "running" && total ? `<span class="lang-progress"><span style="width:${percent}%"></span></span>` : "");
        status.classList.toggle("is-working", data.status === "running");
    }
    if (data.status !== "running") {
        window.clearInterval(langState.timer);
        langState.timer = 0;
        finishLanguageWait();
        if (data.status === "done") {
            notify(data.message || "Default tracks saved.", (data.failed || []).length ? "warning" : "success");
            // No new search: the rows stay where they are and show the saved defaults.
            applySavedLanguageDefaults(langState.saved);
            langState.saved = null;
            const body = document.querySelector("#language-modal .modal-body");
            const top = body ? body.scrollTop : 0;
            paintLanguageList();
            if (body) body.scrollTop = top;
        }
    }
}
