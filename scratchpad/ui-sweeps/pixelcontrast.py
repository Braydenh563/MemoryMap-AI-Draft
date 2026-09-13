"""Contrast from the pixels a screenshot actually holds.

Why this is not done in the page, where every other sweep does it: on a
picture card every surface up the tree is translucent over the page's own
background art, so a composite walked up the DOM is a guess, and both ways of
guessing are wrong in a way that costs a session. `contrast.js` gives up at
the first `background-image` and reports nothing at all for these cards (it
prints "library: ok" having checked none of them). Compositing the fills down
to the body colour instead, which is what `imagecardfoot.js` first tried,
reads the card's own description at 3.24:1 where the pixels say 6.45:1,
because the art behind the glass is darker than the body colour under it.

So: the rendered PNG, one box per element, the extreme pixel inside the box
taken as the text and a corner pixel as the ground. `dark` takes the
brightest pixel as the text and `light` the darkest.

    python3 scratchpad/ui-sweeps/pixelcontrast.py shot.png dark \
        '[{"label":"fold","x":248,"y":432,"w":129,"h":32}]'
"""

import json
import sys
from collections import Counter

sys.path.insert(0, "scratchpad")

from pngpixel import read_png  # noqa: E402


def _lum(colour):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = colour[:3]
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def ratio(one, two):
    first, second = _lum(one), _lum(two)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def measure(path, theme, boxes):
    _width, _height, pixels = read_png(path)
    pick = max if theme == "dark" else min
    out = []
    for box in boxes:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        # The band the words run through, inset so a border or a rounded
        # corner cannot be sampled as either colour.
        band = [
            pixels[row][col][:3]
            for row in range(y + max(3, h // 4), y + h - max(3, h // 4))
            for col in range(x + 4, x + w - 4)
        ]
        if not band:
            continue
        # The ground is the commonest pixel in that band and the text is the
        # extreme one. A corner sample is what this did first and it is wrong
        # for a bare paragraph, where the first line's first letter starts at
        # the corner: it read the description's ground as its own type and
        # reported 1.00:1. Type never covers most of a text box, so the mode
        # is the ground on a padded control and on a paragraph alike.
        ground = Counter(tuple(p) for p in band).most_common(1)[0][0]
        text = pick(band, key=_lum)
        out.append(
            {
                "label": box["label"],
                "ground": list(ground),
                "text": list(text),
                "ratio": round(ratio(text, ground), 2),
            }
        )
    return out


if __name__ == "__main__":
    print(json.dumps(measure(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))))
