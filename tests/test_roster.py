# Grand Prix RPi — pinewood derby race system.
# Copyright (C) 2026 Steven Southwell
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Roster save/load roundtrip + DB replace tests."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinewood.config import load_config  # noqa: E402
from pinewood.db import Database  # noqa: E402
from pinewood.roster import (  # noqa: E402
    list_rosters,
    load_roster,
    safe_filename,
    save_roster,
)


def _tmp_cfg():
    cfg = load_config()
    cfg.config_dir = Path(tempfile.mkdtemp())
    cfg.database = "t.db"
    return cfg


def test_safe_filename():
    assert safe_filename("Pack 42 / 2026!") == "Pack_42_2026"
    assert safe_filename("") == "roster"
    assert safe_filename("   ") == "roster"


def test_save_load_roundtrip():
    cfg = _tmp_cfg()
    db = Database(cfg.database_path)
    db.add_racer("Lightning", 101)
    db.add_racer("Thunder", 102)
    path = save_roster(cfg, "My Pack", db.list_racers())
    assert path.exists()
    assert path in list_rosters(cfg)

    entries = load_roster(path)
    assert entries == [("Lightning", 101), ("Thunder", 102)]
    db.close()


def test_replace_roster_resets_event_and_dedupes():
    cfg = _tmp_cfg()
    db = Database(cfg.database_path)
    db.add_racer("Old", 1)
    db.save_schedule("qualifying", [[1, None, None, None]])
    assert db.phase_has_schedule("qualifying")

    added = db.replace_roster([("A", 10), ("B", 11), ("Dup", 10)])
    assert added == 2                      # duplicate car #10 skipped
    nums = sorted(r.car_number for r in db.list_racers())
    assert nums == [10, 11]
    assert not db.phase_has_schedule("qualifying")   # event reset
    db.close()


def test_load_rejects_garbage():
    cfg = _tmp_cfg()
    bad = cfg.config_dir / "bad.json"
    bad.write_text('{"type": "something-else"}')
    try:
        load_roster(bad)
        assert False, "should have raised"
    except ValueError:
        pass
