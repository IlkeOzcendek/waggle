from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import json

from .auth import password_stamp
from .models import Device, DeviceCreate, EnrollmentStatus, HealthConfirmation, HealthConfirmationIn, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveSummary, HiveUpdate, Report, ReportIn


# A hive profile is only trained once it has heard the colony across enough separate
# days. The day count is what makes the baseline seasonal rather than a snapshot, so it
# cannot be satisfied by uploading many files at once. These are the single source of
# truth for both the progress bar and the gate that allows training.
REQUIRED_RECORDINGS = max(int(os.getenv("WAGGLE_ENROLLMENT_RECORDINGS", "42")), 1)
REQUIRED_DAYS = max(int(os.getenv("WAGGLE_ENROLLMENT_DAYS", "14")), 1)
REQUIRED_CONFIRMATIONS = max(int(os.getenv("WAGGLE_ENROLLMENT_CONFIRMATIONS", "4")), 1)

# Hive and device ids are derived from the highest one already stored, which is a read
# followed by a write with no lock in between: two hives added in the same moment compute
# the same id and one of them loses on the primary key. The id is the panel's to choose,
# not the caller's, so a collision means deriving it again rather than failing the request
# — which is what it used to do, as a bare 500 from a UNIQUE constraint.
ID_ALLOCATION_ATTEMPTS = 25
# The event schema names a hive with ^H[1-9][0-9]{0,2}$, so ids stop here.
MAX_HIVE_NUMBER = 999

# Only ever the seed for a brand new settings row, and the value an upgrading panel keeps.
# After that the stored pair is the single source of truth, because it is the one a person
# can correct from the panel. The default names the same place the default location name
# does, so an untouched panel is at least internally consistent.
DEFAULT_LATITUDE = float(os.getenv("WAGGLE_LAT", "39.7897"))
DEFAULT_LONGITUDE = float(os.getenv("WAGGLE_LON", "32.8065"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS hives (
    hive_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('healthy', 'queenless_suspected', 'uncertain')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    anomaly_severity REAL CHECK (anomaly_severity IS NULL OR (anomaly_severity >= 0 AND anomaly_severity <= 1)),
    consecutive_anomalies INTEGER NOT NULL DEFAULT 0,
    source_file TEXT,
    alindi TEXT NOT NULL,
    acknowledged_at TEXT,
    inspection_result TEXT CHECK (inspection_result IN ('issue_confirmed', 'no_issue_found', 'uncertain')),
    inspection_note TEXT,
    acknowledged_by TEXT,
    model TEXT,
    temperature_c REAL,
    humidity_percent INTEGER,
    wind_kmh REAL,
    weather_code INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_hive_time ON events(hive_id, timestamp DESC);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    recommendations TEXT NOT NULL,
    hive_ids TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'tr' CHECK (language IN ('tr', 'en')),
    generator TEXT NOT NULL DEFAULT 'manual',
    grounding_sources TEXT NOT NULL DEFAULT '[]',
    report_type TEXT NOT NULL DEFAULT 'weekly' CHECK (report_type IN ('event', 'daily', 'weekly')),
    event_id INTEGER,
    created_at TEXT NOT NULL,
    assessment TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    panel_name TEXT NOT NULL,
    location_name TEXT NOT NULL,
    alarm_threshold REAL NOT NULL,
    sound_enabled INTEGER NOT NULL,
    refresh_seconds INTEGER NOT NULL,
    onboarding_completed INTEGER NOT NULL DEFAULT 0,
    weather_enabled INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT 'tr' CHECK (language IN ('tr', 'en')),
    -- Where the apiary actually is. The name beside it is a label a person types; these
    -- are what the weather is asked about, and they were readable only from the
    -- environment. Renaming the apiary therefore relabelled another town's weather with
    -- it, and that reading was stamped onto every event recorded while it was on.
    latitude REAL NOT NULL DEFAULT 39.7897,
    longitude REAL NOT NULL DEFAULT 32.8065
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    hive_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('phone', 'sensor', 'folder', 'demo')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE INDEX IF NOT EXISTS idx_devices_hive ON devices(hive_id, active);
CREATE TABLE IF NOT EXISTS hive_profiles (
    hive_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('device_required', 'enrolling', 'ready', 'monitoring')),
    model_path TEXT,
    enrollment_started_at TEXT,
    ready_at TEXT,
    verification TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE TABLE IF NOT EXISTS enrollment_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    window_count INTEGER NOT NULL,
    healthy_confirmed INTEGER NOT NULL,
    feature_names TEXT,
    features TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id),
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);
CREATE INDEX IF NOT EXISTS idx_enrollment_hive_time ON enrollment_recordings(hive_id, recorded_at);
CREATE TABLE IF NOT EXISTS health_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hive_id TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK (evidence IN ('queen_seen', 'brood_healthy', 'hive_healthy', 'uncertain')),
    note TEXT,
    accepted_for_enrollment INTEGER NOT NULL,
    confirmed_by TEXT,
    FOREIGN KEY (hive_id) REFERENCES hives(hive_id)
);
CREATE INDEX IF NOT EXISTS idx_health_confirmation_hive_time ON health_confirmations(hive_id, confirmed_at DESC);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'worker')),
    created_at TEXT NOT NULL,
    recovery_salt TEXT,
    recovery_hash TEXT,
    recovery_created_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    demo_account INTEGER NOT NULL DEFAULT 0
);
"""

REQUIRED_BACKUP_COLUMNS = {
    "hives": {"hive_id", "name", "location", "active", "created_at"},
    "events": {"id", "hive_id", "timestamp", "event", "confidence", "alindi"},
    "reports": {"id", "period_start", "period_end", "summary", "recommendations", "hive_ids", "created_at"},
    "settings": {"id", "panel_name", "location_name", "alarm_threshold", "sound_enabled", "refresh_seconds"},
}


def _optional(row: sqlite3.Row, name: str):
    """A nullable column, tolerating a row written before the column existed."""
    return row[name] if name in row.keys() else None


def _decode_json(value):
    """Read a stored JSON column, tolerating a row written before it existed."""
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _decode_assessment(row: sqlite3.Row):
    """Read the stored assessment, tolerating rows written before the column existed."""
    if "assessment" not in row.keys() or not row["assessment"]:
        return None
    try:
        return json.loads(row["assessment"])
    except (TypeError, ValueError):
        return None


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        # SQLite enforces no foreign key at all unless it is asked to, per connection. The
        # schema has declared them since the first version and none of them were ever
        # checked: every cleanup was a DELETE somewhere in this file, and a path that
        # forgot one would have orphaned rows in silence.
        connection.execute("PRAGMA foreign_keys = ON")
        # A report run writes in a background thread while the panel is being read. Under
        # the rollback journal a writer locks readers out for the whole transaction; WAL
        # lets them proceed. The setting lives in the database file, so this is a no-op
        # after the first connection ever made to it.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._upgrade_events_columns(connection)
            confirmation_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(health_confirmations)")
            }
            if "confirmed_by" not in confirmation_columns:
                connection.execute(
                    "ALTER TABLE health_confirmations ADD COLUMN confirmed_by TEXT"
                )
            profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(hive_profiles)")}
            # Training refuses to publish a profile whose ONNX decisions differ from the
            # joblib ones, and then threw the comparison away. Keeping it is what turns
            # "this hive is monitored" into "this hive is monitored by a model whose
            # conversion was checked over this many windows".
            if "verification" not in profile_columns:
                connection.execute("ALTER TABLE hive_profiles ADD COLUMN verification TEXT")
            report_columns = {row["name"] for row in connection.execute("PRAGMA table_info(reports)")}
            # The model's own decision, kept so the panel can show what it concluded rather
            # than re-deriving a verdict from the raw events.
            if "assessment" not in report_columns:
                connection.execute("ALTER TABLE reports ADD COLUMN assessment TEXT")
            user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
            for column in ("recovery_salt", "recovery_hash", "recovery_created_at"):
                if column not in user_columns:
                    connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
            if "active" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
                )
            if "must_change_password" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
                )
            if "demo_account" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN demo_account INTEGER NOT NULL DEFAULT 0"
                )
            self._rebuild_users_table(connection)
            settings_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(settings)")
            }
            if "onboarding_completed" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0"
                )
            if "weather_enabled" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN weather_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "language" not in settings_columns:
                connection.execute(
                    "ALTER TABLE settings ADD COLUMN language TEXT NOT NULL DEFAULT 'tr'"
                )
            # A panel upgrading from a version that read the coordinates out of the
            # environment keeps exactly the pair it was already using, so the weather it
            # reports does not move the day it is upgraded.
            if "latitude" not in settings_columns:
                connection.execute(
                    f"ALTER TABLE settings ADD COLUMN latitude REAL NOT NULL DEFAULT {DEFAULT_LATITUDE}"
                )
            if "longitude" not in settings_columns:
                connection.execute(
                    f"ALTER TABLE settings ADD COLUMN longitude REAL NOT NULL DEFAULT {DEFAULT_LONGITUDE}"
                )
            report_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(reports)")
            }
            if "language" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN language TEXT NOT NULL DEFAULT 'tr'"
                )
            if "generator" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN generator TEXT NOT NULL DEFAULT 'manual'"
                )
            if "grounding_sources" not in report_columns:
                connection.execute(
                    "ALTER TABLE reports ADD COLUMN grounding_sources TEXT NOT NULL DEFAULT '[]'"
                )
            if "report_type" not in report_columns:
                connection.execute("ALTER TABLE reports ADD COLUMN report_type TEXT NOT NULL DEFAULT 'weekly'")
            if "event_id" not in report_columns:
                connection.execute("ALTER TABLE reports ADD COLUMN event_id INTEGER")
            enrollment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(enrollment_recordings)")
            }
            if "feature_names" not in enrollment_columns:
                connection.execute("ALTER TABLE enrollment_recordings ADD COLUMN feature_names TEXT")
            if "features" not in enrollment_columns:
                connection.execute("ALTER TABLE enrollment_recordings ADD COLUMN features TEXT")
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'events'"
            ).fetchone()["sql"]
            if "hive_id IN" in table_sql:
                self._migrate_events_table(connection)
                # The rebuild writes a table of its own, so the columns added since have to
                # be put back onto it rather than onto the one it replaced.
                self._upgrade_events_columns(connection)
            connection.execute(
                """INSERT OR IGNORE INTO settings
                (id, panel_name, location_name, alarm_threshold, sound_enabled, refresh_seconds)
                VALUES (1, 'Waggle', 'Gölbaşı Arılığı', 0.85, 1, 5)"""
            )
            connection.execute(
                "UPDATE settings SET location_name = 'Gölbaşı Arılığı' WHERE location_name IN ('Demo Kovanları', 'Kovanlık')"
            )

    @staticmethod
    def _rebuild_users_table(connection: sqlite3.Connection) -> None:
        """Bring an older users table up to the current definition.

        Two things need it, and SQLite can alter neither in place. The role CHECK was
        written when 'owner' was the only role. And the username column carried COLLATE
        NOCASE, which folds ASCII only: "İlke" and "ilke" never matched, while "Ali" and
        "ALi" did. Usernames are identifiers here, so they now compare exactly as typed.
        Existing rows are copied across unchanged — a NOCASE key could not have held two
        names that differ only by case, so nothing can collide on the way over.
        """
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        sql = definition["sql"] if definition else ""
        if definition is None or ("'worker'" in sql and "COLLATE NOCASE" not in sql):
            return
        connection.execute("ALTER TABLE users RENAME TO users_legacy")
        connection.execute(
            """CREATE TABLE users (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'worker')),
                created_at TEXT NOT NULL,
                recovery_salt TEXT,
                recovery_hash TEXT,
                recovery_created_at TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                demo_account INTEGER NOT NULL DEFAULT 0
            )"""
        )
        legacy_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users_legacy)")
        }
        shared = [
            column
            for column in (
                "username", "display_name", "password_salt", "password_hash", "role",
                "created_at", "recovery_salt", "recovery_hash", "recovery_created_at",
                "active", "must_change_password", "demo_account",
            )
            if column in legacy_columns
        ]
        names = ", ".join(shared)
        connection.execute(f"INSERT INTO users ({names}) SELECT {names} FROM users_legacy")
        connection.execute("DROP TABLE users_legacy")

    # Sample hives belong to a demo, not to every database that is ever opened. They used
    # to be inserted by initialize(), which meant a beekeeper's first launch showed three
    # hives they had never owned — and their profiles were marked "monitoring" against the
    # generic model, so the panel claimed a trained profile where no recording existed.
    # That is the opposite of what the enrollment thresholds promise.
    SAMPLE_HIVES = (
        ("H1", "Bahçe Kovanı", "Gölbaşı / Bahçe"),
        ("H2", "Orman Kovanı", "Gölbaşı / Orman kenarı"),
        ("H3", "Çayır Kovanı", "Gölbaşı / Çayır"),
    )

    def seed_sample_hives(self) -> None:
        """Add the three demo hives with ready profiles. Only a demo should call this."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO hives (hive_id, name, location, created_at) VALUES (?, ?, ?, ?)",
                [(hive_id, name, location, now) for hive_id, name, location in self.SAMPLE_HIVES],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO hive_profiles (hive_id, state, model_path, ready_at) VALUES (?, 'monitoring', ?, ?)",
                [(hive_id, "results/mendeley_isolation_monitor.onnx", now) for hive_id, *_ in self.SAMPLE_HIVES],
            )

    def has_users(self, include_demo: bool = False) -> bool:
        """Whether a real owner has been registered.

        The demo account is seeded automatically and must not count: a demo panel should
        still offer first-time setup so a genuine owner can be created alongside it.
        """
        query = "SELECT 1 FROM users LIMIT 1" if include_demo else (
            "SELECT 1 FROM users WHERE demo_account = 0 LIMIT 1"
        )
        with self.connect() as connection:
            row = connection.execute(query).fetchone()
        return row is not None

    def ensure_demo_owner(
        self, username: str, display_name: str, password_salt: str, password_hash: str
    ) -> None:
        """Give the demo account a real row so it behaves like any other owner.

        Without one it cannot hold a password or a recovery code, and every account
        feature has to be special-cased into invisibility for exactly the account someone
        would be demonstrating with. The row is flagged so it can never sign in once demo
        mode is switched off, and so it never blocks first-time setup.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                return
            connection.execute(
                """INSERT INTO users
                (username, display_name, password_salt, password_hash, role, created_at,
                 active, must_change_password, demo_account)
                VALUES (?, ?, ?, ?, 'owner', ?, 1, 0, 1)""",
                (
                    username,
                    display_name,
                    password_salt,
                    password_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def create_owner(
        self,
        display_name: str,
        username: str,
        password_salt: str,
        password_hash: str,
    ) -> None:
        """Create the single first owner atomically; public registration stays closed."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # The seeded demo owner is not a real owner, so it must not close setup.
            if connection.execute(
                "SELECT 1 FROM users WHERE demo_account = 0 LIMIT 1"
            ).fetchone():
                raise ValueError("Sistem sahibi hesabı zaten oluşturulmuş")
            if connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username.strip(),)
            ).fetchone():
                raise ValueError("Bu kullanıcı adı zaten kullanılıyor")
            connection.execute(
                """INSERT INTO users
                (username, display_name, password_salt, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, 'owner', ?)""",
                (
                    username.strip(),
                    display_name.strip(),
                    password_salt,
                    password_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def add_worker(
        self,
        display_name: str,
        username: str,
        password_salt: str,
        password_hash: str,
    ) -> None:
        """Add a field worker account.

        The owner types the first password and reads it out, because an offline panel has
        no way to send an invitation. That password is therefore known to two people, so
        the account is flagged to change it before it can do anything else — otherwise
        "who acknowledged this alarm" would not identify anyone.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
            if existing:
                raise ValueError("Bu kullanıcı adı zaten kullanılıyor")
            connection.execute(
                """INSERT INTO users
                (username, display_name, password_salt, password_hash, role, created_at,
                 active, must_change_password)
                VALUES (?, ?, ?, ?, 'worker', ?, 1, 1)""",
                (
                    username.strip(),
                    display_name.strip(),
                    password_salt,
                    password_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def users(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT username, display_name, role, created_at, active,
                          must_change_password, recovery_hash, demo_account
                   FROM users ORDER BY role, created_at"""
            ).fetchall()
        return [
            {
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "created_at": datetime.fromisoformat(row["created_at"]),
                "active": bool(row["active"]),
                "must_change_password": bool(row["must_change_password"]),
                "has_recovery_code": bool(row["recovery_hash"]),
                "demo_account": bool(row["demo_account"]),
            }
            for row in rows
        ]

    def user_account(self, username: str) -> dict | None:
        """Role and standing of one account, or None when it has no row of its own."""
        with self.connect() as connection:
            row = connection.execute(
                """SELECT username, display_name, role, active, must_change_password,
                          demo_account, password_hash
                   FROM users WHERE username = ?""",
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        return {
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "active": bool(row["active"]),
            "must_change_password": bool(row["must_change_password"]),
            "demo_account": bool(row["demo_account"]),
            # The stamp, not the hash: this dictionary is handed to request handlers.
            "password_stamp": password_stamp(row["password_hash"]),
        }

    def set_user_active(self, username: str, active: bool) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET active = ? WHERE username = ? AND role = 'worker'",
                (int(active), username.strip()),
            )
        return cursor.rowcount > 0

    def set_user_password(
        self,
        username: str,
        password_salt: str,
        password_hash: str,
        must_change: bool = False,
    ) -> bool:
        """Set a password. `must_change` marks it as a temporary one the owner issued.

        Choosing a password also clears the demo flag: the account was only ever marked
        because it was created with a well-known one, and that is no longer true.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE users SET password_salt = ?, password_hash = ?,
                       must_change_password = ?, demo_account = 0
                WHERE username = ?""",
                (password_salt, password_hash, int(must_change), username.strip()),
            )
        return cursor.rowcount > 0

    def set_recovery_code(self, username: str, code_salt: str, code_hash: str) -> str | None:
        """Store the hash of a fresh recovery code. The code itself is never persisted."""
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE users
                SET recovery_salt = ?, recovery_hash = ?, recovery_created_at = ?
                WHERE username = ?""",
                (code_salt, code_hash, created_at.isoformat(), username.strip()),
            )
        return created_at.isoformat() if cursor.rowcount else None

    def recovery_code_state(self, username: str) -> tuple[bool, datetime | None]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT recovery_hash, recovery_created_at FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if row is None or not row["recovery_hash"]:
            return False, None
        created = row["recovery_created_at"]
        return True, datetime.fromisoformat(created) if created else None

    def recovery_credentials(self, username: str) -> tuple[str, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT recovery_salt, recovery_hash FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if row is None or not row["recovery_hash"] or not row["recovery_salt"]:
            return None
        return row["recovery_salt"], row["recovery_hash"]

    def consume_recovery_code(
        self, username: str, password_salt: str, password_hash: str
    ) -> bool:
        """Set a new password and burn the recovery code in one transaction.

        The code is single use: a slip of paper that leaked once must not stay a
        permanent way back into the panel.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE users
                SET password_salt = ?, password_hash = ?, must_change_password = 0,
                    demo_account = 0,
                    recovery_salt = NULL, recovery_hash = NULL, recovery_created_at = NULL
                WHERE username = ? AND recovery_hash IS NOT NULL""",
                (password_salt, password_hash, username.strip()),
            )
        return cursor.rowcount > 0

    def user_credentials(self, username: str) -> tuple[str, str, str] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT display_name, password_salt, password_hash
                FROM users WHERE username = ?""",
                (username.strip(),),
            ).fetchone()
        if row is None:
            return None
        return row["display_name"], row["password_salt"], row["password_hash"]

    @staticmethod
    def _upgrade_events_columns(connection: sqlite3.Connection) -> None:
        """Bring an events table up to the current column set.

        It runs in more than one place because more than one thing can leave the table
        behind: a database from an older version, the legacy rebuild below, and a restored
        backup taken before a column existed. Keeping the list in one method is what stops
        those paths from drifting apart — they already had, and the symptom was an insert
        failing on a column the schema said was there.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
        additions = {
            "acknowledged_at": "TEXT",
            "inspection_result": "TEXT",
            "inspection_note": "TEXT",
            "consecutive_anomalies": "INTEGER NOT NULL DEFAULT 0",
            "source_file": "TEXT",
            # Who inspected the hive is part of the audit trail behind an AI decision, and
            # it can never be filled in retroactively — rows written before this column
            # existed stay anonymous.
            "acknowledged_by": "TEXT",
            # Which acoustic model decided this event. The ONNX profile is the first link
            # in the chain a report rests on, and without it stored per event a report can
            # name the language model that phrased it but not the one that measured it.
            "model": "TEXT",
            # How far outside the profile the anomalous windows sat. It stays null on rows
            # written before the ONNX graph's score output was read, so a report has to
            # treat its absence as "not measured" rather than as zero.
            "anomaly_severity": "REAL",
            # Conditions at the moment of the recording, stamped only while online weather
            # is on. They stay null on every row written with it off and on every row that
            # predates these columns, because the weather of a past recording cannot be
            # recovered without asking an external service about a place and a time.
            "temperature_c": "REAL",
            "humidity_percent": "INTEGER",
            "wind_kmh": "REAL",
            "weather_code": "INTEGER",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE events ADD COLUMN {name} {declaration}")

    @staticmethod
    def _migrate_events_table(connection: sqlite3.Connection) -> None:
        connection.execute("DROP INDEX IF EXISTS idx_events_hive_time")
        connection.execute("ALTER TABLE events RENAME TO events_legacy")
        connection.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hive_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL CHECK (event IN ('healthy', 'queenless_suspected', 'uncertain')),
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                consecutive_anomalies INTEGER NOT NULL DEFAULT 0,
                source_file TEXT,
                alindi TEXT NOT NULL,
                acknowledged_at TEXT,
                inspection_result TEXT CHECK (inspection_result IN ('issue_confirmed', 'no_issue_found', 'uncertain')),
                inspection_note TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO events
            (id, hive_id, timestamp, event, confidence, consecutive_anomalies,
             source_file, alindi, acknowledged_at, inspection_result, inspection_note)
            SELECT id, hive_id, timestamp, event, confidence, 0, NULL, alindi,
                   acknowledged_at, NULL, NULL
            FROM events_legacy"""
        )
        connection.execute("DROP TABLE events_legacy")
        connection.execute(
            "CREATE INDEX idx_events_hive_time ON events(hive_id, timestamp DESC)"
        )

    def hives(self, include_inactive: bool = False) -> list[Hive]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hives WHERE active = 1 OR ? = 1 ORDER BY active DESC, CAST(SUBSTR(hive_id, 2) AS INTEGER)",
                (int(include_inactive),),
            ).fetchall()
        return [self._hive(row) for row in rows]

    def add_hive(self, hive: HiveCreate) -> Hive:
        created_at = datetime.now(timezone.utc)
        name = hive.name.strip()
        location = hive.location.strip() if hive.location else None
        last_collision: sqlite3.IntegrityError | None = None
        for _ in range(ID_ALLOCATION_ATTEMPTS):
            try:
                with self.connect() as connection:
                    # Profiles outlive a deleted hive in older databases, so the next id is
                    # taken from both tables; reusing one would collide on the profile
                    # primary key.
                    rows = connection.execute(
                        "SELECT hive_id FROM hives UNION SELECT hive_id FROM hive_profiles"
                    ).fetchall()
                    numbers = [int(row["hive_id"][1:]) for row in rows if row["hive_id"][1:].isdigit()]
                    number = max(numbers, default=0) + 1
                    # An event names its hive with the same pattern the panel hands out, and
                    # that pattern stops at H999. Past it a hive could be created but never
                    # receive a recording, so the refusal belongs here rather than three
                    # screens later on the first upload.
                    if number > MAX_HIVE_NUMBER:
                        raise ValueError(f"Kovan sayısı üst sınıra ulaştı (H{MAX_HIVE_NUMBER})")
                    hive_id = f"H{number}"
                    connection.execute(
                        "INSERT INTO hives (hive_id, name, location, active, created_at) VALUES (?, ?, ?, 1, ?)",
                        (hive_id, name, location, created_at.isoformat()),
                    )
                    connection.execute(
                        "INSERT INTO hive_profiles (hive_id, state) VALUES (?, 'device_required')",
                        (hive_id,),
                    )
                return Hive(hive_id=hive_id, name=name, location=location, active=True, created_at=created_at)
            except sqlite3.IntegrityError as collision:
                last_collision = collision
        raise last_collision

    def devices(self, hive_id: str) -> list[Device]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices WHERE hive_id = ? ORDER BY active DESC, created_at",
                (hive_id,),
            ).fetchall()
        return [self._device(row) for row in rows]

    def add_device(self, hive_id: str, device: DeviceCreate) -> Device:
        created_at = datetime.now(timezone.utc)
        name = device.name.strip()
        last_collision: sqlite3.IntegrityError | None = None
        for _ in range(ID_ALLOCATION_ATTEMPTS):
            try:
                with self.connect() as connection:
                    profile = connection.execute(
                        "SELECT state FROM hive_profiles WHERE hive_id = ?", (hive_id,)
                    ).fetchone()
                    active_devices = connection.execute(
                        "SELECT COUNT(*) FROM devices WHERE hive_id = ? AND active = 1", (hive_id,)
                    ).fetchone()[0]
                    if profile and profile["state"] == "enrolling" and active_devices:
                        raise ValueError("Öğrenme sırasında tek bir mikrofon kullanılmalıdır")
                    count = connection.execute(
                        "SELECT COUNT(*) FROM devices WHERE hive_id = ?", (hive_id,)
                    ).fetchone()[0]
                    device_id = f"{hive_id}-D{count + 1}"
                    connection.execute(
                        "INSERT INTO devices (device_id, hive_id, name, kind, created_at) VALUES (?, ?, ?, ?, ?)",
                        (device_id, hive_id, name, device.kind, created_at.isoformat()),
                    )
                    connection.execute(
                        "UPDATE hive_profiles SET state = 'enrolling', enrollment_started_at = COALESCE(enrollment_started_at, ?) WHERE hive_id = ? AND state = 'device_required'",
                        (created_at.isoformat(), hive_id),
                    )
                return Device(device_id=device_id, hive_id=hive_id, name=name, kind=device.kind, created_at=created_at)
            except sqlite3.IntegrityError as collision:
                last_collision = collision
        raise last_collision

    def enrollment_status(self, hive_id: str) -> EnrollmentStatus:
        with self.connect() as connection:
            profile = connection.execute(
                "SELECT state, model_path FROM hive_profiles WHERE hive_id = ?", (hive_id,)
            ).fetchone()
            counts = connection.execute(
                "SELECT COUNT(*) AS recordings, COUNT(DISTINCT SUBSTR(recorded_at, 1, 10)) AS days FROM enrollment_recordings WHERE hive_id = ? AND healthy_confirmed = 1",
                (hive_id,),
            ).fetchone()
            confirmations = connection.execute(
                "SELECT COALESCE(SUM(accepted_for_enrollment), 0) AS accepted, MAX(CASE WHEN accepted_for_enrollment = 1 THEN confirmed_at END) AS last_at FROM health_confirmations WHERE hive_id = ?",
                (hive_id,),
            ).fetchone()
        state = profile["state"] if profile else "device_required"
        recordings, days = int(counts["recordings"]), int(counts["days"])
        confirmation_count = int(confirmations["accepted"])
        last_confirmation = datetime.fromisoformat(confirmations["last_at"]) if confirmations["last_at"] else None
        confirmation_due = last_confirmation is None or datetime.now(timezone.utc) - last_confirmation > timedelta(days=4)
        progress = min(100, round(
            40 * min(recordings / REQUIRED_RECORDINGS, 1)
            + 40 * min(days / REQUIRED_DAYS, 1)
            + 20 * min(confirmation_count / REQUIRED_CONFIRMATIONS, 1)
        ))
        return EnrollmentStatus(
            hive_id=hive_id, state=state, recording_count=recordings,
            recording_days=days, progress_percent=100 if state in {"ready", "monitoring"} else progress,
            can_monitor=state in {"ready", "monitoring"},
            required_recordings=REQUIRED_RECORDINGS,
            required_days=REQUIRED_DAYS,
            required_confirmations=REQUIRED_CONFIRMATIONS,
            ready_to_train=recordings >= REQUIRED_RECORDINGS and days >= REQUIRED_DAYS and confirmation_count >= REQUIRED_CONFIRMATIONS and state == "enrolling",
            model_path=profile["model_path"] if profile else None,
            confirmation_count=confirmation_count,
            confirmation_due=confirmation_due and state == "enrolling",
            last_confirmation_at=last_confirmation,
        )

    def add_health_confirmation(
        self,
        hive_id: str,
        confirmation: HealthConfirmationIn,
        confirmed_by: str | None = None,
    ) -> HealthConfirmation:
        confirmed_at = datetime.now(timezone.utc)
        accepted = confirmation.evidence != "uncertain"
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO health_confirmations (hive_id, confirmed_at, evidence, note, accepted_for_enrollment, confirmed_by) VALUES (?, ?, ?, ?, ?, ?)",
                (hive_id, confirmed_at.isoformat(), confirmation.evidence, confirmation.note.strip() if confirmation.note else None, int(accepted), confirmed_by),
            )
        return HealthConfirmation(
            id=cursor.lastrowid, hive_id=hive_id, confirmed_at=confirmed_at,
            evidence=confirmation.evidence, note=confirmation.note,
            accepted_for_enrollment=accepted, confirmed_by=confirmed_by,
        )

    def add_enrollment_recording(self, hive_id: str, device_id: str, filename: str, values, feature_names) -> EnrollmentStatus:
        now = datetime.now(timezone.utc)
        with self.connect() as connection:
            device = connection.execute(
                "SELECT 1 FROM devices WHERE device_id = ? AND hive_id = ? AND active = 1",
                (device_id, hive_id),
            ).fetchone()
            if device is None:
                raise ValueError("Cihaz bu kovana bağlı değil")
            connection.execute(
                "INSERT INTO enrollment_recordings (hive_id, device_id, recorded_at, filename, window_count, healthy_confirmed, feature_names, features) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (hive_id, device_id, now.isoformat(), filename, len(values), json.dumps(list(feature_names)), json.dumps(values.tolist() if hasattr(values, "tolist") else values)),
            )
            connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?", (now.isoformat(), device_id)
            )
        return self.enrollment_status(hive_id)

    def health_confirmations(self, limit: int = 1_000_000) -> list[dict]:
        """Every field check, with the account that vouched for it.

        These are what unlock more training data, so they belong in an export as much as
        the events do: an assessment nobody can audit is just an opinion.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, hive_id, confirmed_at, evidence, note, accepted_for_enrollment,
                          confirmed_by
                   FROM health_confirmations ORDER BY confirmed_at DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "hive_id": row["hive_id"],
                "confirmed_at": row["confirmed_at"],
                "evidence": row["evidence"],
                "note": row["note"],
                "accepted_for_enrollment": bool(row["accepted_for_enrollment"]),
                "confirmed_by": row["confirmed_by"],
            }
            for row in rows
        ]

    def enrollment_recordings(self, limit: int = 1_000_000) -> list[dict]:
        """One row per enrollment recording, without the extracted feature vectors.

        This is the evidence behind the enrollment gate: how many recordings a hive has,
        spread over how many distinct calendar days, and which were confirmed healthy. The
        panel shows the resulting percentage; nothing let anyone download what it rests on.
        The features themselves are left out because they are a long numeric blob nobody
        reads in a spreadsheet, and the audio they came from no longer exists.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT r.id, r.hive_id, h.name AS hive_name, r.device_id, r.recorded_at,
                          r.filename, r.window_count, r.healthy_confirmed
                   FROM enrollment_recordings r
                   LEFT JOIN hives h ON h.hive_id = r.hive_id
                   ORDER BY r.recorded_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "hive_id": row["hive_id"],
                "hive_name": row["hive_name"] or "Bilinmeyen kovan",
                "device_id": row["device_id"],
                "recorded_at": row["recorded_at"],
                # The day is what the 14-day threshold counts, so it is spelled out rather
                # than left for the reader to slice out of the timestamp.
                "recorded_day": (row["recorded_at"] or "")[:10],
                "filename": row["filename"],
                "window_count": row["window_count"],
                "healthy_confirmed": bool(row["healthy_confirmed"]),
            }
            for row in rows
        ]

    def all_devices(self) -> list[dict]:
        """Every device on every hive. Which microphone produced a recording is part of
        reading that recording, and it was not exportable anywhere."""
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.device_id, d.hive_id, h.name AS hive_name, d.name, d.kind,
                          d.active, d.created_at, d.last_seen_at
                   FROM devices d LEFT JOIN hives h ON h.hive_id = d.hive_id
                   ORDER BY d.hive_id, d.created_at""",
            ).fetchall()
        return [
            {
                "device_id": row["device_id"],
                "hive_id": row["hive_id"],
                "hive_name": row["hive_name"] or "Bilinmeyen kovan",
                "name": row["name"],
                "kind": row["kind"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in rows
        ]

    def enrollment_features(self, hive_id: str):
        import numpy as np

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT feature_names, features FROM enrollment_recordings WHERE hive_id = ? AND healthy_confirmed = 1 AND features IS NOT NULL ORDER BY recorded_at, id",
                (hive_id,),
            ).fetchall()
        if not rows:
            raise ValueError("Öğrenme özelliği bulunamadı")
        schemas = [json.loads(row["feature_names"]) for row in rows]
        if any(schema != schemas[0] for schema in schemas[1:]):
            raise ValueError("Özellik şeması kayıtlar arasında değişmiş")
        matrices = [np.asarray(json.loads(row["features"]), dtype=np.float64) for row in rows]
        return np.concatenate(matrices), schemas[0]

    def activate_profile(self, hive_id: str, model_path: str, verification: dict | None = None) -> EnrollmentStatus:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """UPDATE hive_profiles
                SET state = 'monitoring', model_path = ?, ready_at = ?, verification = ?
                WHERE hive_id = ?""",
                (model_path, now, json.dumps(verification, ensure_ascii=False) if verification else None, hive_id),
            )
        return self.enrollment_status(hive_id)

    def monitoring_profiles(self) -> list[dict]:
        """The hives being watched by their own trained profile.

        The panel claims a hive is monitored; whether the file behind that claim is still
        on disk, and whether its ONNX conversion was ever checked against the joblib model
        it came from, are different questions and nothing was asking either.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT hive_id, model_path, verification FROM hive_profiles
                WHERE state = 'monitoring' AND model_path IS NOT NULL"""
            ).fetchall()
        return [
            {
                "hive_id": row["hive_id"],
                "model_path": row["model_path"],
                "verification": _decode_json(row["verification"] if "verification" in row.keys() else None),
            }
            for row in rows
        ]

    def touch_device(self, device_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (datetime.now(timezone.utc).isoformat(), device_id),
            )

    def has_hive(self, hive_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM hives WHERE hive_id = ? AND active = 1", (hive_id,)
            ).fetchone() is not None

    def update_hive(self, hive_id: str, hive: HiveUpdate) -> Hive | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE hives SET name = ?, location = ? WHERE hive_id = ?",
                (hive.name.strip(), hive.location.strip() if hive.location else None, hive_id),
            )
            row = connection.execute("SELECT * FROM hives WHERE hive_id = ?", (hive_id,)).fetchone()
        return self._hive(row) if row else None

    def set_hive_active(self, hive_id: str, active: bool) -> Hive | None:
        with self.connect() as connection:
            connection.execute("UPDATE hives SET active = ? WHERE hive_id = ?", (int(active), hive_id))
            row = connection.execute("SELECT * FROM hives WHERE hive_id = ?", (hive_id,)).fetchone()
        return self._hive(row) if row else None

    def hive_footprint(self, hive_id: str) -> dict | None:
        """What a permanent delete would remove, so the panel can say it before asking."""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM hives WHERE hive_id = ?", (hive_id,)).fetchone()
            if row is None:
                return None
            events = connection.execute("SELECT COUNT(*) FROM events WHERE hive_id = ?", (hive_id,)).fetchone()[0]
            devices = connection.execute("SELECT COUNT(*) FROM devices WHERE hive_id = ?", (hive_id,)).fetchone()[0]
        return {"hive": self._hive(row), "events": events, "devices": devices}

    def delete_hive(self, hive_id: str) -> dict | None:
        """Remove a hive and the rows that belong to it.

        Reports are left untouched: they are period documents that may cover several
        hives, and deleting one hive must not rewrite history that was already issued.
        """
        footprint = self.hive_footprint(hive_id)
        if footprint is None:
            return None
        with self.connect() as connection:
            # The trained profile is a file on disk that the row only points at, so the
            # path is read before the row goes: deleting the row first would leave the
            # model behind with nothing left to say whose it was.
            profile = connection.execute(
                "SELECT model_path FROM hive_profiles WHERE hive_id = ?", (hive_id,)
            ).fetchone()
            model_path = (profile["model_path"] or "").strip() if profile else ""
            connection.execute("DELETE FROM events WHERE hive_id = ?", (hive_id,))
            # Enrollment recordings name the device that made them, so they have to go
            # before it does. The order used to be the other way round, and nothing said
            # so while foreign keys were unenforced: the delete simply left every
            # recording pointing at a device that no longer existed. Turning enforcement
            # on turned that silence into the error it always was.
            connection.execute("DELETE FROM enrollment_recordings WHERE hive_id = ?", (hive_id,))
            connection.execute("DELETE FROM devices WHERE hive_id = ?", (hive_id,))
            connection.execute("DELETE FROM health_confirmations WHERE hive_id = ?", (hive_id,))
            # The learning profile is keyed by hive_id too. Leaving it behind orphans a
            # primary key, and the next hive that reuses the id fails to insert its profile.
            connection.execute("DELETE FROM hive_profiles WHERE hive_id = ?", (hive_id,))
            connection.execute("DELETE FROM hives WHERE hive_id = ?", (hive_id,))
        return {"events": footprint["events"], "devices": footprint["devices"], "model_path": model_path}

    def backup_to(self, destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination_path)
        try:
            with self.connect() as source:
                source.backup(target)
        finally:
            target.close()
        return destination_path

    @staticmethod
    def validate_backup(source: str | Path) -> None:
        connection = sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("Yedek dosyasının SQLite bütünlük kontrolü başarısız")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for table, required_columns in REQUIRED_BACKUP_COLUMNS.items():
                if table not in tables:
                    raise ValueError(f"Yedekte gerekli {table} tablosu bulunamadı")
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if not required_columns.issubset(columns):
                    raise ValueError(f"Yedekteki {table} tablosu Waggle ile uyumlu değil")
        except sqlite3.DatabaseError as exc:
            raise ValueError("Dosya geçerli bir SQLite yedeği değil") from exc
        finally:
            connection.close()

    def restore_from(self, source: str | Path) -> None:
        self.validate_backup(source)
        backup = sqlite3.connect(str(source))
        try:
            with self.connect() as destination:
                backup.backup(destination)
        finally:
            backup.close()
        # The copy replaces the live schema with the backup's, which may predate a column
        # the panel now writes. Without this the restore looks successful and the next
        # recording fails on a column the code is certain exists.
        self.initialize()

    def diagnostics(self) -> dict[str, object]:
        """Return lightweight, read-only database and integration metrics."""
        with self.connect() as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("hives", "events", "reports")
            }
            last_event = connection.execute("SELECT MAX(alindi) FROM events").fetchone()[0]
            last_report = connection.execute("SELECT MAX(created_at) FROM reports").fetchone()[0]
        return {
            "integrity": integrity,
            "counts": counts,
            "last_event_at": datetime.fromisoformat(last_event) if last_event else None,
            "last_report_at": datetime.fromisoformat(last_report) if last_report else None,
        }

    def add(self, event: HiveEventIn) -> HiveEvent:
        received_at = datetime.now(timezone.utc)
        legacy_event = {
            "NORMAL": "healthy",
            "WATCH": "uncertain",
            "ALARM": "queenless_suspected",
        }[event.status]
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO events
                (hive_id, timestamp, event, confidence, anomaly_severity, consecutive_anomalies,
                 source_file, alindi, model, temperature_c, humidity_percent, wind_kmh, weather_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.hive_id,
                    event.timestamp.isoformat(),
                    legacy_event,
                    event.anomaly_fraction,
                    event.anomaly_severity,
                    event.consecutive_anomalies,
                    event.source_file,
                    received_at.isoformat(),
                    event.model,
                    event.temperature_c,
                    event.humidity_percent,
                    event.wind_kmh,
                    event.weather_code,
                ),
            )
            event_id = cursor.lastrowid
        return HiveEvent(id=event_id, alindi=received_at, **event.model_dump())

    def event(self, event_id: int) -> HiveEvent | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event(row) if row else None

    def recent(self, limit: int = 50) -> list[HiveEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY timestamp DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._event(row) for row in rows]

    def latest_event(self, hive_id: str) -> HiveEvent | None:
        """This hive's most recent event, however long ago the last one was.

        The run of consecutive anomalies behind WATCH and ALARM is carried forward from
        it, and it used to be looked up by scanning the newest few hundred events across
        every hive. A quiet hive in a busy apiary fell out of that window, its run silently
        restarted at zero, and the escalation the whole system rests on began again — the
        one lookup where "recent enough" is not the question being asked.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE hive_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                (hive_id,),
            ).fetchone()
        return self._event(row) if row else None

    def acknowledge(
        self,
        event_id: int,
        inspection_result: str | None = None,
        inspection_note: str | None = None,
        acknowledged_by: str | None = None,
    ) -> HiveEvent | None:
        acknowledged_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            connection.execute(
                """UPDATE events
                   SET acknowledged_at = ?, inspection_result = ?, inspection_note = ?,
                       acknowledged_by = ?
                   WHERE id = ? AND acknowledged_at IS NULL""",
                (
                    acknowledged_at.isoformat(),
                    inspection_result,
                    inspection_note,
                    acknowledged_by,
                    event_id,
                ),
            )
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event(row) if row else None

    def summaries(self) -> list[HiveSummary]:
        summaries: list[HiveSummary] = []
        with self.connect() as connection:
            hives = connection.execute(
                "SELECT * FROM hives WHERE active = 1 ORDER BY CAST(SUBSTR(hive_id, 2) AS INTEGER)"
            ).fetchall()
            for hive in hives:
                hive_id = hive["hive_id"]
                row = connection.execute(
                    "SELECT * FROM events WHERE hive_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (hive_id,),
                ).fetchone()
                if row is None:
                    summaries.append(
                        HiveSummary(
                            hive_id=hive_id,
                            name=hive["name"],
                            location=hive["location"],
                            durum="veri_yok",
                            last_status=None,
                            anomaly_fraction=None,
                            timestamp=None,
                        )
                    )
                    continue
                event = self._event(row)
                status = {
                    "NORMAL": "normal",
                    "WATCH": "uyari",
                    "ALARM": "kritik",
                }[event.status]
                summaries.append(
                    HiveSummary(
                        hive_id=hive_id,
                        name=hive["name"],
                        location=hive["location"],
                        durum=status,
                        last_status=event.status,
                        anomaly_fraction=event.anomaly_fraction,
                        timestamp=event.timestamp,
                    )
                )
        return summaries

    def settings(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return {
            "panel_name": row["panel_name"],
            "location_name": row["location_name"],
            "alarm_threshold": row["alarm_threshold"],
            "sound_enabled": bool(row["sound_enabled"]),
            "refresh_seconds": row["refresh_seconds"],
            "onboarding_completed": bool(row["onboarding_completed"]),
            "weather_enabled": bool(row["weather_enabled"]),
            "language": row["language"],
            "latitude": _optional(row, "latitude") if _optional(row, "latitude") is not None else DEFAULT_LATITUDE,
            "longitude": _optional(row, "longitude") if _optional(row, "longitude") is not None else DEFAULT_LONGITUDE,
        }

    def update_settings(self, values: dict[str, object]) -> dict[str, object]:
        current = self.settings()
        with self.connect() as connection:
            connection.execute(
                """UPDATE settings SET panel_name = ?, location_name = ?, alarm_threshold = ?,
                sound_enabled = ?, refresh_seconds = ?, onboarding_completed = ?,
                weather_enabled = ?, language = ?, latitude = ?, longitude = ? WHERE id = 1""",
                (
                    values["panel_name"], values["location_name"], values["alarm_threshold"],
                    int(bool(values["sound_enabled"])), values["refresh_seconds"],
                    int(bool(values["onboarding_completed"])),
                    int(bool(values["weather_enabled"])),
                    values.get("language", "tr"),
                    # A caller that does not mention the coordinates keeps the stored pair,
                    # rather than being read as asking for the defaults back.
                    float(values.get("latitude", current["latitude"])),
                    float(values.get("longitude", current["longitude"])),
                ),
            )
        return self.settings()

    def add_report(self, report: ReportIn) -> Report:
        created_at = datetime.now(timezone.utc)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reports
                (period_start, period_end, summary, recommendations, hive_ids,
                 language, generator, grounding_sources, report_type, event_id, created_at,
                 assessment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.summary,
                    json.dumps(report.recommendations, ensure_ascii=False),
                    json.dumps(report.hive_ids),
                    report.language,
                    report.generator,
                    json.dumps(report.grounding_sources),
                    report.report_type,
                    report.event_id,
                    created_at.isoformat(),
                    json.dumps(report.assessment.model_dump(), ensure_ascii=False) if report.assessment else None,
                ),
            )
            report_id = cursor.lastrowid
        return Report(id=report_id, created_at=created_at, **report.model_dump())

    def reports(self, limit: int = 10) -> list[Report]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY period_end DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Report(
                id=row["id"],
                period_start=datetime.fromisoformat(row["period_start"]),
                period_end=datetime.fromisoformat(row["period_end"]),
                summary=row["summary"],
                recommendations=json.loads(row["recommendations"]),
                hive_ids=json.loads(row["hive_ids"]),
                language=row["language"] if "language" in row.keys() else "tr",
                generator=row["generator"] if "generator" in row.keys() else "manual",
                grounding_sources=json.loads(row["grounding_sources"]) if "grounding_sources" in row.keys() else [],
                report_type=row["report_type"] if "report_type" in row.keys() else "weekly",
                event_id=row["event_id"] if "event_id" in row.keys() else None,
                assessment=_decode_assessment(row),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def report(self, report_id: int) -> Report | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            return None
        return Report(
            id=row["id"], period_start=datetime.fromisoformat(row["period_start"]),
            period_end=datetime.fromisoformat(row["period_end"]), summary=row["summary"],
            recommendations=json.loads(row["recommendations"]), hive_ids=json.loads(row["hive_ids"]),
            language=row["language"] if "language" in row.keys() else "tr",
            generator=row["generator"] if "generator" in row.keys() else "manual",
            grounding_sources=json.loads(row["grounding_sources"]) if "grounding_sources" in row.keys() else [],
            report_type=row["report_type"] if "report_type" in row.keys() else "weekly",
            event_id=row["event_id"] if "event_id" in row.keys() else None,
            assessment=_decode_assessment(row),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _hive(row: sqlite3.Row) -> Hive:
        return Hive(
            hive_id=row["hive_id"],
            name=row["name"],
            location=row["location"],
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            device_id=row["device_id"], hive_id=row["hive_id"], name=row["name"],
            kind=row["kind"], active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None,
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> HiveEvent:
        status = {
            "healthy": "NORMAL",
            "uncertain": "WATCH",
            "queenless_suspected": "ALARM",
        }[row["event"]]
        return HiveEvent(
            id=row["id"],
            hive_id=row["hive_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            status=status,
            anomaly_fraction=row["confidence"],
            anomaly_severity=(
                row["anomaly_severity"]
                if "anomaly_severity" in row.keys() and row["anomaly_severity"] is not None
                else None
            ),
            consecutive_anomalies=(
                row["consecutive_anomalies"]
                if "consecutive_anomalies" in row.keys() else 0
            ),
            source_file=(row["source_file"] if "source_file" in row.keys() else None),
            model=(row["model"] if "model" in row.keys() and row["model"] else None),
            temperature_c=_optional(row, "temperature_c"),
            humidity_percent=_optional(row, "humidity_percent"),
            wind_kmh=_optional(row, "wind_kmh"),
            weather_code=_optional(row, "weather_code"),
            alindi=datetime.fromisoformat(row["alindi"]),
            acknowledged_at=(
                datetime.fromisoformat(row["acknowledged_at"])
                if "acknowledged_at" in row.keys() and row["acknowledged_at"]
                else None
            ),
            inspection_result=(
                row["inspection_result"]
                if "inspection_result" in row.keys() and row["inspection_result"]
                else None
            ),
            inspection_note=(
                row["inspection_note"]
                if "inspection_note" in row.keys() and row["inspection_note"]
                else None
            ),
            acknowledged_by=(
                row["acknowledged_by"]
                if "acknowledged_by" in row.keys() and row["acknowledged_by"]
                else None
            ),
        )
