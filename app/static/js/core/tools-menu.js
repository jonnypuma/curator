// The Tools menu in the header: every library tool in one place.

const TOOLS_OPEN = {
    "tools-wishlist": () => openWishlist(),
    "tools-cleanup": () => openCleanup(),
    "tools-history": () => openActivityHistory(),
    "tools-changes": () => openWhatsChanged(),
    "tools-journeys": () => openJourneys(),
    "tools-disk": () => openDisk(),
    "tools-orphans": () => openOrphans(),
    "tools-trash": () => openTrash(),
    "tools-musicvideos": () => openMusicVideos(),
    "tools-analytics": () => openInsights(),
};

function closeToolsMenu() {
    const menu = document.getElementById("tools-menu");
    if (menu) menu.classList.add("hidden");
    const button = document.querySelector('[data-action="tools-toggle"]');
    if (button) button.setAttribute("aria-expanded", "false");
}

function onToolsAction(name) {
    if (name === "tools-toggle") {
        const menu = document.getElementById("tools-menu");
        const open = menu.classList.contains("hidden");
        menu.classList.toggle("hidden", !open);
        document.querySelector('[data-action="tools-toggle"]').setAttribute("aria-expanded", open ? "true" : "false");
        return true;
    }
    closeToolsMenu();
    const open = TOOLS_OPEN[name];
    return open ? runAction(open) : false;
}

document.addEventListener("click", (event) => {
    if (!event.target.closest(".tools-wrap")) closeToolsMenu();
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeToolsMenu();
});
