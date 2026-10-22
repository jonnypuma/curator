// Tag manager: every tag with its use count (rename, merge, delete), and add, remove or fetch
// TMDB keywords for picked movies or shows.

state.tags = { media: "movies", list: [], picked: null, pickedTags: [], filter: "", renaming: null };

function tagsKind() {
    return state.tags.media === "tv" ? "show" : "movie";
}

function tagsPickedHtml() {
    const picked = state.tags.picked;
    if (!picked) return "";
    const chips = state.tags.pickedTags.length
        ? state.tags.pickedTags.map((item, index) => `<span class="tag-chip">${escapeHtml(item.tag)}${picked.ids.length > 1 ? ` <small>${item.count}/${picked.ids.length}</small>` : ""}
            <button type="button" class="tag-chip-x" data-action="tags-remove" data-index="${index}" aria-label="Remove ${escapeHtml(item.tag)}" title="Remove from the picked items">×</button></span>`).join("")
        : `<span class="muted">No tags yet.</span>`;
    return `<section class="tags-picked"><h3>${escapeHtml(picked.label)}</h3>
        <div class="tag-chips">${chips}</div>
        <form id="tags-add-form" class="tags-add">
            <label class="sr-only" for="tags-add">Tags to add</label>
            <input id="tags-add" list="tags-known" placeholder="Add tags, separated by commas" autocomplete="off">
            <datalist id="tags-known">${state.tags.list.map((item) => `<option value="${escapeHtml(item.tag)}"></option>`).join("")}</datalist>
            <button type="submit">Add</button>
            <button type="button" class="btn-ghost" data-action="tags-scrape" title="Add the TMDB keywords of each picked item as tags">Fetch keywords from TMDB</button>
        </form>
        <p class="muted">Locked items are skipped. Changed items keep their tags when they are scraped again, and their .nfo is rewritten when edits are written straight away.</p>
    </section>`;
}

function tagsTableHtml() {
    const match = textMatcher(state.tags.filter);
    const rows = state.tags.list.map((item, index) => ({ item, index })).filter(({ item }) => !match || match(item.tag.toLowerCase()));
    if (!state.tags.list.length) return `<p class="muted">No ${state.tags.media === "episodes" ? "episode" : state.tags.media === "tv" ? "show" : "movie"} has tags yet. Add some above, or turn on keywords as tags under Settings, Movies.</p>`;
    if (!rows.length) return `<p class="muted">No tag matches the filter.</p>`;
    return `<table class="tags-table"><thead><tr><th>Tag</th><th class="num">Used</th><th class="num">Locked</th><th></th></tr></thead><tbody>
        ${rows.map(({ item, index }) => state.tags.renaming === index
            ? `<tr><td colspan="3"><input id="tags-rename-input" value="${escapeHtml(item.tag)}" aria-label="New name for ${escapeHtml(item.tag)}"></td>
                <td class="tags-row-actions"><button type="button" data-action="tags-rename-save" data-index="${index}">Save</button><button type="button" class="btn-ghost" data-action="tags-rename-cancel">Cancel</button></td></tr>`
            : `<tr><td>${escapeHtml(item.tag)}</td><td class="num">${item.count}</td><td class="num">${item.locked || ""}</td>
                <td class="tags-row-actions"><button type="button" class="btn-ghost" data-action="tags-rename" data-index="${index}">Rename…</button><button type="button" class="btn-ghost btn-remove" data-action="tags-delete" data-index="${index}">Delete</button></td></tr>`
        ).join("")}</tbody></table>`;
}

function renderTagManager() {
    document.getElementById("tags-media").value = state.tags.media;
    document.getElementById("tags-media").disabled = !!state.tags.picked;
    document.getElementById("tags-picked").innerHTML = tagsPickedHtml();
    document.getElementById("tags-list").innerHTML = tagsTableHtml();
    const form = document.getElementById("tags-add-form");
    if (form) form.onsubmit = (event) => {
        event.preventDefault();
        runAction(addPickedTags, "Adding tags…");
    };
    const rename = document.getElementById("tags-rename-input");
    if (rename) {
        rename.focus();
        rename.select();
        rename.onkeydown = (event) => {
            if (event.key === "Enter") runAction(() => saveTagRename(state.tags.renaming), "Renaming…");
            if (event.key === "Escape") {
                event.stopPropagation();
                state.tags.renaming = null;
                renderTagManager();
            }
        };
    }
}

async function loadTags() {
    const media = state.tags.media;
    const requests = [api(`/api/v1/tags?media=${media}`)];
    if (state.tags.picked) requests.push(api(`/api/v1/tags?media=${media}&ids=${state.tags.picked.ids.join(",")}`));
    const [all, picked] = await Promise.all(requests);
    state.tags.list = all.tags || [];
    state.tags.pickedTags = picked ? picked.tags || [] : [];
    renderTagManager();
}

function openTagManager(target) {
    if (target) {
        const noun = target.kind === "episode" ? "episode" : target.kind === "show" ? "show" : "movie";
        state.tags.media = target.kind === "episode" ? "episodes" : target.kind === "show" ? "tv" : "movies";
        state.tags.picked = { kind: target.kind, ids: target.ids.slice(), label: `Tags of ${target.ids.length} picked ${noun}${target.ids.length === 1 ? "" : "s"}` };
        if (target.ids.length === 1) {
            const list = target.kind === "episode"
                ? (state.video.rows || []).filter((row) => row._kind === "episode")
                : target.kind === "show" ? state.video.shows : state.video.movies;
            const item = (list || []).find((row) => row.id === target.ids[0]);
            if (item) {
                const title = target.kind === "episode" && item.season_number != null
                    ? `${item.show_title || item.title} S${item.season_number}E${item.episode_number}`
                    : item.title;
                state.tags.picked.label = `Tags of ${title}${target.kind === "episode" ? "" : item.year ? ` (${item.year})` : ""}`;
            }
        }
    } else {
        state.tags.media = state.media === "tv" ? "tv" : "movies";
        state.tags.picked = null;
    }
    state.tags.filter = "";
    state.tags.renaming = null;
    document.getElementById("tags-filter").value = "";
    document.getElementById("tags-modal").classList.remove("hidden");
    renderTagManager();
    return loadTags();
}

function tagsChanged(data, verb) {
    const changed = Number(data.changed) || 0;
    const noun = state.tags.media === "episodes" ? "episode" : state.tags.media === "tv" ? "show" : "movie";
    const locked = Number(data.locked) || 0;
    notify(`${verb} on ${changed} ${noun}${changed === 1 ? "" : "s"}.${locked ? ` ${locked} locked ${locked === 1 ? "item was" : "items were"} skipped.` : ""}`, changed ? "info" : "warning");
    if (changed && state.tags.tagChange) patchVideoTags(state.tags.tagChange.ids, state.tags.tagChange);
    state.tags.tagChange = null;
    return loadTags();
}

async function addPickedTags() {
    const input = document.getElementById("tags-add");
    const add = input.value.split(",").map((tag) => tag.trim()).filter(Boolean);
    if (!add.length) {
        notify("Type at least one tag.", "warning");
        return;
    }
    const picked = state.tags.picked;
    const data = await api("/api/v1/tags/apply", { method: "POST", body: { kind: picked.kind, ids: picked.ids, add } });
    state.tags.tagChange = { ids: picked.ids, add };
    return tagsChanged(data, "Tags added");
}

async function removePickedTag(index) {
    const item = state.tags.pickedTags[Number(index)];
    const picked = state.tags.picked;
    if (!item || !picked) return;
    const data = await api("/api/v1/tags/apply", { method: "POST", body: { kind: picked.kind, ids: picked.ids, remove: [item.tag] } });
    state.tags.tagChange = { ids: picked.ids, remove: [item.tag] };
    return tagsChanged(data, `Removed "${item.tag}"`);
}

async function scrapePickedTags() {
    const picked = state.tags.picked;
    if (!picked) return;
    const data = await api("/api/v1/tags/scrape", { method: "POST", body: { kind: picked.kind, ids: picked.ids } });
    const empty = Number(data.without_keywords) || 0;
    if (empty) notify(`${empty} item${empty === 1 ? " has" : "s have"} no keywords on TMDB, or no TMDB match.`, "warning");
    return tagsChanged(data, "Keywords added");
}

async function saveTagRename(index) {
    const item = state.tags.list[Number(index)];
    const input = document.getElementById("tags-rename-input");
    if (!item || !input) return;
    const value = input.value.trim();
    state.tags.renaming = null;
    if (!value || value === item.tag) return renderTagManager();
    const data = await api("/api/v1/tags/rename", { method: "POST", body: { media: state.tags.media, old: item.tag, new: value } });
    state.tags.tagChange = { rename: [item.tag, value] };
    return tagsChanged(data, `Renamed "${item.tag}" to "${value}"`);
}

function deleteTagAsk(index) {
    const item = state.tags.list[Number(index)];
    if (!item) return;
    const noun = state.tags.media === "episodes" ? "episode" : state.tags.media === "tv" ? "show" : "movie";
    askDanger(
        `Delete the tag "${item.tag}"?`,
        `It is removed from ${item.count - (item.locked || 0)} ${noun}${item.count - (item.locked || 0) === 1 ? "" : "s"}.${item.locked ? ` ${item.locked} locked ${item.locked === 1 ? "one keeps" : "ones keep"} it.` : ""}`,
        "Delete tag",
        async () => {
            state.tags.tagChange = { drop: item.tag };
            return tagsChanged(await api("/api/v1/tags/delete", { method: "POST", body: { media: state.tags.media, tag: item.tag } }), `Deleted "${item.tag}"`);
        },
        false,
    );
}

function bindVideoTags() {
    const media = document.getElementById("tags-media");
    const filter = document.getElementById("tags-filter");
    if (!media || !filter) return;
    media.addEventListener("change", () => {
        state.tags.media = media.value;
        state.tags.renaming = null;
        runAction(loadTags);
    });
    filter.addEventListener("input", () => {
        state.tags.filter = filter.value;
        document.getElementById("tags-list").innerHTML = tagsTableHtml();
    });
}

function onTagsAction(name, action) {
    if (name === "tags-open") return runAction(() => openTagManager(null), "Loading tags…");
    if (name === "tags-remove") return runAction(() => removePickedTag(action.dataset.index), "Removing…");
    if (name === "tags-scrape") return runAction(scrapePickedTags, "Fetching keywords…");
    if (name === "tags-rename") {
        state.tags.renaming = Number(action.dataset.index);
        return renderTagManager();
    }
    if (name === "tags-rename-save") return runAction(() => saveTagRename(action.dataset.index), "Renaming…");
    if (name === "tags-rename-cancel") {
        state.tags.renaming = null;
        return renderTagManager();
    }
    if (name === "tags-delete") return deleteTagAsk(action.dataset.index);
    return false;
}
