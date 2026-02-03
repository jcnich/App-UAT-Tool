"""Database schema and helpers for UAT Test Management Tool."""
import sqlite3
from pathlib import Path

from flask import g

# Result options for checklist items
RESULTS = ("Pass", "Fail", "Partial", "NA")

# Review status: draft, in_progress, completed, approved, rejected
# archived (0=Active, 1=Archived) is separate from status
REVIEW_STATUSES = ("draft", "in_progress", "completed", "approved", "rejected")


def get_db():
    """Get a database connection for the current request. Requires Flask app context with DATABASE config."""
    if "db" not in g:
        from flask import current_app
        db_path = current_app.config.get("DATABASE", str(Path(__file__).parent / "uat.db"))
        g.db = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Close the database connection at end of request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app=None):
    """Create tables if they do not exist. Uses Flask app config for DB path if app given."""
    if app is not None:
        db_path = app.config.get("DATABASE")
    else:
        db_path = Path(__file__).parent / "uat.db"
    db_path = str(db_path)

    conn = sqlite3.connect(db_path)

    # Migration: add archived column and 'rejected' status (existing DBs created before this change).
    # Run this BEFORE the main script so an old review table gets the column before any CREATE INDEX on archived.
    has_review = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='review'"
    ).fetchone()
    if has_review:
        cur = conn.execute("PRAGMA table_info(review)")
        cols = [row[1] for row in cur.fetchall()]
        if "archived" not in cols:
            conn.execute(
                """
                CREATE TABLE review_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    app_owner_email TEXT NOT NULL DEFAULT '',
                    overall_notes TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_progress', 'completed', 'approved', 'rejected')),
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO review_new (id, app_name, app_id, date, app_owner_email, overall_notes, status, archived, created_at)
                SELECT id, app_name, app_id, date, app_owner_email, overall_notes, status,
                       CASE WHEN status = 'approved' THEN 1 ELSE 0 END, created_at
                FROM review
                """
            )
            conn.execute("DROP TABLE review")
            conn.execute("ALTER TABLE review_new RENAME TO review")
            conn.execute("CREATE INDEX idx_review_status ON review (status)")
            conn.execute("CREATE INDEX idx_review_created ON review (created_at)")
            conn.execute("CREATE INDEX idx_review_archived ON review (archived)")
            conn.commit()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS checklist_section (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT 'Section'
        );

        CREATE TABLE IF NOT EXISTS checklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER REFERENCES checklist_section(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            app_id TEXT NOT NULL,
            date TEXT NOT NULL,
            app_owner_email TEXT NOT NULL DEFAULT '',
            overall_notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_progress', 'completed', 'approved', 'rejected')),
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS review_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            checklist_id INTEGER NOT NULL,
            result TEXT CHECK (result IN ('Pass', 'Fail', 'Partial', 'NA')),
            FOREIGN KEY (review_id) REFERENCES review (id) ON DELETE CASCADE,
            FOREIGN KEY (checklist_id) REFERENCES checklist (id) ON DELETE CASCADE,
            UNIQUE (review_id, checklist_id)
        );

        CREATE INDEX IF NOT EXISTS idx_review_result_review ON review_result (review_id);
        CREATE INDEX IF NOT EXISTS idx_review_result_checklist ON review_result (checklist_id);
        CREATE INDEX IF NOT EXISTS idx_review_status ON review (status);
        CREATE INDEX IF NOT EXISTS idx_review_created ON review (created_at);
        CREATE INDEX IF NOT EXISTS idx_review_archived ON review (archived);
        CREATE INDEX IF NOT EXISTS idx_checklist_section ON checklist (section_id);
        """
    )
    conn.commit()

    # Migration: add section_id to checklist if missing (existing DBs)
    cur = conn.execute("PRAGMA table_info(checklist)")
    cols = [row[1] for row in cur.fetchall()]
    if "section_id" not in cols:
        conn.execute("ALTER TABLE checklist ADD COLUMN section_id INTEGER REFERENCES checklist_section(id)")
        conn.commit()
        conn.execute(
            "INSERT INTO checklist_section (sort_order, name) VALUES (0, 'Section 1')"
        )
        conn.commit()
        default_sec = conn.execute("SELECT id FROM checklist_section ORDER BY sort_order, id LIMIT 1").fetchone()
        if default_sec:
            conn.execute("UPDATE checklist SET section_id = ? WHERE section_id IS NULL", (default_sec[0],))
            conn.commit()

    # Ensure at least one section exists (new DBs)
    if conn.execute("SELECT COUNT(*) FROM checklist_section").fetchone()[0] == 0:
        conn.execute("INSERT INTO checklist_section (sort_order, name) VALUES (0, 'Section 1')")
        conn.commit()
    conn.close()
