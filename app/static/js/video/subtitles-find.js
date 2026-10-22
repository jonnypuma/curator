// Find subtitles: search OpenSubtitles.com for one movie or episode and save a result beside the video.

async function openSubtitleFinder(kind, id) {
    const modal = document.getElementById("subs-find-modal");
    const body = document.getElementById("subs-find-body");
    if (!modal || !body) return;
    state.subsFind = { kind, id, data: null };
    document.getElementById("subs-find-title").textContent = "Find subtitles";
    body.innerHTML = `<p class="muted">Searching OpenSubtitles.com…</p>`;
    modal.classList.remove("hidden");
    await searchSubtitles();
}

async function searchSubtitles(languages) {
    const body = document.getElementById("subs-find-body");
    const current = state.subsFind;
    if (!body || !current) return;
    try {
        const data = await api("/api/v1/subs/find", { method: "POST", body: { kind: current.kind, id: current.id, languages: languages || "", hearing: "include" } });
        current.data = data;
        document.getElementById("subs-find-title").textContent = `Find subtitles · ${data.title || ""}`;
        paintSubtitleResults();
    } catch (error) {
        body.innerHTML = `<p class="muted">${escapeHtml((error && error.message) || "The search failed")}</p>`;
    }
}

function paintSubtitleResults() {
    const body = document.getElementById("subs-find-body");
    const data = state.subsFind && state.subsFind.data;
    if (!body || !data) return;
    const have = (data.have || []).map((code) => String(code).toUpperCase()).join(", ");
    const intro = `<p class="muted">Searching ${escapeHtml((data.languages || []).join(", "))}. ${have ? `This file already has ${escapeHtml(have)}.` : "This file has no full subtitles yet."}
        ${data.can_download ? "" : " Set the OpenSubtitles username and password in Settings to download."}</p>
        <p class="job-actions"><label class="field">Languages <input id="subs-find-languages" type="text" value="${escapeHtml((data.languages || []).join(", "))}" spellcheck="false"></label>
        <button type="button" class="btn-ghost" data-action="video-subs-search">Search</button></p>`;
    if (!(data.results || []).length) {
        body.innerHTML = `${intro}<p class="muted">OpenSubtitles.com has nothing for these languages.</p>`;
        return;
    }
    const rows = data.results.map((item, index) => {
        const badges = [
            item.hash_match ? `<span class="tag-pill" title="Made for this exact file">File match</span>` : "",
            item.trusted ? `<span class="tag-pill" title="Trusted uploader">Trusted</span>` : "",
            item.hearing_impaired ? `<span class="tag-pill">SDH</span>` : "",
            item.machine ? `<span class="tag-pill" title="Machine translated">Machine</span>` : "",
            item.foreign_only ? `<span class="tag-pill" title="Only the foreign-language parts">Forced</span>` : "",
        ].join(" ");
        const button = item.saved
            ? `<span class="muted">Saved</span>`
            : `<button type="button" class="btn-ghost" data-action="video-subs-get" data-index="${index}" ${data.can_download ? "" : "disabled"}>Download</button>`;
        return `<tr><td>${escapeHtml(String(item.language || "").toUpperCase())}</td><td title="${escapeHtml(item.file_name)}">${escapeHtml(item.release || item.file_name)}<br>${badges}</td>
            <td>${item.downloads.toLocaleString()}</td><td>${escapeHtml(item.uploaded)}</td><td>${button}</td></tr>`;
    }).join("");
    body.innerHTML = `${intro}<table class="table"><thead><tr><th>Lang</th><th>Release</th><th>Downloads</th><th>Uploaded</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function downloadSubtitle(index) {
    const current = state.subsFind;
    const item = current && current.data && current.data.results[index];
    if (!item) return;
    try {
        const saved = await api("/api/v1/subs/get", { method: "POST", body: {
            kind: current.kind, id: current.id, file_id: item.file_id, language: item.language, hearing_impaired: item.hearing_impaired, hash_match: item.hash_match,
        } });
        item.saved = true;
        notify(saved.message || "Subtitle saved", "success");
        paintSubtitleResults();
    } catch (error) {
        notify((error && error.message) || "The subtitle could not be saved", "fail");
    }
}

async function testOpenSubtitles(button) {
    const read = (id) => ((document.getElementById(id) || {}).value || "").trim();
    button.dataset.testLabel = "Test";
    beginConnectionTest(button);
    try {
        const data = await api("/api/v1/subs/opensubtitles/test", { method: "POST", body: {
            key: read("opensubtitles-key"), username: read("video-subs-username"), password: read("opensubtitles-password"),
        } });
        paintConnectionTest(button, true);
        notify(data.message || "Connected to OpenSubtitles.com", "success");
    } catch (error) {
        paintConnectionTest(button, false);
        notify((error && error.message) || "OpenSubtitles.com could not be reached", "fail");
    }
}
