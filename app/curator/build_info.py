"""The fingerprint of the page Curator serves: the version and every static file's hash. An open page compares it with
the one it was served with, so it can offer a reload after an update instead of running old scripts."""
import hashlib

_page = {"token": ""}


def set_page(version, static_hashes):
    text = version + "\n" + "\n".join(f"{name} {digest}" for name, digest in sorted((static_hashes or {}).items()))
    _page["token"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def page():
    return _page["token"]
