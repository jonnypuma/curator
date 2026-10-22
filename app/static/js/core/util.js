function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[char]));
}

function librarySortName(name) {
    const text = String(name || "").trim();
    if (state.sortIgnoreThe === false) return text;
    const stripped = text.replace(/^(?:the|an|a)\s+/i, "").trim();
    return stripped || text;
}

function debounce(fn, wait) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}
