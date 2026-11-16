// One layout for every compare window: albums, movies, episodes, music videos, and show and artist folders.
// A group says why its rows are copies, shows the copies side by side (picture, name, facts, the Radarr/Sonarr/Lidarr
// line, path, then Delete from disk as the bin at the top and Remove from library at the bottom), an optional
// media-specific middle (the tracks of albums), and Not duplicates for the group.

function compareGroupHtml({ heading = "", reason = "", warning = "", cards = "", body = "", actions = "" } = {}) {
    return `<section class="duplicate-pair compare-group">
        ${heading ? `<h3>${escapeHtml(heading)}</h3>` : ""}
        ${reason ? `<p class="muted dup-reason">${escapeHtml(reason)}</p>` : ""}
        ${warning || ""}
        <div class="upgrade-scroll"><table class="upgrade-table"><thead><tr>${cards}</tr></thead>${body ? `<tbody>${body}</tbody>` : ""}</table></div>
        ${actions ? `<p class="compare-actions">${actions}</p>` : ""}
    </section>`;
}

// One copy. del and remove are the data attributes of the bin and of Remove from library (none: no button); lines are
// HTML the caller has escaped; extra is more buttons beside Remove from library.
function compareCardHtml({ id = "", picture = "", name = "", lines = [], keep = false, note = "", arr = "", path = "",
    del = "", delTitle = "Delete this copy from disk", remove = "", extra = "" } = {}) {
    const bin = del
        ? `<button type="button" class="upgrade-delete" ${del} title="${escapeHtml(delTitle)}" aria-label="${escapeHtml(delTitle)}">${trashSvg()}</button>`
        : "";
    const buttons = [remove ? `<button type="button" class="btn-ghost btn-remove" ${remove}>Remove from library</button>` : "", extra]
        .filter(Boolean).join(" ");
    return `<th class="video-dup-card compare-card${keep ? " is-keep" : ""}" data-id="${escapeHtml(id)}">
        ${bin}
        ${keep ? `<p class="dup-keep">Suggested to keep</p>` : ""}
        ${note || ""}
        ${picture || ""}
        <div class="dup-name">${escapeHtml(name)}</div>
        ${(lines || []).filter(Boolean).map((line) => `<div class="upgrade-label">${line}</div>`).join("")}
        <div class="dup-arr-slot">${arr || ""}</div>
        <span class="upgrade-path">${escapeHtml(path)}</span>
        ${buttons ? `<p class="video-dup-actions">${buttons}</p>` : ""}
    </th>`;
}

// Not duplicates for a group: one button for two copies, one per other copy (named) for more.
function compareDismissButtons(items, attrs) {
    if ((items || []).length < 2) return "";
    return items.slice(1).map((item, index) => {
        const named = items.length > 2 ? ` (${escapeHtml(item.label || `copy ${index + 2}`)})` : "";
        return `<button type="button" class="btn-ghost" ${attrs(items[0], item)}>Not duplicates${named}</button>`;
    }).join(" ");
}

// The shared ids two folders have, for the reason line of a show or artist folder compare.
function compareSharedIds(first, other, fields) {
    return fields.filter(([key]) => first[key] && other[key] && String(first[key]).toLowerCase() === String(other[key]).toLowerCase())
        .map(([, label]) => label);
}
