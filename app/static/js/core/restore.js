// Database restore from a dump in the backup folder, behind a type-RESTORE confirmation.

function restoreSectionHtml() {
    return `<section class="settings-section" data-tab="backup"><h3>Restore and music import</h3>
            <p class="muted">A <span class="mono">.dump</span> in the backup folder, or placed in the Curator folder next to docker-compose, shows up here. <strong>Import music</strong> copies artists, albums and tracks from an old Resonance dump and leaves movies and TV alone. <strong>Restore</strong> replaces the whole database. Either way the current database is saved first and put back if the operation fails. Library files on disk are not touched.</p>
            <div id="restore-files" class="restore-files"><p class="muted">Loading dumps…</p></div>
            <p><button type="button" class="btn-ghost" data-action="restore-refresh">Refresh list</button></p>
        </section>`;
}

function formatDumpSize(bytes) {
    const value = Number(bytes) || 0;
    if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GB`;
    if (value >= 1048576) return `${(value / 1048576).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(value / 1024))} KB`;
}

async function loadBackupFiles() {
    const box = document.getElementById("restore-files");
    if (!box) return;
    let data;
    try {
        data = await api("/api/backup/files");
    } catch (error) {
        box.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
        return;
    }
    const files = data.files || [];
    state.backupFiles = files;
    box.innerHTML = files.length ? `<table class="restore-table"><thead><tr><th>Dump</th><th>Written</th><th>Size</th><th></th></tr></thead><tbody>
        ${files.map((file, index) => `<tr>
            <td class="mono">${escapeHtml(file.name)}${file.safety ? ` <span class="muted">(saved before a restore)</span>` : ""}<br><span class="muted">${escapeHtml(file.folder)}</span></td>
            <td>${escapeHtml(String(file.modified || "").replace("T", " "))}</td>
            <td>${formatDumpSize(file.size)}</td>
            <td><button type="button" class="btn-ghost" data-action="import-open" data-index="${index}">Import music…</button>
                <button type="button" class="btn-ghost is-danger" data-action="restore-open" data-index="${index}">Restore…</button></td>
        </tr>`).join("")}</tbody></table>`
        : `<p class="muted">No .dump files yet. Use Backup now, or put a Resonance dump in the Curator folder (next to docker-compose) or in the backup folder.</p>`;
}

function openRestore(index) {
    const file = (state.backupFiles || [])[Number(index)];
    if (!file) return;
    state.restoreFile = file;
    document.getElementById("restore-file-name").textContent = `${file.name} (${String(file.modified || "").replace("T", " ")}, ${formatDumpSize(file.size)})`;
    const input = document.getElementById("restore-confirm");
    input.value = "";
    input.oninput = syncRestoreButton;
    syncRestoreButton();
    document.getElementById("restore-modal").classList.remove("hidden");
    input.focus();
}

function syncRestoreButton() {
    const ready = document.getElementById("restore-confirm").value === "RESTORE";
    document.getElementById("restore-go").classList.toggle("hidden", !ready);
}

function openMusicImport(index) {
    const file = (state.backupFiles || [])[Number(index)];
    if (!file) return;
    state.restoreFile = file;
    document.getElementById("import-file-name").textContent = `${file.name} (${String(file.modified || "").replace("T", " ")}, ${formatDumpSize(file.size)})`;
    const input = document.getElementById("import-confirm");
    input.value = "";
    input.oninput = syncImportButton;
    syncImportButton();
    document.getElementById("import-modal").classList.remove("hidden");
    input.focus();
}

function syncImportButton() {
    const ready = document.getElementById("import-confirm").value === "IMPORT";
    document.getElementById("import-go").classList.toggle("hidden", !ready);
}

async function startMusicImport() {
    const file = state.restoreFile;
    const confirm = document.getElementById("import-confirm").value;
    if (!file || confirm !== "IMPORT") return;
    state.backup = await api("/api/backup/import-music", { method: "POST", body: { file: file.name, folder: file.folder, confirm } });
    document.getElementById("import-modal").classList.add("hidden");
    notify("Importing music. Curator reloads when it is done.", "info");
    watchRestore();
}

async function startRestore() {
    const file = state.restoreFile;
    const confirm = document.getElementById("restore-confirm").value;
    if (!file || confirm !== "RESTORE") return;
    state.backup = await api("/api/backup/restore", { method: "POST", body: { file: file.name, folder: file.folder, confirm } });
    document.getElementById("restore-modal").classList.add("hidden");
    notify("Restoring the database. Curator reloads when it is done.", "info");
    watchRestore();
}

async function watchRestore() {
    clearTimeout(state.restoreTimer);
    let data;
    try {
        data = await api("/api/backup/files");
    } catch (error) {
        state.restoreTimer = setTimeout(watchRestore, 2000);
        return;
    }
    const status = data.status || {};
    const busy = status.status === "running" || status.status === "waiting";
    if (busy && (status.kind === "restore" || status.kind === "import" || status.kind === "backup")) {
        state.backup = status;
        state.backupSeen = status.status;
        syncActivity();
        state.restoreTimer = setTimeout(watchRestore, 2000);
        return;
    }
    if (typeof pollSystem === "function") pollSystem();
}
