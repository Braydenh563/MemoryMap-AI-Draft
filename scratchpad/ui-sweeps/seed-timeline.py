"""Back-date the seeded notes so the Timeline has months to draw.

`POST /entries` stamps `created_at` with now, which is correct and should stay
that way -- so a timeline sweep that needs six months of history has to write
the dates itself. Spread the notes over the last ~200 days with a few dense
days (the same-day cluster is the case the line view is worst at), and leave
the newest handful on today so "Jump to today" has something to land on.

    python scratchpad/ui-sweeps/seed-timeline.py /tmp/mm-timeline/memorymap.db
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

db = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mm-timeline/memorymap.db"
con = sqlite3.connect(db)
rows = [r[0] for r in con.execute("SELECT id FROM entries ORDER BY id")]
now = datetime.now(timezone.utc)
# Offsets in days: a long tail back over six months, then two dense days near
# the top so a bucket with eight notes in it is on screen.
offsets = []
for i in range(len(rows)):
    if i < 6:
        offsets.append(0)          # today
    elif i < 12:
        offsets.append(3)          # one dense day this week
    else:
        offsets.append(int((i - 12) * 5.2) + 7)
for entry_id, days in zip(rows, offsets):
    when = now - timedelta(days=days, hours=(entry_id % 11), minutes=(entry_id * 7) % 60)
    con.execute(
        "UPDATE entries SET created_at = ? WHERE id = ?",
        (when.replace(tzinfo=None).isoformat(sep=" "), entry_id),
    )
con.commit()
span = con.execute("SELECT MIN(created_at), MAX(created_at), COUNT(*) FROM entries").fetchone()
print("entries", span[2], "from", span[0], "to", span[1])
con.close()
