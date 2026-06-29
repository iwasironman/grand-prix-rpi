"""SQLite persistence for racers, heats and results."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import FINAL, QUALIFYING, Heat, LaneResult, Racer

SCHEMA = """
CREATE TABLE IF NOT EXISTS racers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    car_number  INTEGER NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS heats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    phase      TEXT    NOT NULL,
    seq        INTEGER NOT NULL,
    completed  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS heat_lanes (
    heat_id   INTEGER NOT NULL REFERENCES heats(id) ON DELETE CASCADE,
    lane      INTEGER NOT NULL,
    racer_id  INTEGER REFERENCES racers(id) ON DELETE CASCADE,
    PRIMARY KEY (heat_id, lane)
);

CREATE TABLE IF NOT EXISTS results (
    heat_id      INTEGER NOT NULL REFERENCES heats(id) ON DELETE CASCADE,
    lane         INTEGER NOT NULL,
    racer_id     INTEGER REFERENCES racers(id) ON DELETE CASCADE,
    time_seconds REAL,
    dnf          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (heat_id, lane)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ----- racers -----------------------------------------------------------
    def add_racer(self, name: str, car_number: int) -> Racer:
        cur = self.conn.execute(
            "INSERT INTO racers (name, car_number) VALUES (?, ?)",
            (name.strip(), car_number),
        )
        self.conn.commit()
        return Racer(id=cur.lastrowid, name=name.strip(), car_number=car_number)

    def delete_racer(self, racer_id: int) -> None:
        self.conn.execute("DELETE FROM racers WHERE id = ?", (racer_id,))
        self.conn.commit()

    def list_racers(self, active_only: bool = True) -> list[Racer]:
        q = "SELECT * FROM racers"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY car_number"
        return [
            Racer(r["id"], r["name"], r["car_number"], bool(r["active"]))
            for r in self.conn.execute(q)
        ]

    def racers_by_id(self) -> dict[int, Racer]:
        return {r.id: r for r in self.list_racers(active_only=False)}

    def replace_roster(self, entries: list[tuple[str, int]]) -> int:
        """Wipe the event + roster and load a fresh roster.

        Heats/results reference racer ids, so loading a new roster resets the
        event.  Duplicate car numbers in the import are skipped.  Returns the
        number of racers actually added.
        """
        self.reset_event()
        self.conn.execute("DELETE FROM racers")
        added = 0
        seen: set[int] = set()
        for name, num in entries:
            if num in seen:
                continue
            seen.add(num)
            self.conn.execute(
                "INSERT INTO racers (name, car_number) VALUES (?, ?)",
                (name.strip(), num),
            )
            added += 1
        self.conn.commit()
        return added

    def car_number_exists(self, car_number: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM racers WHERE car_number = ?", (car_number,)
        ).fetchone()
        return row is not None

    # ----- heats / schedule -------------------------------------------------
    def clear_phase(self, phase: str) -> None:
        ids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM heats WHERE phase = ?", (phase,))]
        for hid in ids:
            self.conn.execute("DELETE FROM heats WHERE id = ?", (hid,))
        self.conn.commit()

    def save_schedule(self, phase: str, rows: list[list[int | None]]) -> list[Heat]:
        self.clear_phase(phase)
        heats: list[Heat] = []
        for seq, lanes in enumerate(rows, start=1):
            cur = self.conn.execute(
                "INSERT INTO heats (phase, seq, completed) VALUES (?, ?, 0)",
                (phase, seq),
            )
            hid = cur.lastrowid
            for lane, rid in enumerate(lanes):
                self.conn.execute(
                    "INSERT INTO heat_lanes (heat_id, lane, racer_id) VALUES (?, ?, ?)",
                    (hid, lane, rid),
                )
            heats.append(Heat(id=hid, phase=phase, seq=seq, lanes=list(lanes)))
        self.conn.commit()
        return heats

    def get_heats(self, phase: str) -> list[Heat]:
        heats: list[Heat] = []
        for hrow in self.conn.execute(
            "SELECT * FROM heats WHERE phase = ? ORDER BY seq", (phase,)
        ):
            lane_rows = self.conn.execute(
                "SELECT lane, racer_id FROM heat_lanes WHERE heat_id = ? ORDER BY lane",
                (hrow["id"],),
            ).fetchall()
            lanes = [lr["racer_id"] for lr in lane_rows]
            heats.append(
                Heat(
                    id=hrow["id"],
                    phase=hrow["phase"],
                    seq=hrow["seq"],
                    lanes=lanes,
                    completed=bool(hrow["completed"]),
                )
            )
        return heats

    def next_pending_heat(self, phase: str) -> Heat | None:
        for h in self.get_heats(phase):
            if not h.completed:
                return h
        return None

    def phase_has_schedule(self, phase: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM heats WHERE phase = ? LIMIT 1", (phase,)
        ).fetchone()
        return row is not None

    # ----- results ----------------------------------------------------------
    def save_heat_results(self, heat_id: int, results: list[LaneResult]) -> None:
        for res in results:
            self.conn.execute(
                """INSERT INTO results (heat_id, lane, racer_id, time_seconds, dnf)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(heat_id, lane) DO UPDATE SET
                       time_seconds = excluded.time_seconds,
                       dnf = excluded.dnf""",
                (heat_id, res.lane, res.racer_id, res.time_s, int(res.dnf)),
            )
        self.conn.execute("UPDATE heats SET completed = 1 WHERE id = ?", (heat_id,))
        self.conn.commit()

    def get_results(self, phase: str) -> list[LaneResult]:
        rows = self.conn.execute(
            """SELECT r.heat_id, r.lane, r.racer_id, r.time_seconds, r.dnf
               FROM results r JOIN heats h ON h.id = r.heat_id
               WHERE h.phase = ? AND r.racer_id IS NOT NULL""",
            (phase,),
        )
        return [
            LaneResult(
                lane=row["lane"],
                racer_id=row["racer_id"],
                time_s=row["time_seconds"],
                dnf=bool(row["dnf"]),
                heat_id=row["heat_id"],
            )
            for row in rows
        ]

    # ----- settings ---------------------------------------------------------
    def get_setting(self, key: str, default: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, str(value)),
        )
        self.conn.commit()

    def reopen_heat(self, heat_id: int) -> None:
        """Discard a single heat's saved results and mark it pending again."""
        self.conn.execute("DELETE FROM results WHERE heat_id = ?", (heat_id,))
        self.conn.execute("UPDATE heats SET completed = 0 WHERE id = ?", (heat_id,))
        self.conn.commit()

    def reset_results(self, phase: str) -> None:
        self.conn.execute(
            """DELETE FROM results WHERE heat_id IN
               (SELECT id FROM heats WHERE phase = ?)""",
            (phase,),
        )
        self.conn.execute("UPDATE heats SET completed = 0 WHERE phase = ?", (phase,))
        self.conn.commit()

    # ----- full reset -------------------------------------------------------
    def reset_event(self) -> None:
        """Wipe heats + results but keep the roster of racers."""
        self.conn.execute("DELETE FROM results")
        self.conn.execute("DELETE FROM heats")
        self.conn.commit()
