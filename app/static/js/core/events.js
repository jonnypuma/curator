function fitModalChrome() {
    const header = document.querySelector("header");
    const dock = document.getElementById("dock");
    const top = header && header.getClientRects().length ? Math.max(0, Math.round(header.getBoundingClientRect().bottom)) : 0;
    const bottom = dock && dock.getClientRects().length ? Math.max(0, Math.round(window.innerHeight - dock.getBoundingClientRect().top)) : 0;
    document.documentElement.style.setProperty("--chrome-top", `${top}px`);
    document.documentElement.style.setProperty("--chrome-bottom", `${bottom}px`);
}

function placeJobsDrawer(anchor) {
    // The drawer's CSS already pins it above its parent (.dock-jobs) via
    //   position: absolute; right: 0; bottom: calc(100% + 8px);
    // Chip-anchored inline positioning used to push it off-screen when the activity bar sat
    // at the bottom of the window. Keeping the CSS default means every chip opens the drawer
    // in the same predictable spot - above the dock. The chip is still remembered on the
    // drawer so a second click on the same chip toggles it closed.
    const drawer = document.getElementById("job-drawer");
    if (!drawer) return;
    drawer.classList.remove("hidden");
    state.jobsReveal = true;
    drawer.dataset.jobsChip = anchor ? jobsChipKey(anchor) : "";
    drawer.scrollTop = 0;
    ["position", "zIndex", "top", "bottom", "left", "right", "width", "maxHeight"].forEach((key) => {
        drawer.style[key] = "";
    });
    schedulePoll(200);
}

function jobsChipKey(chip) {
    return chip ? String(chip.innerText || "").replace(/\s+/g, " ").trim() : "";
}

function jobsActivityChip(node) {
    const chip = node && node.closest ? node.closest("[data-action='open-activity']") : null;
    if (!chip) return null;
    const open = chip.dataset.open || "";
    if (open === "scan" || open === "scrape" || open === "queue") return null;
    return chip;
}

function closeJobsDrawer() {
    const drawer = document.getElementById("job-drawer");
    if (!drawer || drawer.classList.contains("hidden")) return;
    drawer.classList.add("hidden");
    drawer.dataset.jobsChip = "";
}

function bindEvents() {
    fitModalChrome();
    if (typeof bindArtSplit === "function") bindArtSplit();
    window.addEventListener("resize", fitModalChrome);
    if (window.ResizeObserver) {
        const chrome = new ResizeObserver(fitModalChrome);
        const header = document.querySelector("header");
        const dock = document.getElementById("dock");
        if (header) chrome.observe(header);
        if (dock) chrome.observe(dock);
    }
    document.getElementById("library-filter").addEventListener("change", (event) => {
        state.filter = event.target.value;
        sessionStorage.setItem("resonance.filter", state.filter);
        if (typeof syncLibraryFilterButton === "function") syncLibraryFilterButton();
        const overlay = document.getElementById("filter-overlay");
        if (overlay) overlay.classList.remove("hidden");
        if (typeof startFilterProgress === "function") startFilterProgress();
        loadLibrary().finally(() => {
            if (typeof stopFilterProgress === "function") stopFilterProgress();
            if (overlay) overlay.classList.add("hidden");
        });
    });
    const librarySort = document.getElementById("library-sort");
    if (librarySort) {
        librarySort.value = state.librarySort || "name";
        librarySort.addEventListener("change", (event) => {
            const mode = event.target.value;
            state.librarySort = mode === "artists" || mode === "albums" || mode === "modified" ? mode : "name";
            localStorage.setItem("resonance.librarySort", state.librarySort);
            renderTree();
        });
    }
    document.getElementById("artist-search").addEventListener("input", debounce((event) => {
        state.query = event.target.value.trim();
        loadLibrary();
    }, 250));
    const tree = document.getElementById("tree");
    if (tree) {
        const clearTreeScrollGuard = () => { state.treeScrollAt = 0; };
        tree.addEventListener("wheel", clearTreeScrollGuard, { passive: true });
        tree.addEventListener("touchmove", clearTreeScrollGuard, { passive: true });
        tree.addEventListener("pointerdown", clearTreeScrollGuard, { passive: true });
        tree.addEventListener("scroll", () => {
            if (typeof noteTreeScroll === "function") noteTreeScroll(tree);
            if (state.treePainting) return;
            paintTreeWindow(false);
        });
    }
    window.addEventListener("resize", () => paintTreeWindow(true));
    document.body.addEventListener("click", onClick);
    document.body.addEventListener("change", onChange);
    document.body.addEventListener("input", (event) => {
        if (event.target.dataset.schedulePreview) queueSchedulePreview();
        if (event.target.id === "artist-pick-query") queueArtistPick();
        if (event.target.id === "library-filter-find" && typeof paintLibraryFilterOptions === "function") paintLibraryFilterOptions();
    });
    document.addEventListener("keydown", onKeyDown);
    applyTheme(state.theme);
    applyDensity(state.density);
    applyPanes();
    bindSplitters();
    bindPlayer();
    bindLoupe();
    window.addEventListener("resize", applyPanes);
    const tracks = document.getElementById("tracks");
    tracks.addEventListener("dblclick", onTrackDblClick);
    tracks.addEventListener("contextmenu", onTrackMenu);
    document.getElementById("tree").addEventListener("contextmenu", onTreeMenu);
    document.getElementById("center-artist").addEventListener("contextmenu", onDiscogMenu);
    const settingsBody = document.getElementById("settings-body");
    settingsBody.addEventListener("dragstart", onPriorityDragStart);
    settingsBody.addEventListener("dragover", onPriorityDragOver);
    settingsBody.addEventListener("drop", onPriorityDrop);
    settingsBody.addEventListener("dragend", onPriorityDragEnd);
    document.getElementById("editor-diff").addEventListener("contextmenu", onDiffMenu);
    document.getElementById("editor").addEventListener("contextmenu", onTagMenu);
    document.getElementById("palette-input").addEventListener("input", renderPalette);
    const artworkFile = document.getElementById("artwork-file");
    if (artworkFile) artworkFile.addEventListener("change", () => {
        const file = artworkFile.files && artworkFile.files[0];
        const target = state.artUpload;
        artworkFile.value = "";
        if (!file || !target) return;
        runAction(() => uploadArtwork(file, target), "Uploading artwork…");
    });
    const videoArtFile = document.getElementById("video-art-file");
    if (videoArtFile) videoArtFile.addEventListener("change", () => {
        const file = videoArtFile.files && videoArtFile.files[0];
        const artKind = state.videoArtUpload;
        videoArtFile.value = "";
        if (!file || !artKind) return;
        runAction(() => uploadVideoArt(file, artKind), "Uploading artwork…");
    });
    const artworkSearch = document.getElementById("artwork-search");
    if (artworkSearch) artworkSearch.addEventListener("submit", (event) => {
        event.preventDefault();
        runAction(searchArtwork, "Searching artwork…");
    });
    const artistSearch = document.getElementById("artist-search-form");
    if (artistSearch) artistSearch.addEventListener("submit", (event) => {
        event.preventDefault();
        runAction(runArtistMetadataSearch, "Searching artist metadata…");
    });
    const addArtist = document.getElementById("add-artist-form");
    if (addArtist) addArtist.addEventListener("submit", (event) => {
        event.preventDefault();
        runAction(searchAddArtist, "Searching artists…");
    });
    const reviewSearch = document.getElementById("review-search-form");
    if (reviewSearch) reviewSearch.addEventListener("submit", (event) => {
        event.preventDefault();
        runAction(searchAlbumReviews, "Searching reviews…");
    });
    document.addEventListener("selectionchange", () => {
        if (!state.scanLogHeld) return;
        const node = document.getElementById("scan-log");
        if (scanLogSelectionHeld(node)) return;
        state.scanLogHeld = false;
        if (state.scan) setScanLog(state.scan.log || state.scan.message || "Idle.");
    });
    syncLibraryTools();
}

async function onClick(event) {
    const subSyncRow = event.target.closest && event.target.closest("#sub-sync-list .sub-sync-row");
    if (subSyncRow && !event.target.closest("button, textarea, input, label")
        && typeof selectSubSyncCue === "function") {
        selectSubSyncCue(subSyncRow.dataset.cueIndex);
        return;
    }

    // Click inside the alert toast - leave it open so the user can select and copy text.
    // Click OUTSIDE while it is visible dismisses it, which is the standard dialog pattern.
    const toast = document.getElementById("toast-pop");
    if (toast && !toast.classList.contains("hidden") && !toast.contains(event.target)) {
        dismissToast();
        // fall through: the click may also be on a chip or button that should still act.
    }
    // Scan chip fast-path. Any ancestor with data-action="open-activity" + data-open="scan"
    // or data-action="open-scan" opens the matching scan engine immediately, before anything
    // else can swallow the click. Also catches the "Scan engine" button inside the jobs
    // drawer. If the handlers below are the problem, this bypasses them; if they are not,
    // it is a no-op (the normal dispatcher reached the same destination either way).
    const scanAnchor = event.target.closest(
        "[data-action='open-activity'][data-open='scan'],[data-action='open-scan'],[data-action='open-activity-scan']"
    );
    if (scanAnchor) {
        try { console.log("[scan-chip] clicked", scanAnchor.dataset.action, scanAnchor.dataset.scanMedia || "(no media)"); } catch (_) {}
        try { closeJobsDrawer(); } catch (_) {}
        const media = scanAnchor.dataset.scanMedia || (state.media === "sets" ? "sets" : (typeof scanKind === "function" ? scanKind() : "music"));
        if (media === "movies" || media === "tv" || media === "sets") {
            if (typeof openVideoScanModal === "function") { event.preventDefault(); event.stopPropagation(); openVideoScanModal(media); return; }
        } else if (typeof openScanModal === "function") {
            event.preventDefault();
            event.stopPropagation();
            openScanModal();
            return;
        }
        try { console.warn("[scan-chip] open modal function not available", { media }); } catch (_) {}
    }
    if (!event.target.closest(".saved-filter-menu")) {
        document.querySelectorAll(".saved-filter-list").forEach((list) => list.classList.add("hidden"));
    }
    if (!event.target.closest(".filter-picker")) {
        if (typeof closeLibraryFilterMenu === "function") closeLibraryFilterMenu();
    }
    if (!event.target.closest(".preset-field, .preset-menu")) closePresetMenus();
    else if (event.target.closest(".preset-field input")) openPresetMenu(event.target.closest(".preset-field"));
    if (state.artistNameEditing && !event.target.closest("#artist-name-input, [data-action='edit-artist-name']")) {
        cancelArtistNameEdit();
    }
    if (state.albumTitleEditing && !event.target.closest("#album-title-input, [data-action='edit-album-title']")) {
        cancelAlbumTitleEdit();
    }
    if (event.target.id === "palette") {
        closePalette();
        return;
    }
    if (event.target.closest(".cell-edit, .diff-edit")) return;
    const trackMenu = document.getElementById("track-menu");
    if (trackMenu && !event.target.closest("#track-menu")) trackMenu.classList.add("hidden");
    const jobsDrawer = document.getElementById("job-drawer");
    if (jobsDrawer && !jobsDrawer.classList.contains("hidden") && !event.target.closest("#job-drawer") && !event.target.closest("[data-action='toggle-jobs']") && !jobsActivityChip(event.target)) {
        closeJobsDrawer();
    }
    const albumMenu = document.getElementById("album-menu");
    if (albumMenu && !event.target.closest("#album-menu")) {
        albumMenu.classList.add("hidden");
        state.contextAlbumIds = null;
    }
    const diffMenu = document.getElementById("diff-menu");
    if (diffMenu && !event.target.closest("#diff-menu")) diffMenu.classList.add("hidden");
    const density = event.target.closest(".density-switch [data-density]");
    if (density) {
        applyDensity(density.dataset.density);
        return;
    }
    const inspector = event.target.closest("[data-inspector]");
    if (inspector) {
        switchInspector(inspector.dataset.inspector);
        return;
    }
    const tokenButton = event.target.closest("[data-token]");
    if (tokenButton) {
        insertRenameToken(tokenButton.dataset.token);
        return;
    }
    const backdrop = event.target.classList && event.target.classList.contains("modal") ? event.target : null;
    if (backdrop && !backdrop.classList.contains("hidden") && !backdrop.classList.contains("is-prompt")) {
        if (typeof scanLogSelectionHeld === "function" && scanLogSelectionHeld(backdrop)) return;
        if (!(backdrop.id === "upgrade-modal" && state.upgradeReplacing)) {
            if (backdrop.id === "upgrade-modal") state.videoUpgrade = null;
            const artworkClosed = backdrop.id === "artwork-modal";
            backdrop.classList.add("hidden");
            document.documentElement.scrollLeft = 0;
            document.body.scrollLeft = 0;
            const snackbar = document.getElementById("snackbar");
            if (snackbar) snackbar.classList.add("hidden");
            if (artworkClosed && state.artDirty) {
                state.artDirty = false;
                refreshOpenArtwork().catch((error) => notify(error.message, "error"));
            }
            return;
        }
    }
    const closer = event.target.closest("[data-close]");
    if (closer) {
        if (state.upgradeReplacing && closer.dataset.close === "upgrade-modal") return;
        if (closer.dataset.close === "upgrade-modal") state.videoUpgrade = null;
        const modal = document.getElementById(closer.dataset.close);
        const advanceArtwork = closer.dataset.close === "artwork-modal" && modal && !modal.classList.contains("hidden") && !modal.classList.contains("is-prompt");
        const artworkClosed = closer.dataset.close === "artwork-modal";
        if (modal && !modal.classList.contains("is-prompt")) modal.classList.add("hidden");
        document.documentElement.scrollLeft = 0;
        document.body.scrollLeft = 0;
        const snackbar = document.getElementById("snackbar");
        if (snackbar) snackbar.classList.add("hidden");
        if (artworkClosed && state.artDirty) {
            state.artDirty = false;
            refreshOpenArtwork().catch((error) => notify(error.message, "error"));
        }
        if (advanceArtwork) advanceArtworkQueue();
        return;
    }
    if (event.target.closest("#scan-toggle")) {
        if (!scanBusy()) toggleScanMenu();
        return;
    }
    const scanMenu = document.getElementById("scan-menu");
    if (scanMenu && !event.target.closest("#scan-group")) scanMenu.classList.add("hidden");
    const toastLog = document.getElementById("toast-log");
    if (toastLog && !toastLog.classList.contains("hidden") && !event.target.closest("#toast-dock, #toast-log, #toast-pop")) {
        toastLog.classList.add("hidden");
    }
    if (event.target.closest("#scan-btn")) {
        closeScanMenu();
        if (state.media === "sets") {
            const scrape = state.videoScrape || {};
            if (scrape.status === "running" && scrape.media === "sets") return cancelVideoScrape();
            return openVideoScanModal("sets");
        }
        if (ownScanRunning()) return scanKind() === "music" ? cancelScan() : cancelVideoScan();
        return scanKind() === "music" ? openScanModal() : openVideoScanModal();
    }
    if (event.target.closest("#settings-btn")) return openSettings();
    if (event.target.closest("#acoustid-btn")) return runAction(findMetadata, "Finding metadata…");
    if (event.target.closest("#save-tags")) {
        if (state.inspector === "artist-nfo") return runAction(saveArtistProfile);
        if (state.inspector === "album-nfo") return runAction(saveAlbumProfile);
        return runAction(saveTags);
    }
    if (event.target.closest("#columns-btn")) {
        const menu = document.getElementById("column-menu");
        if (menu) menu.classList.toggle("hidden");
        return;
    }
    const menu = document.getElementById("column-menu");
    if (menu && !event.target.closest("#column-menu")) menu.classList.add("hidden");

    if (event.target.closest("[data-check-artist]")) return;
    const duplicatePill = event.target.closest("#tree .duplicate-pill");
    if (duplicatePill) {
        const albumButton = duplicatePill.closest("[data-album]");
        if (albumButton) {
            return runAction(() => openDuplicates({ media: "music", id: albumButton.dataset.album }), "Looking up duplicates…");
        }
    }
    const upgradePill = event.target.closest("#tree .upgrade-pill");
    if (upgradePill) {
        const albumButton = upgradePill.closest("[data-album]");
        if (albumButton) {
            state.expanded.add(albumButton.dataset.artistId);
            persistExpanded();
            await selectAlbum(albumButton.dataset.album);
            await showUpgrade();
            return;
        }
    }
    const toggle = event.target.closest("[data-toggle-artist]");
    if (toggle) {
        toggleArtist(toggle.dataset.toggleArtist);
        return;
    }
    const nfoPill = event.target.closest("[data-action='show-album-nfo-diff']");
    if (nfoPill) {
        await showAlbumNfoModal(nfoPill.dataset.albumId);
        return;
    }
    const artistNfoPill = event.target.closest("[data-action='show-artist-nfo-diff']");
    if (artistNfoPill) {
        await showArtistNfoModal(artistNfoPill.dataset.artistId);
        return;
    }
    const openArtist = event.target.closest("[data-open-artist]");
    if (openArtist) {
        state.expanded.add(openArtist.dataset.openArtist);
        persistExpanded();
        await selectArtist(openArtist.dataset.openArtist);
        return;
    }
    const albumButton = event.target.closest("#tree [data-album]");
    if (albumButton) {
        state.expanded.add(albumButton.dataset.artistId);
        persistExpanded();
        await selectAlbum(albumButton.dataset.album);
        return;
    }
    const trackRow = event.target.closest("tr[data-track], [data-side='local']");
    if (trackRow && state.album) {
        stashProposal();
        selectTrack(trackRow.dataset.track, event);
        renderTracks();
        renderEditor();
        return;
    }
    if (event.target.id === "art-zoom") {
        closeArtZoom();
        return;
    }
    const action = event.target.closest("[data-action]");
    if (!action) return;
    actionButton = busyButton(action);
    queueMicrotask(() => { actionButton = null; });
    const name = action.dataset.action;
    if (name === "grid-size") return setGridSize(action.dataset.gridSize);
    if (name.startsWith("sub-sync-")) {
        const handler = (typeof SUB_SYNC_ACTIONS !== "undefined") ? SUB_SYNC_ACTIONS[name] : null;
        if (handler) return handler(action);
    }
    if (name.startsWith("video-") || name.startsWith("trakt-") || name === "library-update-send") return onVideoAction(name, action, event);
    if (name.startsWith("insights-")) return onInsightsAction(name, action);
    if (name.startsWith("tags-")) return onTagsAction(name, action);
    if ((name.startsWith("queue-") || name.startsWith("auto-") || name.startsWith("kodi-sources-")) && onAutomationAction(name, action)) return;
    if (name === "album-menu" && action.dataset.menu === "mark-album") return queueSelectedProcessed();
    if (name === "album-menu") return runAction(() => runAlbumMenu(action.dataset.menu));
    if (name === "discog-menu" && action.dataset.menu === "missing-art") return runAction(downloadDiscogArtwork, "Downloading artwork…");
    if (name === "discog-menu") {
        if (arrSearchBlocked("lidarr")) {
            document.getElementById("album-menu").classList.add("hidden");
            return;
        }
        return runAction(searchLidarrRelease, "Asking Lidarr…");
    }
    if (name === "artist-menu") return runAction(() => runArtistMenu(action.dataset.menu));
    if (name === "confirm-danger") return runAction(confirmDanger);
    if (name === "confirm-danger-library") return runAction(confirmDangerLibrary);
    if (name === "diff-command") return runDiffCommand(action.dataset.diffCommand);
    if (name === "save-diff") return runAction(() => saveDiffField(action.dataset.diffKey), "Saving tag…");
    if (name === "saved-filter-confirm") return runAction(confirmSavedFilter, "Saving filter…");
    if (name === "music-filter-clear") return applyMusicPreset("all");
    if (name === "library-filter-toggle") return toggleLibraryFilterMenu();
    if (name === "library-filter-pick") return pickLibraryFilter(action.dataset.filter);
    if (name === "music-filter-save") return openSavedFilterModal("music");
    if (name === "music-filter-menu") {
        event.stopPropagation();
        ensureSavedFilters("music");
        return toggleSavedFilterMenu("music-saved-filters");
    }
    if (name === "music-filter-apply") {
        const row = ((state.video.savedFilters || {}).music || []).find((item) => item.id === action.dataset.id);
        if (row) applyMusicPreset((row.payload || {}).preset || "all");
        const menu = document.getElementById("music-saved-filters");
        if (menu) menu.classList.add("hidden");
        return;
    }
    if (name === "music-filter-delete") {
        event.stopPropagation();
        return runAction(() => deleteSavedFilter(action.dataset.id, "music"));
    }
    if (name === "apply-all-matches") return openPendingAlbums();
    if (name === "apply-all-matches-confirm") {
        const ids = pendingAlbumIds();
        document.getElementById("pending-album-modal").classList.add("hidden");
        if (!ids.length) return;
        return runAction(() => applyAllMatches(ids), "Applying matches…");
    }
    if (name === "pending-album-remove") return removePendingAlbumRow(action);
    if (name === "add-artist") return openAddArtist();
    if (name === "pick-add-artist") return runAction(() => addChosenArtist(action.dataset.mbid), "Adding artist…");
    if (name === "match") return runAction(findMetadata, "Finding metadata…");
    if (name === "edit-review") return startReviewEdit();
    if (name === "cancel-review") return cancelReviewEdit();
    if (name === "save-review") return runAction(saveAlbumReview, "Saving review…");
    if (name === "refresh-review") return openReviewSearch();
    if (name === "toggle-review") return toggleAlbumReview();
    if (name === "toggle-bio") return toggleArtistBio();
    if (name === "pick-review") return runAction(() => saveChosenReview(action), "Saving review…");
    if (name === "apply") return runAction(applyMatch, "Applying match…");
    if (name === "send-library-update") return runAction(sendAlbumLibraryUpdate, "Queuing library update…");
    if (name === "cancel-proposal") {
        if (state.album) setPending(state.album.album.id, null);
        state.proposal = null;
        state.aligner = false;
        renderTree();
        renderAlbum();
        renderEditor();
        return;
    }
    if (name === "toggle-aligner") {
        state.aligner = !state.aligner;
        renderTracks();
        return;
    }
    if (name === "auto-number") return runAction(autoNumber);
    if (name === "set-disc") return runAction(setDiscNumber);
    if (name === "keep-old-field") return keepOldField();
    if (name === "keep-old-song") return keepOldSongValues();
    if (name === "keep-old-album") return keepOldAlbumValues();
    if (name === "missing-chip") {
        if (action.dataset.subject === "artist" && action.dataset.focus === "nfo") return runAction(writeArtistNfo);
        return openArtwork(action.dataset.subject || "album", action.dataset.focus);
    }
    if (name === "view-nfo") return runAction(() => showNfo(action.dataset.subject));
    if (name === "nfo-copy") return runAction(copyOpenNfo);
    if (name === "nfo-write") return runAction(writeOpenNfo);
    if (name === "nfo-keep-field") return runAction(() => keepNfoField(action), "Keeping the .nfo value…");
    if (name === "view-chip") return openChipZoom(action.dataset.subject, action.dataset.focus);
    if (name === "palette-pick") return runPalette(action.dataset.kind, action.dataset.id);
    if (name === "undo-snack") {
        document.getElementById("snackbar").classList.add("hidden");
        return runAction(rollbackBatch);
    }
    if (name === "player-span") return togglePlaybackSpan();
    if (name === "artwork") return openArtwork(action.dataset.subject || "album");
    if (name === "lyrics") return runAction(fetchLyrics, "Fetching lyrics…");
    if (name === "lyrics-edit") return openLyricsEditor && openLyricsEditor();
    if (name === "mark-album") return runAction(() => mark("albums", state.album.album.id, nextProcessStatus(state.album.album.status)));
    if (name === "ignore-album") return runAction(() => mark("albums", state.album.album.id, nextIgnoreStatus(state.album.album.status)));
    if (name === "lock-album") return runAction(() => lockLibraryRows("album", [state.album.album.id], !state.album.album.locked));
    if (name === "compilation") return runAction(treatCompilation);
    if (name === "group-compilation") return runAction(groupCompilation);
    if (name === "replaygain") return runAction(runReplayGain);
    if (name === "audit") return runAction(runAudit);
    if (name === "show-upgrade") return runAction(showUpgrade, "Looking up upgrades…");
    if (name === "pick-upgrade") {
        state.upgradeSource = action.dataset.id;
        renderUpgradeDialog();
        return;
    }
    if (name === "delete-upgrade") {
        state.deleteCopyFrom = "upgrade";
        askDeleteCopy(action.dataset.id);
        return;
    }
    if (name === "delete-duplicate") {
        askDeleteDuplicate(action.dataset.id);
        return;
    }
    if (name === "cancel-delete-copy") {
        document.getElementById("delete-copy-modal").classList.add("hidden");
        return;
    }
    if (name === "confirm-delete-copy") return runAction(confirmDeleteCopy, "Deleting files…");
    if (name === "confirm-upgrade") {
        if (state.upgradeReplacing) return;
        const purge = document.getElementById("upgrade-purge").checked;
        setUpgradeReplacing(true);
        return runAction(() => confirmUpgrade(purge), "Replacing…").finally(() => setUpgradeReplacing(false));
    }
    if (name === "check-gaps") return runAction(checkGaps, "Checking MusicBrainz…");
    if (name === "download-missing-art") return runAction(downloadMissingArt, "Downloading artwork…");
    if (name === "open-split") {
        document.getElementById("split-modal").classList.remove("hidden");
        return;
    }
    if (name === "confirm-split") return runAction(confirmSplit);
    if (name === "lang-open") return runAction(openLanguageDefaults);
    if (name.startsWith("lang-")) return onLanguageAction(name, action);
    if (name === "open-duplicates") {
        const focus = action.dataset.id
            ? { media: action.dataset.kind === "episode" ? "tv" : "movies", id: action.dataset.id }
            : null;
        return runAction(() => openDuplicates(focus), "Looking up duplicates…");
    }
    if (name === "scan-duplicates") return runAction(scanDuplicates, "Fingerprinting tracks…");
    if (name === "dismiss-duplicate") return runAction(() => dismissDuplicatePair(action.dataset.index));
    if (name === "dismiss-video-duplicate") return runAction(async () => {
        const data = await api("/api/v1/video-duplicates/dismiss", { method: "POST", body: { kind: action.dataset.kind, left_id: action.dataset.left, right_id: action.dataset.right } });
        if (typeof clearVideoDuplicatePills === "function") clearVideoDuplicatePills(data.cleared);
        state.duplicateUndo = { media: action.dataset.kind === "episode" ? "tv" : "movies", kind: data.kind, left_id: data.left_id, right_id: data.right_id };
        notify("Those copies are no longer marked as duplicates.", "success");
        return openDuplicates(state.duplicateFocus);
    }, "Saving…");
    if (name === "undo-duplicate") return runAction(undoDuplicateDismiss, "Restoring…");
    if (name === "delete-video-duplicate") return askVideoDuplicate(action, true);
    if (name === "remove-video-duplicate") return askVideoDuplicate(action, false);
    if (name === "refresh-discography") return runAction(refreshDiscography, "Loading discography…");
    if (name === "lidarr-missing") {
        if (arrSearchBlocked("lidarr")) return;
        return runAction(searchMissingLidarr, "Asking Lidarr…");
    }
    if (name === "toggle-preview") return togglePreview();
    if (name === "toggle-jobs") {
        const drawer = document.getElementById("job-drawer");
        const opening = drawer.classList.contains("hidden");
        if (!opening) closeJobsDrawer();
        else placeJobsDrawer();
        return;
    }
    if (name === "open-activity") {
        const open = action.dataset.open || "";
        if (open === "scan") {
            closeJobsDrawer();
            const media = action.dataset.scanMedia || (state.media === "sets" ? "sets" : scanKind());
            if (media === "movies" || media === "tv" || media === "sets") return openVideoScanModal(media);
            return openScanModal();
        }
        if (open === "scrape") {
            closeJobsDrawer();
            return openVideoScrapeModal();
        }
        if (open === "queue") {
            closeJobsDrawer();
            return openQueuePanel(action.dataset.tab);
        }
        const drawer = document.getElementById("job-drawer");
        if (drawer && !drawer.classList.contains("hidden") && drawer.dataset.jobsChip && drawer.dataset.jobsChip === jobsChipKey(action)) {
            closeJobsDrawer();
            return;
        }
        return placeJobsDrawer(action);
    }
    if (name === "open-scrape") {
        document.getElementById("job-drawer").classList.add("hidden");
        return openVideoScrapeModal();
    }
    if (name === "open-queue") {
        document.getElementById("job-drawer").classList.add("hidden");
        return openQueuePanel(action.dataset.tab || "webhook");
    }
    if (name === "open-scan" || name === "open-activity-scan") {
        document.getElementById("job-drawer").classList.add("hidden");
        const media = action.dataset.scanMedia || (state.media === "sets" ? "sets" : scanKind());
        if (media === "movies" || media === "tv" || media === "sets") return openVideoScanModal(media);
        return openScanModal();
    }
    if (name === "copy-job") return copyJob(action.dataset.job);
    if (name === "export-job") return exportJob(action.dataset.job);
    if (name === "toggle-alerts") return toggleAlerts();
    if (name === "clear-alerts") return clearAlerts();
    if (name === "clear-scan-log") return clearScanLog();
    if (name === "clear-video-scan-log") return typeof clearVideoScanLog === "function" ? clearVideoScanLog() : null;
    if (name === "scan-history") {
        const fromMusic = !!action.closest("#scan-modal");
        const media = fromMusic
            ? "music"
            : (state.videoScanFocus || (scanKind() === "tv" ? "tv" : (state.media === "sets" ? "sets" : "movies")));
        return openScanHistory(media);
    }
    if (name === "open-scan-report") return openScanReport(action.dataset.name);
    if (name === "scan-report-copy") return copyScanReport();
    if (name === "scan-results-copy") return copyScanResults();
    if (name === "scan-report-export") return exportScanReport();
    if (name === "rollback") return runAction(rollbackBatch);
    if (name === "mark-artist") return runAction(() => mark("artists", state.artistId || (state.album && state.album.artist.id), nextProcessStatus(currentArtistStatus())));
    if (name === "ignore-artist") return runAction(() => mark("artists", state.artistId || (state.album && state.album.artist.id), nextIgnoreStatus(currentArtistStatus())));
    if (name === "lock-artist") {
        const id = state.artistId || (state.album && state.album.artist && state.album.artist.id);
        const locked = state.center === "artist" && state.artistDetail && state.artistDetail.artist
            ? state.artistDetail.artist.locked
            : state.album && state.album.artist && state.album.artist.locked;
        return runAction(() => lockLibraryRows("artist", [id], !locked));
    }
    if (name === "show-files") return runAction(() => showReleaseFiles(action.dataset.filesAlbum), "Loading files…");
    if (name === "search-again") return runAction(searchAgain, "Searching MusicBrainz…");
    if (name === "toggle-compare") return runAction(() => toggleCompare(action.dataset.album), "Comparing tracks…");
    if (name === "pick-release") {
        if (event.target.closest(".candidate-score")) return focusCandidate(action.dataset.release);
        return runAction(() => pickRelease(action.dataset.release), "Loading release…");
    }
    if (name === "choose-scan-release") {
        if (event.target.closest(".candidate-score")) return focusScanCandidate(action.dataset.release);
        return runAction(() => chooseScanRelease(action.dataset.release), "Saving the release…");
    }
    if (name === "skip-scan-release") return runAction(() => answerScanPrompt({ action: "skip" }), "Skipping this album…");
    if (name === "continue-scan-artwork") return runAction(() => answerScanPrompt({ action: "continue" }), "Continuing the scan…");
    if (name === "skip-scan-artwork") return runAction(() => answerScanPrompt({ action: "skip" }), "Skipping artwork…");
    if (name === "delete-art") {
        askDanger(
            "Remove Artwork",
            "Are you sure you want to permanently remove this artwork file from disk and the database?",
            "Delete Artwork",
            () => runAction(() => deleteArt(action.dataset.art), "Removing artwork…"),
            true
        );
        return;
    }
    if (name === "select-art") return downloadArt(action.dataset.art);
    if (name === "undo-artwork") return runAction(undoArtwork, "Restoring artwork…");
    if (name === "highlight-art") return highlightArt(action.dataset.art);
    if (name === "upload-art") return chooseArtworkFile(action.dataset.asset, action.dataset.subject);
    if (name === "zoom-art") {
        openArtZoom(action.dataset.art);
        return;
    }
    if (name === "fanart-prev") return stepFanart(-1);
    if (name === "fanart-next") return stepFanart(1);
    if (name === "zoom-artist-thumb") {
        openArtistThumbZoom();
        return;
    }
    if (name === "zoom-album-cover") {
        openAlbumCoverZoom();
        return;
    }
    if (name === "close-zoom") {
        closeArtZoom();
        return;
    }
    if (name === "priority-up" || name === "priority-down") return movePriority(action.dataset.source, name === "priority-up" ? -1 : 1);
    if (name === "meta-priority-up" || name === "meta-priority-down") {
        return moveMetaPriority(action.dataset.purpose, action.dataset.source, name === "meta-priority-up" ? -1 : 1);
    }
    if (name === "suffix-type") return toggleSuffixType(action.dataset.suffixType);
    if (name === "copy-cmm-key") return copyCmmApiKey();
    if (name === "save-settings") return saveSettings();
    if (name === "save-scan-schedule") return saveScanSchedule();
    if (name === "remove-scan-schedule") return removeScanSchedule(action.dataset.index);
    if (name === "save-player-clean-schedule") return savePlayerCleanSchedule();
    if (name === "remove-player-clean-schedule") return removePlayerCleanSchedule(action.dataset.index);
    if (name === "backup-now") return backupNow();
    if (name === "restore-refresh") return runAction(loadBackupFiles);
    if (name === "restore-open") return openRestore(action.dataset.index);
    if (name === "restore-go") return runAction(startRestore, "Starting the restore…");
    if (name === "import-open") return openMusicImport(action.dataset.index);
    if (name === "import-go") return runAction(startMusicImport, "Starting the music import…");
    if (name === "add-path") return openPathBrowser();
    if (name === "browse-set-folder") return openPathBrowser("set-folder");
    if (name === "browse-backup-folder") return openPathBrowser("backup-folder");
    if (name === "browse-map-local") {
        const row = action.closest("[data-auto-map]");
        state.pathMapInput = row ? row.querySelector("[data-map-local]") : null;
        return openPathBrowser("map-local");
    }
    if (name === "add-mount") {
        const row = action.closest(".path-row");
        const type = row && row.querySelector("[data-mount-media]");
        return addLibraryPath(action.dataset.path, type ? type.value : "music");
    }
    if (name === "choose-scan") return chooseScanRoot(action.dataset.root || "");
    if (name === "path-up") return runAction(pathUp);
    if (name === "path-open") return runAction(() => browsePath(action.dataset.path || ""));
    if (name === "path-jump") return jumpToFolder(action.dataset.letter || "");
    if (name === "asset-all") return setAssetGroup(action, action.dataset.checked === "true");
    if (name === "use-path") return useBrowsedPath();
    if (name === "clear-key") return clearKey(action.dataset.field);
    if (name === "new-lidarr-token") return newLidarrToken();
    if (name === "add-lidarr-path") return addLidarrPath();
    if (name === "remove-lidarr-path") return removeLidarrPath(action.dataset.index);
    if (name === "test-key") return testApiKey(action);
    if (name === "logos-load") return runAction(() => loadMissingLogos(action.dataset.media), "Checking logos…");
    if (name === "logo-upload") return pickLogo(action.dataset.media, action.dataset.name);
    if (name === "purge-storage") return runAction(() => purgeStorage(action.dataset.folder), "Deleting files…");
    if (name === "about-open") return openAbout();
    if (name === "about-ytdlp-update") return updateYtdlp();
    if (name === "scan-force") return runAction(() => scan(true, "deep"));
    if (name === "cancel-scan") return scanKind() !== "music" && videoScanRunning() ? cancelVideoScan() : cancelScan();    if (name === "remove-path") return removeLibraryPath(action.dataset.path, action.dataset.media);
    if (name === "select-tier") return selectByTier(action.dataset.tier);
    if (name === "select-all") return selectVisible(true);
    if (name === "select-none") return selectVisible(false);
    if (name === "expand-all") return expandAll();
    if (name === "open-batch") return openBatchModal();
    if (name === "batch-scrape") return openLookupModal();
    if (name === "batch-rescan") return runAction(() => rescanSelectedAlbums(action), "Starting scan…");
    if (name === "batch-rescan-menu") return toggleRescanMenu(action);
    if (name === "batch-rescan-mode") return chooseRescanMode(action);
    if (name === "batch-edit-fields") return openBatchEdit("album", [...selectionChecked("album")]);
    if (name === "batch-edit-save") return runAction(saveBatchEdit, "Saving…");
    if (name === "open-lookup") return runAction(openLookupModal);
    if (name === "lookup-review") return runAction(() => startLookup("review"), "Finding metadata…");
    if (name === "lookup-auto") return runAction(() => startLookup("auto"), "Finding metadata…");
    if (name === "apply-write") return toggleApplyWrite(action.dataset.applyWrite);
    if (name === "lookup-apply") return loadLookupMatches();
    if (name === "open-rename") return openRenameModal();
    if (name === "save-rename") return runAction(saveRenameConfig);
    if (name === "run-batch") return runAction(runBatch);
    if (name === "batch-nfo") return runAction(() => rewriteSelectedNfos([...selectionChecked("album")]), "Writing .nfo files…");
    if (name === "batch-processed") return queueSelectedProcessed();
    if (name === "batch-lock") {
        const ids = [...selectionChecked("album")];
        const rows = (state.artists || []).flatMap((artist) => artist.albums || []).filter((album) => ids.includes(album.id));
        const unlock = rows.length > 0 && rows.every((album) => album.locked);
        return runAction(() => lockLibraryRows("album", ids, !unlock).then(() => renderBatchBar()), unlock ? "Unlocking albums…" : "Locking albums…");
    }
    if (name === "music-lock-field") return runAction(() => toggleMusicFieldLock(action), "Saving field lock…");
    if (name === "music-view-toggle") return toggleMusicViewMode();
    if (name === "music-filter-query") {
        const q = (action.dataset.query || "").trim();
        const input = document.getElementById("artist-search");
        if (input && q) {
            input.value = q;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            notify(`Filtered music library by "${q}".`, "info");
        }
        return;
    }
    if (name === "open-shortcuts") {
        const modal = document.getElementById("shortcuts-modal");
        if (modal) modal.classList.remove("hidden");
        return;
    }
    if (name === "music-prune-held") return runAction(removeAllNotFoundMusic, "Looking for albums marked Not found…");
    if (name === "video-prune-held") return removeAllNotFoundVideo();
    if (name === "batch-forget") return askBatchAlbumRemoval(false);
    if (name === "batch-delete") return askBatchAlbumRemoval(true);
    if (name === "start-scan") return runAction(startScanFromModal);
    if (name === "reset-columns") return resetColumns();
    if (name === "scrape-artist") return runAction(scrapeArtist, "Finding artist metadata…");
    if (name === "artist-move") {
        const artist = state.artistDetail && state.artistDetail.artist;
        if (!artist) return;
        return openVideoMove("artist", [artist.id]);
    }
    if (name === "artist-manual-search") return runAction(openArtistManualSearch, "Searching artist metadata…");
    if (name === "pick-artist-meta") return runAction(() => pickArtistMetadata(action.dataset.mbid), "Finding artist metadata…");
    if (name === "download-artist-art") return runAction(downloadArtistArt, "Downloading artwork…");
    if (name === "edit-artist-name") {
        if (state.artistNameEditing) return runAction(saveArtistName, "Saving artist name…");
        return startArtistNameEdit();
    }
    if (name === "delete-open-artist") return deleteOpenArtist();
    if (name === "edit-album-title") {
        if (state.albumTitleEditing) return runAction(saveAlbumTitle, "Saving album title…");
        return startAlbumTitleEdit();
    }
    if (name === "delete-open-album") return deleteOpenAlbum();
    if (name === "edit-bio") return startBioEdit();
    if (name === "cancel-bio") return cancelBioEdit();
    if (name === "save-bio") return runAction(saveBiography, "Saving biography…");
    if (name === "write-artist-nfo") return runAction(writeArtistNfo);
    if (name === "clear-artist-nfo") return runAction(clearArtistNfo, "Clearing artist info…");
    if (name === "merge-with") return openArtistPick();
    if (name === "pick-merge-artist") return chooseMergeArtist(action.dataset.id);
    if (name === "write-album-nfo") return runAction(writeAlbumNfo);
    if (name === "merge-artists") {
        const blocked = mergeChoiceError();
        if (blocked) {
            showMergeError(blocked);
            notify(blocked, "error");
            return;
        }
        return runAction(confirmArtistMerge, "Merging artists…");
    }
    if (name === "scan-mode-flag") return toggleScanModeFlag(action.dataset.scanFlag, action.dataset.scanMode);
    if (name === "remove-genre") {
        const chip = action.closest(".genre-chip");
        if (chip) chip.remove();
        return;
    }
    if (name === "add-genre") return addGenreChip(action.closest(".nfo-form") || action.parentElement);
    if (name === "jump-album") return selectAlbum(action.dataset.jumpAlbum);
}

function onChange(event) {
    if (event.target.id === "kodi-sources-file") {
        runAction(() => readKodiSources(event.target), "Reading sources.xml…");
        return;
    }
    if (event.target.name === "scan-mode" || event.target.id === "scan-force") {
        renderScanModal(state.scan || {});
        return;
    }
    if (event.target.name === "video-scan-mode") {
        renderVideoScanModal();
        return;
    }
    if (event.target.name === "schedule-mode" || event.target.name === "backup-mode") {
        const group = event.target.name === "backup-mode" ? "backup" : "schedule";
        showSchedulePanel(group, event.target.value);
        rememberSettingsForm();
        queueSchedulePreview();
        return;
    }
    if (event.target.name === "player-clean-mode") {
        showPlayerCleanPanel(event.target.value);
        return;
    }
    if (event.target.dataset.schedulePreview) queueSchedulePreview();
    if (event.target.dataset.lookupChoice) {
        const storedId = event.target.dataset.storedRelease || "";
        event.target.classList.toggle("has-stored", !!storedId && event.target.value === storedId);
        const albumId = event.target.dataset.lookupChoice;
        state.compareFocus[albumId] = event.target.value;
        if (state.compareOpen.has(albumId)) runAction(() => ensureCompare(albumId), "Comparing tracks…");
    }
    if (event.target.dataset.compareRelease) {
        const albumId = event.target.dataset.album;
        state.compareFocus[albumId] = event.target.value;
        const filesOpen = state.filesAlbumId === albumId && !document.getElementById("files-modal").classList.contains("hidden");
        runAction(async () => {
            await ensureCompare(albumId, { paint: !filesOpen });
            if (filesOpen) await paintFilesModal(albumId);
        }, "Comparing tracks…");
    }
    if (event.target.dataset.column) {
        if (event.target.dataset.column === "title") {
            event.target.checked = true;
            return;
        }
        state.columns[event.target.dataset.column] = event.target.checked;
        localStorage.setItem("resonance.columns", JSON.stringify(state.columns));
        renderTracks();
    }
    if (event.target.dataset.checkAlbum) {
        const id = event.target.dataset.checkAlbum;
        selectionSet("album", id, event.target.checked);
        const gridCard = event.target.closest(".vgrid-card");
        if (gridCard) gridCard.classList.toggle("is-checked", event.target.checked);
        state.contextAlbumIds = null;
        syncArtistChecks();
        renderBatchBar();
        refreshOpenLookup();
    }
    if (event.target.dataset.checkArtist) {
        const artist = state.artists.find((row) => row.id === event.target.dataset.checkArtist);
        const ids = visibleAlbumIds(artist);
        state.contextAlbumIds = null;
        ids.forEach((id) => {
            selectionSet("album", id, event.target.checked);
            const box = document.querySelector(`input[data-check-album="${CSS.escape(id)}"]`);
            if (box) {
                box.checked = event.target.checked;
                const gridCard = box.closest(".vgrid-card");
                if (gridCard) gridCard.classList.toggle("is-checked", event.target.checked);
            }
        });
        syncArtistChecks();
        renderBatchBar();
        refreshOpenLookup();
    }
    if (event.target.dataset.pathMedia && state.settings) retypeLibraryPath(event.target.dataset.pathMedia, event.target.value);
    if (event.target.id === "path-media") syncPathModalMedia();
    if (event.target.dataset.pathRole && state.settings) {
        state.settings.music_path_roles = state.settings.music_path_roles || {};
        state.settings.music_path_roles[event.target.dataset.pathRole] = event.target.value;
    }
    if (event.target.dataset.pathKind && state.settings) {
        state.settings.music_path_kinds = state.settings.music_path_kinds || {};
        state.settings.music_path_kinds[event.target.dataset.pathKind] = event.target.value;
    }
    if (event.target.id === "artist-merge-move" || event.target.id === "artist-merge-remove" || event.target.name === "artist-merge-master") refreshMergeNote();
    if (event.target.name && String(event.target.name).startsWith("merge-folder-")) showMergeError("");
    if (event.target.id === "theme-select") applyTheme(event.target.value);
    if (event.target.id === "resolution-preset") {
        const wrap = document.getElementById("min-resolution-wrap");
        if (wrap) wrap.classList.toggle("hidden", event.target.value !== "custom");
    }
    if (event.target.id === "embed-preset") {
        const wrap = document.getElementById("embed-max-wrap");
        if (wrap) wrap.classList.toggle("hidden", event.target.value !== "custom");
    }
    if (event.target.id === "path-mount") return runAction(() => browsePath(""));
    if (["lastfm-key", "fanart-key", "acoustid-key"].includes(event.target.id) && event.target.value.trim()) {
        const map = { "lastfm-key": "lastfm_key", "fanart-key": "fanart_key", "acoustid-key": "acoustid_key" };
        delete state.clearKeys[map[event.target.id]];
    }
    if (event.target.dataset.ribbonPick !== undefined || event.target.matches("[data-ribbon-pick]")) {
        const key = event.target.value;
        event.target.value = "";
        if (key && state.video) {
            const ribbons = libraryRibbons();
            if (ribbons.has(key)) ribbons.delete(key);
            else ribbons.add(key);
            renderVideoList();
        }
    }
    if (event.target.dataset.videoKey && event.target.value.trim()) delete state.clearKeys[event.target.dataset.videoKey];
    if (event.target.dataset.sourceEnabled && state.settings) {
        state.settings.sources_enabled = state.settings.sources_enabled || {};
        state.settings.sources_enabled[event.target.dataset.sourceEnabled] = event.target.checked;
        const row = event.target.closest(".priority-item");
        if (row) row.classList.toggle("is-off", !event.target.checked);
        if (row && !event.target.checked && row.parentElement) row.parentElement.appendChild(row);
    }
    const chainBox = event.target.closest("[data-chain-on], .priority-item input[type='checkbox']");
    if (chainBox && !chainBox.checked) {
        const row = chainBox.closest(".priority-item");
        if (row && row.parentElement) row.parentElement.appendChild(row);
    }
}
