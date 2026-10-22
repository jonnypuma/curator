function renderCell(column, track) {
    const editable = EDITABLE_COLUMNS.has(column.key);
    const text = column.html ? column.html(track) : escapeHtml(column.value(track));
    const classes = ["tabular"];
    if (editable && proposalDiffers(track, column.key)) classes.push("diff-cell");
    const edit = editable ? ` data-edit="${column.key}"` : "";
    return `<td class="${classes.join(" ")}"${edit}>${text}</td>`;
}

function cellValue(track, key) {
    if (key === "title") return track.title || "";
    if (key === "num") return String(track.track_number || "");
    if (key === "year") return track.year == null ? "" : String(track.year);
    if (key === "artist") return (track.tags || {}).artists || track.artist_name || "";
    if (key === "albumartist") return (track.tags || {}).albumartists || (track.tags || {}).albumartist || "";
    return "";
}

function proposedValue(proposal, key) {
    if (!proposal) return "";
    if (key === "title") return proposal.title || "";
    if (key === "num") return proposal.track_number == null ? "" : String(proposal.track_number);
    if (key === "year") return proposal.year == null ? "" : String(proposal.year);
    if (key === "artist") return proposal.artists || proposal.artist_name || "";
    if (key === "albumartist") return proposal.albumartists || proposal.albumartist || "";
    return "";
}

function proposalDiffers(track, key) {
    const proposal = proposalFor(track.id);
    if (!proposal) return false;
    const current = cellValue(track, key);
    const proposed = proposedValue(proposal, key);
    if (key === "num" || key === "year") {
        return String(parseInt(current, 10) || "") !== String(parseInt(proposed, 10) || "");
    }
    return String(current).trim() !== String(proposed).trim();
}

function onTrackDblClick(event) {
    const cell = event.target.closest("[data-edit]");
    if (!cell) return;
    event.preventDefault();
    beginCellEdit(cell);
}

function beginCellEdit(cell) {
    if (!cell || cell.querySelector("input")) return;
    const row = cell.closest("[data-track]");
    const track = state.album && state.album.tracks.find((item) => item.id === row.dataset.track);
    if (!track) return;
    const key = cell.dataset.edit;
    cell.innerHTML = `<input class="cell-edit" value="${escapeHtml(cellValue(track, key))}">`;
    const input = cell.querySelector("input");
    input.focus();
    input.select();
    input.addEventListener("keydown", (event) => onCellKey(event, input, track.id, key));
    input.addEventListener("blur", () => {
        if (input.dataset.skip === "1") return;
        input.dataset.skip = "1";
        commitCell(track.id, key, input.value, null).catch((error) => notify(error.message, "error"));
    });
}

function onCellKey(event, input, id, key) {
    if (event.key !== "Escape" && event.key !== "Enter" && event.key !== "Tab") return;
    event.preventDefault();
    event.stopPropagation();
    input.dataset.skip = "1";
    if (event.key === "Escape") {
        renderTracks();
        return;
    }
    const next = event.key === "Enter" ? nextRowCell(id, key) : nextEditCell(id, key, event.shiftKey);
    commitCell(id, key, input.value, next).catch((error) => notify(error.message, "error"));
}

function editCells() {
    return [...document.querySelectorAll("#tracks td[data-edit]")].map((cell) => ({
        id: cell.closest("[data-track]").dataset.track,
        key: cell.dataset.edit,
    }));
}

function nextRowCell(id, key) {
    const ids = state.album.tracks.map((track) => track.id);
    const index = ids.indexOf(id);
    const next = ids[index + 1];
    return next ? { id: next, key } : null;
}

function nextEditCell(id, key, backward) {
    const cells = editCells();
    const index = cells.findIndex((cell) => cell.id === id && cell.key === key);
    if (index < 0) return null;
    const step = backward ? -1 : 1;
    return cells[index + step] || null;
}

function trackCell(id, key) {
    return [...document.querySelectorAll("#tracks td[data-edit]")].find((cell) => {
        const row = cell.closest("[data-track]");
        return row && row.dataset.track === id && cell.dataset.edit === key;
    });
}

function cellBody(key, value) {
    if (key === "title") return { title: value };
    if (key === "num") return { track_number: value };
    if (key === "year") return { year: value };
    if (key === "artist") return { artist_name: value, artists: value };
    if (key === "albumartist") return { albumartist: value, albumartists: value };
    return {};
}

async function commitCell(id, key, value, next) {
    const track = state.album && state.album.tracks.find((item) => item.id === id);
    if (!track) return;
    if (String(cellValue(track, key)) === String(value)) {
        renderTracks();
        if (next) {
            const cell = trackCell(next.id, next.key);
            if (cell) beginCellEdit(cell);
        }
        return;
    }
    if (!libraryWritable(state.album.album.path)) {
        notify("This music folder is mounted read-only.", "error");
        renderTracks();
        return;
    }
    await api(`/api/tracks/${id}`, { method: "PUT", body: cellBody(key, value) });
    showUndo("Album saved");
    await selectAlbum(state.album.album.id, true);
    if (next) {
        const cell = trackCell(next.id, next.key);
        if (cell) beginCellEdit(cell);
    }
}

function commitOpenDiffEdit() {
    const input = document.querySelector("#editor-diff .diff-edit");
    if (!input || input.dataset.done === "1") return;
    input.dataset.done = "1";
    const cell = input.closest("[data-diff-key]");
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track || !proposal) return;
    const key = cell.dataset.diffKey;
    if (cell.dataset.diffSide === "proposed") {
        proposal[key] = input.value;
        const mirror = document.querySelector(`[data-proposed="${key}"]`);
        if (mirror) mirror.value = input.value;
    } else {
        if (!state.tagDrafts[track.id]) state.tagDrafts[track.id] = {};
        state.tagDrafts[track.id][key] = input.value;
        if (input.value === String(fieldValue(track, key) ?? "")) delete state.tagDrafts[track.id][key];
        if (!Object.keys(state.tagDrafts[track.id]).length) delete state.tagDrafts[track.id];
        if (state.album) noteAlbumChanges(state.album.album.id, state.album.tracks);
    }
}

function beginDiffEdit() {
    const cell = state.diffCell;
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track || !proposal) return;
    const td = document.querySelector(`#editor-diff [data-diff-key="${cell.key}"][data-diff-side="${cell.side}"]`);
    if (!td || td.querySelector("input")) return;
    const value = cell.side === "proposed" ? String(proposal[cell.key] ?? "") : embeddedDisplay(track, cell.key);
    td.textContent = "";
    const input = document.createElement("input");
    input.className = "diff-edit";
    input.value = value;
    td.appendChild(input);
    input.focus();
    input.select();
    const close = (keep) => {
        if (input.dataset.done === "1" && !keep) return;
        if (keep) commitOpenDiffEdit();
        else input.dataset.done = "1";
        renderEditor();
    };
    input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== "Escape") return;
        event.preventDefault();
        event.stopPropagation();
        close(event.key === "Enter");
    });
    input.addEventListener("blur", () => {
        window.setTimeout(() => {
            if (input.dataset.done === "1") return;
            commitOpenDiffEdit();
            renderEditor();
        }, 0);
    });
}

function useEmbeddedValue() {
    const cell = state.diffCell;
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track || !proposal) return;
    proposal[cell.key] = embeddedDisplay(track, cell.key);
    renderEditor();
}

async function removeDiffValue() {
    const cell = state.diffCell;
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track || !proposal) return;
    if (cell.side === "proposed") {
        proposal[cell.key] = "";
        renderEditor();
        return;
    }
    const body = DIFF_EXTRA.has(cell.key) ? { extra: { [cell.key]: "" } } : { [cell.key]: "" };
    const data = await api(`/api/tracks/${track.id}`, { method: "PUT", body });
    if (state.tagDrafts[track.id]) delete state.tagDrafts[track.id][cell.key];
    if (data.warnings && data.warnings.length) notify(data.warnings.join(" "), "warning");
    else notify("Tag removed.", "info");
    await selectAlbum(state.album.album.id, true);
}

function diffCellText() {
    const cell = state.diffCell;
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track) return "";
    if (cell.side === "proposed") return String((proposal && proposal[cell.key]) ?? "");
    return embeddedDisplay(track, cell.key);
}

async function copyDiffValue() {
    try {
        await navigator.clipboard.writeText(diffCellText());
        notify("Copied.", "info");
    } catch (error) {
        notify("Could not copy that text.", "warning");
    }
}

async function pasteDiffValue() {
    const cell = state.diffCell;
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!cell || !track || !proposal) return;
    let text = "";
    try {
        text = await navigator.clipboard.readText();
    } catch (error) {
        notify("Could not read the clipboard.", "warning");
        return;
    }
    if (cell.side === "proposed") proposal[cell.key] = text;
    else {
        if (!state.tagDrafts[track.id]) state.tagDrafts[track.id] = {};
        state.tagDrafts[track.id][cell.key] = text;
    }
    renderEditor();
}

function runDiffCommand(kind) {
    const menu = document.getElementById("diff-menu");
    if (menu) menu.classList.add("hidden");
    if (document.querySelector("#editor-diff .diff-edit")) {
        commitOpenDiffEdit();
        if (kind === "edit") renderEditor();
    }
    if (kind === "edit") return beginDiffEdit();
    if (kind === "use-embedded") return useEmbeddedValue();
    if (kind === "remove") return runAction(removeDiffValue, "Removing tag…");
    if (kind === "copy") return copyDiffValue();
    if (kind === "paste") return pasteDiffValue();
}

async function saveDiffField(key) {
    commitOpenDiffEdit();
    const track = currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!track || !proposal || !state.album) return;
    const value = String(proposal[key] ?? "");
    const body = DIFF_EXTRA.has(key) ? { extra: { [key]: value } } : { [key]: value };
    const data = await api(`/api/tracks/${track.id}`, { method: "PUT", body });
    if (state.tagDrafts[track.id]) delete state.tagDrafts[track.id][key];
    if (data.warnings && data.warnings.length) notify(data.warnings.join(" "), "warning");
    else notify("Tag saved.", "info");
    await selectAlbum(state.album.album.id, true);
    clearMatchIfTagsMatch();
}
