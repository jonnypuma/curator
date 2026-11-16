// The orphan report: files Radarr, Sonarr or Lidarr do not use or know, records whose file is gone, and stray files.

const ORPHAN_TYPES = {
    unused: ["Unused in the app", "The app keeps a file record that no episode is attached to."],
    unknown: ["Unknown to the app", "A library file in the app's folder that the app has no record of."],
    missing: ["Missing on disk", "The app has a record, but the file is gone. A rescan in the app clears it."],
    stray: ["Stray file", "A file in a library folder that neither Curator nor the app lists."],
};

state.orphans = { data: null, timer: 0 };

async function openOrphans() {
    document.getElementById("orphans-modal").classList.remove("hidden");
    await loadOrphans();
    loadKodiReport().catch(() => {});
}

async function loadOrphans() {
    const data = await api("/api/v1/arr-orphans");
    state.orphans.data = data;
    renderOrphans();
    clearTimeout(state.orphans.timer);
    if (data.status === "running" && !document.getElementById("orphans-modal").classList.contains("hidden")) {
        state.orphans.timer = setTimeout(() => loadOrphans().catch(() => {}), 2000);
    }
}

async function scanOrphans() {
    await api("/api/v1/arr-orphans/scan", { method: "POST", body: {} });
    await loadOrphans();
}

function orphanRow(item, index) {
    const [typeLabel, typeHelp] = ORPHAN_TYPES[item.type] || [item.type, ""];
    let action = "";
    if (item.type === "missing") {
        action = item.arr_id ? `<button type="button" class="btn-ghost" data-action="orphans-rescan" data-index="${index}">Rescan in ${escapeHtml(item.app)}</button>` : "";
    } else if (item.sole) {
        // The only copy of the title: the app not using it does not mean nobody needs it, so there is no Delete.
        action = item.arr_id
            ? `<button type="button" class="btn-ghost" data-action="orphans-rescan" data-index="${index}" title="Lets ${escapeHtml(item.app)} pick the file up">Rescan in ${escapeHtml(item.app)}</button>`
            : `<small class="muted">Only copy · not deleted from here</small>`;
    } else {
        action = `<button type="button" class="btn-ghost btn-remove" data-action="orphans-delete" data-index="${index}">Delete…</button>`;
    }
    const size = item.size_bytes ? fmtSize(item.size_bytes) : "";
    return `<tr>
        <td class="queue-fit"><span class="tag-pill" title="${escapeHtml(typeHelp)}">${escapeHtml(typeLabel)}</span></td>
        <td><strong>${escapeHtml(item.label || "")}</strong>${item.note ? ` <small class="muted">${escapeHtml(item.note)}</small>` : ""}<br><small class="mono muted">${escapeHtml(item.path || "")}</small></td>
        <td class="queue-fit">${escapeHtml(size)}</td>
        <td class="queue-fit">${action}</td>
    </tr>`;
}

function renderOrphans() {
    const data = state.orphans.data || {};
    const host = document.getElementById("orphans-list");
    const status = document.getElementById("orphans-status");
    const button = document.getElementById("orphans-scan");
    const running = data.status === "running";
    if (button) {
        button.disabled = running;
        button.textContent = data.result ? "Check again" : "Check now";
    }
    if (status) {
        status.className = `scan-status ${running ? "is-running" : data.status === "failed" ? "is-failed" : ""}`;
        const progress = running && data.total ? ` (${data.processed}/${data.total})` : "";
        const when = data.result && data.result.generated_at ? ` Checked ${fmtDate(data.result.generated_at)}.` : "";
        keepText(status, running ? `${data.message || "Checking"}${progress}` : `${data.message || "Not checked yet."}${when}`);
    }
    const report = data.result;
    if (!report) {
        host.innerHTML = `<p class="muted">Check now reads every movie in Radarr, series in Sonarr and artist in Lidarr, compares their file lists with the library, and walks the library folders for stray files.</p>`;
        return;
    }
    const warnings = (report.warnings || []).map((line) => `<p class="danger-warn">${escapeHtml(line)}</p>`).join("");
    const items = report.items || [];
    if (!items.length) {
        host.innerHTML = `${warnings}<p class="muted">Nothing to report.</p>`;
        return;
    }
    const sections = ["Radarr", "Sonarr", "Lidarr", "Library"].map((app) => {
        const rows = items.map((item, index) => [item, index]).filter(([item]) => item.app === app);
        if (!rows.length) return "";
        return `<h3>${escapeHtml(app)} (${rows.length})</h3>
            <table class="queue-table"><tbody>${rows.map(([item, index]) => orphanRow(item, index)).join("")}</tbody></table>`;
    }).join("");
    host.innerHTML = warnings + sections;
}

function orphanItem(action) {
    return ((state.orphans.data && state.orphans.data.result && state.orphans.data.result.items) || [])[Number(action.dataset.index)];
}

function deleteOrphanAsk(item) {
    if (!item) return;
    askDanger(
        `Delete ${item.label || "this file"}?`,
        item.path,
        "Delete from disk",
        async () => {
            await api("/api/v1/arr-orphans/discard", { method: "POST", body: { path: item.path } });
            notify(`Deleted ${item.label || item.path}.`, "success");
            await loadOrphans();
        },
        true,
        null,
        true,
    );
}

async function rescanOrphan(item) {
    if (!item) return;
    await api("/api/v1/arr-orphans/rescan", { method: "POST", body: { app: item.app, arr_id: item.arr_id } });
    notify(`${item.app} is rescanning ${item.label || "the item"}.`, "info");
}

async function testOrphanApps() {
    const host = document.getElementById("orphans-test");
    host.innerHTML = `<p class="muted">Asking each app…</p>`;
    const data = await api("/api/v1/arr-orphans/test");
    host.innerHTML = connectionLines(data.results, "app");
}

// The Kodi report (curator/kodi_report.py): what Kodi lists and what the library holds, by file.
const KODI_REPORT_LISTS = [
    ["missing", "In Kodi, file gone", "Kodi has an entry whose file is not on disk. A Kodi library clean removes these entries."],
    ["not_in_kodi", "In the library, not in Kodi", "Kodi has no entry for these files. Scan in Kodi asks Kodi to scan the folder."],
    ["not_indexed", "In Kodi, not in the library", "The file is on disk and in Kodi, but Curator has no movie or episode for it. A Curator scan of its folder adds it."],
    ["unmapped_kodi", "Kodi paths no row translates", "Add a Kodi path row that covers these paths, or they cannot be checked."],
    ["unmapped_folders", "Library folders no row reaches", "Kodi cannot be asked to scan these folders on their own until a Kodi path row covers them."],
];

state.kodiReport = { data: null, timer: 0 };

async function loadKodiReport() {
    const data = await api("/api/v1/kodi-report");
    state.kodiReport.data = data;
    renderKodiReport();
    clearTimeout(state.kodiReport.timer);
    if (data.status === "running" && !document.getElementById("orphans-modal").classList.contains("hidden")) {
        state.kodiReport.timer = setTimeout(() => loadKodiReport().catch(() => {}), 1500);
    }
}

async function startKodiReport() {
    await api("/api/v1/kodi-report/scan", { method: "POST", body: {} });
    await loadKodiReport();
}

function kodiReportRow(key, item) {
    let action = "";
    if (key === "not_in_kodi" && item.folder) {
        action = `<button type="button" class="btn-ghost" data-action="orphans-kodi-scan" data-folder="${escapeHtml(item.folder)}">Scan in Kodi</button>`;
    }
    const where = item.path || item.folder || item.kodi_path || "";
    const extra = item.files ? ` <small class="muted">${item.files} file${item.files === 1 ? "" : "s"}</small>` : "";
    const kodi = item.kodi_path && item.path ? `<br><small class="mono muted">Kodi: ${escapeHtml(item.kodi_path)}</small>` : "";
    return `<tr><td><strong>${escapeHtml(item.label || item.folder || "")}</strong>${extra}<br><small class="mono muted">${escapeHtml(where)}</small>${kodi}</td><td class="queue-fit">${action}</td></tr>`;
}

function renderKodiReport() {
    const data = state.kodiReport.data || {};
    const status = document.getElementById("kodi-report-status");
    const host = document.getElementById("kodi-report-list");
    const button = document.getElementById("kodi-report-check");
    const running = data.status === "running";
    if (button) button.disabled = running;
    if (status) {
        status.className = `scan-status ${running ? "is-running" : data.status === "failed" ? "is-failed" : ""}`;
        status.textContent = running ? (data.message || "Reading Kodi…") : data.status === "failed" ? data.message || "The comparison failed" : "";
    }
    if (!host) return;
    const result = data.result;
    if (!result || running) {
        host.innerHTML = "";
        return;
    }
    const counts = result.counts || {};
    const lists = result.lists || {};
    const summary = `<p class="muted">Kodi lists ${result.kodi_movies} movies and ${result.kodi_episodes} episodes; the library has ${result.library_files} video files.</p>`;
    const sections = KODI_REPORT_LISTS.map(([key, title, help]) => {
        const rows = lists[key] || [];
        const total = Number(counts[key]) || 0;
        if (!total) return "";
        const more = total > rows.length ? `<p class="muted">Showing ${rows.length} of ${total}.</p>` : "";
        let tools = "";
        if (key === "missing") tools = `<button type="button" class="btn-ghost" data-action="orphans-kodi-clean">Clean the Kodi video library</button>`;
        const folderCount = new Set(rows.map((row) => row.folder)).size;
        if (key === "not_in_kodi") tools = `<button type="button" class="btn-ghost" data-action="orphans-kodi-scan-all">${folderCount === 1 ? "Scan this folder in Kodi" : `Scan all ${folderCount} folders in Kodi`}</button>`;
        return `<h4>${escapeHtml(title)} (${total})</h4><p class="muted">${escapeHtml(help)}</p>${tools ? `<p>${tools}</p>` : ""}
            <table class="queue-table"><tbody>${rows.map((row) => kodiReportRow(key, row)).join("")}</tbody></table>${more}`;
    }).join("");
    host.innerHTML = summary + (sections || `<p class="muted">Kodi and the library agree: every file is in both.</p>`);
}

async function scanKodiFolders(folders) {
    const data = await api("/api/v1/kodi-report/scan-folders", { method: "POST", body: { folders } });
    notify(data.queued ? `Kodi was asked to scan ${folders.length} folder${folders.length === 1 ? "" : "s"}. It shows in Library updates.` : "Kodi is not set to receive video library updates.", data.queued ? "info" : "warning");
}

async function cleanKodiFromReport() {
    await api("/api/v1/kodi-report/clean", { method: "POST", body: {} });
    notify("Kodi was asked to clean its video library. It starts when Kodi has finished any scan.", "info");
}

function onOrphansAction(name, action) {
    if (name === "orphans-open") return runAction(openOrphans);
    if (name === "orphans-test") return runAction(testOrphanApps, "Asking the apps…");
    if (name === "orphans-scan") return runAction(scanOrphans);
    if (name === "orphans-delete") return deleteOrphanAsk(orphanItem(action));
    if (name === "orphans-rescan") return runAction(() => rescanOrphan(orphanItem(action)));
    if (name === "orphans-kodi-check") return runAction(startKodiReport);
    if (name === "orphans-kodi-clean") return runAction(cleanKodiFromReport);
    if (name === "orphans-kodi-scan") return runAction(() => scanKodiFolders([action.dataset.folder]));
    if (name === "orphans-kodi-scan-all") {
        const rows = (((state.kodiReport.data || {}).result || {}).lists || {}).not_in_kodi || [];
        return runAction(() => scanKodiFolders([...new Set(rows.map((row) => row.folder).filter(Boolean))]));
    }
    return false;
}
