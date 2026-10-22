function savedLibraryFilter() {
    const saved = sessionStorage.getItem("resonance.filter") || "all";
    if (saved === "latest-artists" || saved === "latest-albums" || saved === "latest-modified") {
        sessionStorage.setItem("resonance.filter", "all");
        return "all";
    }
    return saved;
}

function savedLibrarySort() {
    const saved = localStorage.getItem("resonance.librarySort") || "";
    if (saved === "name" || saved === "artists" || saved === "albums" || saved === "modified") return saved;
    return localStorage.getItem("resonance.sortAdded") === "1" ? "albums" : "name";
}

const state = {
    filter: savedLibraryFilter(),
    query: "",
    artists: [],
    libraryLoaded: false,
    libraryError: "",
    totals: { artists: 0, albums: 0, tracks: 0 },
    expanded: new Set(JSON.parse(sessionStorage.getItem("resonance.expanded") || "[]")),
    selected: new Set(),
    album: null,
    artistId: null,
    artistDetail: null,
    bioEditing: false,
    bioDraft: "",
    bioDrafts: {},
    dirtyArtists: new Set(),
    dirtyAlbums: new Set(),
    staleNfoArtists: new Set(),
    staleNfoAlbums: new Set(),
    bulkDirtyAlbum: "",
    center: "album",
    trackId: null,
    trackIds: new Set(),
    trackAnchor: null,
    proposal: null,
    pending: {},
    candidates: [],
    localTracks: [],
    compareOpen: new Set(),
    compareFocus: {},
    compareCache: {},
    deezer: null,
    settings: null,
    mounts: [],
    musicPaths: [],
    scanRoot: "",
    clearKeys: {},
    pathBrowser: { root: "", path: "" },
    busy: false,
    scanning: false,
    jobs: {},
    stopping: false,
    scanLogCut: null,
    scanLogServer: "",
    scanScope: "",
    libraryStale: false,
    scanLibraryToken: "",
    scanPromptKey: "",
    scanPromptOpening: false,
    inspector: "tags",
    batching: false,
    lookupTimer: 0,
    lookupSignature: "",
    lookupSeen: "",
    lookupGeneration: 0,
    lookupPhase: "",
    lookupAutoApply: false,
    lookupCanApply: false,
    activityLabel: "",
    working: false,
    upgradeReplacing: false,
    pollTimer: 0,
    missingArtSeen: "",
    columns: { ...COLUMN_DEFAULTS, ...JSON.parse(localStorage.getItem("resonance.columns") || "{}") },
    columnWidths: loadColumnWidths(),
    pane: loadPane(),
    density: localStorage.getItem("resonance.density") || "standard",
    theme: localStorage.getItem("resonance.theme") || "mocha",
    aligner: false,
    fullPlayback: false,
    paletteIndex: 0,
    contextAlbum: null,
    sortIgnoreThe: true,
    reviewCollapsed: localStorage.getItem("resonance.reviewCollapsed") === "1",
    bioCollapsed: localStorage.getItem("resonance.bioCollapsed") === "1",
    librarySort: savedLibrarySort(),
    musicViewMode: localStorage.getItem("curator.musicViewMode") || "list",
    tagDrafts: {},
    diffCell: null,
};

function loadColumnWidths() {
    try {
        const saved = JSON.parse(localStorage.getItem("resonance.columnWidths") || "{}");
        if (!saved || typeof saved !== "object") return {};
        const widths = {};
        Object.entries(saved).forEach(([key, value]) => {
            const width = Math.round(Number(value));
            if (width >= 48 && width <= 720) widths[key] = width;
        });
        return widths;
    } catch (error) {
        return {};
    }
}

function columnWidth(key) {
    return state.columnWidths[key] || COLUMN_WIDTHS[key] || 120;
}

function loadPane() {
    try {
        const saved = JSON.parse(localStorage.getItem("resonance.panes") || "");
        if (saved && saved.left && saved.right) return saved;
    } catch (error) {
        return { left: 280, right: 360, leftCollapsed: false, rightCollapsed: false };
    }
    return { left: 280, right: 360, leftCollapsed: false, rightCollapsed: false };
}
state.columns.title = true;

let albumRequest = 0;
let artistRequest = 0;
let artworkLookupSerial = 0;
// Must be initialized before loadLibrary() below. A later let stays
// uninitialized while that call runs and stops the rest of this script.
let libraryFlight = null;
