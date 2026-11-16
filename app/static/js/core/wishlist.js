// The upgrade wishlist: what falls short of the quality set under Settings, Files, with a search in the apps.

state.wishlist = { items: [], targets: {}, filter: "", searched: new Set() };
const WISHLIST_BATCH = 100;

function wishlistKey(item) {
    return `${item.kind}:${item.id}`;
}

// What "Search shown" would search next: shown, searchable, and not searched yet in this window.
function wishlistPending() {
    return wishlistShown().filter((item) => item.searchable && !state.wishlist.searched.has(wishlistKey(item)));
}

const WISHLIST_KINDS = { movie: "Movies", show: "TV shows", album: "Albums" };

async function openWishlist() {
    document.getElementById("wishlist-modal").classList.remove("hidden");
    document.getElementById("wishlist-list").innerHTML = `<p class="muted">Comparing…</p>`;
    const data = await api("/api/v1/wishlist");
    state.wishlist.items = data.items || [];
    state.wishlist.targets = data.targets || {};
    renderWishlist();
}

function wishlistTargetsText() {
    const targets = state.wishlist.targets || {};
    const video = (target) => [target && target.resolution, target && target.hdr ? "HDR" : ""].filter(Boolean).join(" + ") || "off";
    const music = { lossless: "lossless", hires: "24-bit lossless" }[(targets.music || {}).quality] || "off";
    return `Targets: movies ${video(targets.movies)}, TV ${video(targets.tv)}, music ${music}. Change them under Settings, Files.`;
}

function wishlistShown() {
    const words = state.wishlist.filter.toLowerCase().split(/\s+/).filter(Boolean);
    return state.wishlist.items.filter((item) => words.every((word) => `${item.label} ${item.reason}`.toLowerCase().includes(word)));
}

function renderWishlist() {
    document.getElementById("wishlist-targets").textContent = wishlistTargetsText();
    const shown = wishlistShown();
    const all = document.getElementById("wishlist-search-all");
    const pending = wishlistPending();
    all.disabled = !pending.length;
    all.textContent = pending.length
        ? `Search next ${Math.min(pending.length, WISHLIST_BATCH)}${pending.length > WISHLIST_BATCH ? ` (${pending.length} left)` : ""}`
        : (shown.some((item) => item.searchable) ? "All shown searched" : "Search shown");
    const host = document.getElementById("wishlist-list");
    if (!state.wishlist.items.length) {
        host.innerHTML = `<p class="muted">Nothing falls short of the targets.</p>`;
        return;
    }
    host.innerHTML = Object.entries(WISHLIST_KINDS).map(([kind, heading]) => {
        const rows = shown.filter((item) => item.kind === kind);
        if (!rows.length) return "";
        return `<h3>${escapeHtml(heading)} (${rows.length})</h3><table class="queue-table"><tbody>${rows.map((item) => `<tr>
                <td><strong>${escapeHtml(item.label)}</strong> <small class="muted">${escapeHtml(item.reason)}</small><br><small class="mono muted">${escapeHtml(item.path || "")}</small></td>
                <td class="queue-fit">${item.searchable
                    ? `<button type="button" class="btn-ghost" data-action="wishlist-search" data-kind="${escapeHtml(item.kind)}" data-id="${escapeHtml(item.id)}">${state.wishlist.searched.has(wishlistKey(item)) ? "Search again" : "Search"}</button>`
                    : `<small class="muted">No id to search with</small>`}</td>
            </tr>`).join("")}</tbody></table>`;
    }).join("");
}

async function searchWishlist(items) {
    const data = await api("/api/v1/wishlist/search", { method: "POST", body: { items } });
    notify(`${data.queued} search${data.queued === 1 ? "" : "es"} queued.${(data.errors || []).length ? ` ${data.errors[0]}` : ""}`, (data.errors || []).length ? "warning" : "info");
    items.forEach((item) => state.wishlist.searched.add(wishlistKey(item)));
    renderWishlist();
}

function onWishlistAction(name, action) {
    if (name === "wishlist-open") return runAction(openWishlist);
    if (name === "wishlist-search") {
        const item = state.wishlist.items.find((row) => row.id === action.dataset.id && row.kind === action.dataset.kind);
        return runAction(() => searchWishlist(item ? [item] : []));
    }
    if (name === "wishlist-search-all") {
        const batch = wishlistPending().slice(0, WISHLIST_BATCH);
        return askDanger(
            `Search for ${batch.length} item${batch.length === 1 ? "" : "s"}?`,
            `Radarr, Sonarr and Lidarr search for the next ${batch.length} of the ${wishlistPending().length} items shown that were not searched yet (up to ${WISHLIST_BATCH} at a time), and may download better copies. Press the button again for the rest.`,
            "Search",
            () => searchWishlist(batch),
            false,
        );
    }
    return false;
}

document.addEventListener("input", (event) => {
    if (event.target && event.target.id === "wishlist-filter") {
        state.wishlist.filter = event.target.value || "";
        renderWishlist();
    }
});
