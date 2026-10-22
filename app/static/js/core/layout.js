function applyTheme(name) {
    const known = ["mocha", "macchiato", "nord", "dracula", "oled", "olive", "sunset", "deepsea", "nightfall", "coastal", "lavender", "candle"];
    state.theme = known.includes(name) ? name : "mocha";
    document.documentElement.dataset.theme = state.theme;
    localStorage.setItem("resonance.theme", state.theme);
    const select = document.getElementById("theme-select");
    if (select && select.value !== state.theme) select.value = state.theme;
}

function applyDensity(name) {
    const known = ["compact", "standard", "relaxed"];
    state.density = known.includes(name) ? name : "standard";
    document.body.dataset.rows = state.density;
    delete document.body.dataset.density;
    localStorage.setItem("resonance.density", state.density);
    document.querySelectorAll(".density-switch [data-density]").forEach((button) => {
        button.classList.toggle("active", button.dataset.density === state.density);
    });
}

const MIN_CENTER_PANE = 360;

function applyPanes() {
    const main = document.querySelector("main");
    const left = document.getElementById("left-pane");
    const right = document.getElementById("right-pane");
    if (!main || !left || !right) return;
    if (window.innerWidth <= 1100) {
        main.style.gridTemplateColumns = "";
        left.classList.remove("is-collapsed");
        right.classList.remove("is-collapsed");
        return;
    }
    // Saved widths may come from a wider screen: keep room for the centre pane (the one that stretches).
    const room = main.clientWidth - 16 - MIN_CENTER_PANE;
    let wantLeft = state.pane.leftCollapsed ? 0 : state.pane.left;
    let wantRight = state.pane.rightCollapsed ? 0 : state.pane.right;
    if (room > 0 && wantLeft + wantRight > room) {
        const scale = room / (wantLeft + wantRight);
        wantLeft = Math.max(wantLeft ? 180 : 0, Math.floor(wantLeft * scale));
        wantRight = Math.max(wantRight ? 180 : 0, Math.floor(wantRight * scale));
    }
    const leftWidth = state.pane.leftCollapsed ? "0px" : `${Math.round(wantLeft)}px`;
    const rightWidth = state.pane.rightCollapsed ? "0px" : `${Math.round(wantRight)}px`;
    main.style.gridTemplateColumns = `${leftWidth} 8px minmax(0, 1fr) 8px ${rightWidth}`;
    left.classList.toggle("is-collapsed", !!state.pane.leftCollapsed);
    right.classList.toggle("is-collapsed", !!state.pane.rightCollapsed);
}

function bindSplitters() {
    document.querySelectorAll(".pane-split").forEach((handle) => {
        handle.addEventListener("mousedown", (event) => {
            if (event.button !== 0 || window.innerWidth <= 1100) return;
            const side = handle.dataset.split;
            const origin = event.clientX;
            const start = state.pane[side];
            const move = (ev) => {
                const delta = ev.clientX - origin;
                const width = side === "left" ? start + delta : start - delta;
                state.pane[side] = Math.max(180, Math.min(720, width));
                state.pane[side === "left" ? "leftCollapsed" : "rightCollapsed"] = false;
                applyPanes();
            };
            const up = () => {
                localStorage.setItem("resonance.panes", JSON.stringify(state.pane));
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
            };
            window.addEventListener("mousemove", move);
            window.addEventListener("mouseup", up);
        });
        handle.addEventListener("dblclick", () => {
            const flag = handle.dataset.split === "left" ? "leftCollapsed" : "rightCollapsed";
            state.pane[flag] = !state.pane[flag];
            localStorage.setItem("resonance.panes", JSON.stringify(state.pane));
            applyPanes();
        });
    });
}
