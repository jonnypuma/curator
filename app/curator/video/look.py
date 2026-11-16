"""Is one picture the same as another, resized, re-encoded, cropped or zoomed? For extra fanart repeats and for matching
a file on disk with the online pictures.

Fanart sites hold the same shot framed in several ways (a wider or tighter crop, another size, another grade). A plain
fingerprint of the whole picture sees those as different pictures. Here both pictures are reduced to a small grey
image (WIDTH pixels wide); one is then searched inside the other at a few zoom levels and positions, and the best
normalised correlation is the score: 1.0 is the same picture. On real TMDB backdrops a reframed copy of one shot scored
0.95 to 0.98 and the closest two different pictures 0.83, so SAME is 0.90.

numpy does the search in a few milliseconds per pair. Without numpy (a development machine) a pure Python search with
coarser steps gives the same answer for clear cases, slowly.
"""
from __future__ import annotations

import io

from PIL import Image

try:
    import numpy as np
except ImportError:          # pragma: no cover - the image has numpy
    np = None

WIDTH = 64
ZOOMS = (1.0, 1.06, 1.12, 1.2, 1.3, 1.42, 1.56, 1.64)       # real reframes of one shot needed up to 1.56
MARGIN = 2
SAME = 0.90


def prepare(source):
    """A small grey copy of a picture (a path or bytes), or None when it cannot be read."""
    try:
        handle = source if isinstance(source, str) else io.BytesIO(source)
        with Image.open(handle) as image:
            grey = image.convert("L")
            height = max(8, round(WIDTH * grey.height / max(1, grey.width)))
            return grey.resize((WIDTH, height), Image.BILINEAR)
    except Exception:
        return None


def similarity(left, right):
    """1.0 for the same picture; below SAME for different ones. 0 when either is missing."""
    if left is None or right is None:
        return 0.0
    return max(_inside(left, right), _inside(right, left))


def alike(left, right):
    return similarity(left, right) >= SAME


def _templates(small, big_width, big_height):
    for zoom in ZOOMS:
        width = round(big_width / zoom)
        height = round(width * small.height / small.width)
        if width <= 2 * MARGIN + 4 or height <= 2 * MARGIN + 4:
            continue
        if height - 2 * MARGIN > big_height or width - 2 * MARGIN > big_width:
            continue
        resized = small.resize((width, height), Image.BILINEAR)
        yield resized.crop((MARGIN, MARGIN, width - MARGIN, height - MARGIN))


def _inside(small, big):
    if np is not None:
        return _inside_numpy(small, big)
    return _inside_python(small, big)


def _inside_numpy(small, big):
    """Normalised correlation of each zoomed template at every position, by FFT (the sum of products) and running sums
    (each window's mean and spread): about a millisecond per pair."""
    best = -1.0
    field = np.asarray(big, dtype=np.float64)
    fh, fw = field.shape
    spectrum = np.fft.rfft2(field)
    total = np.pad(field, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    squares = np.pad(field * field, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    for template in _templates(small, fw, fh):
        tpl = np.asarray(template, dtype=np.float64)
        th, tw = tpl.shape
        tpl = (tpl - tpl.mean()) / (tpl.std() + 1e-6)
        padded = np.zeros((fh, fw))
        padded[:th, :tw] = tpl
        products = np.fft.irfft2(spectrum * np.conj(np.fft.rfft2(padded)), s=(fh, fw))[: fh - th + 1, : fw - tw + 1]
        count = th * tw
        sums = total[th:, tw:] - total[:-th, tw:] - total[th:, :-tw] + total[:-th, :-tw]
        sums2 = squares[th:, tw:] - squares[:-th, tw:] - squares[th:, :-tw] + squares[:-th, :-tw]
        spread = np.sqrt(np.maximum(sums2 / count - (sums / count) ** 2, 0)) + 1e-6
        scores = products / (count * spread)
        best = max(best, float(scores.max()))
    return best


def _inside_python(small, big):
    # Without numpy (tests on a development machine): the same search on copies half as large, so it stays quick.
    small = small.resize((max(8, small.width // 2), max(8, small.height // 2)), Image.BILINEAR)
    big = big.resize((max(8, big.width // 2), max(8, big.height // 2)), Image.BILINEAR)
    best = -1.0
    field = list(big.tobytes())
    fw, fh = big.size
    for template in _templates(small, fw, fh):
        tw, th = template.size
        tpl = list(template.tobytes())
        mean = sum(tpl) / len(tpl)
        spread = (sum((value - mean) ** 2 for value in tpl) / len(tpl)) ** 0.5 + 1e-6
        tpl = [(value - mean) / spread for value in tpl]
        rows, cols = fh - th + 1, fw - tw + 1
        step = 1 if rows * cols <= 120 else 2       # every position when there are few (a plain resize), else every second
        for top in sorted(set(range(0, rows, step)) | {rows // 2}):
            for left in sorted(set(range(0, cols, step)) | {cols // 2}):
                window = [field[(top + row) * fw + left + col] for row in range(th) for col in range(tw)]
                wmean = sum(window) / len(window)
                wspread = (sum((value - wmean) ** 2 for value in window) / len(window)) ** 0.5 + 1e-6
                score = sum(t * (w - wmean) for t, w in zip(tpl, window)) / (wspread * len(window))
                best = max(best, score)
    return best
