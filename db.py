import sqlite3
import json
import time

DB_PATH = "deals.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            listing_id TEXT PRIMARY KEY,
            market_hash_name TEXT,
            strategy TEXT,
            current_price REAL,
            baseline_price REAL,
            dip_percentage REAL,
            est_profit REAL,
            est_profit_percentage REAL,
            sales_in_window INTEGER,
            url TEXT,
            details TEXT,
            found_at REAL
        )
    """)
    conn.commit()
    conn.close()


def save_deals(deals):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    saved = 0
    for d in deals:
        try:
            c.execute("""
                INSERT INTO deals (listing_id, market_hash_name, strategy, current_price,
                    baseline_price, dip_percentage, est_profit, est_profit_percentage,
                    sales_in_window, url, details, found_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["listing_id"], d["market_hash_name"], d["strategy"],
                d["current_price"], d["baseline_price"], d["dip_percentage"],
                d["est_profit"], d["est_profit_percentage"], d["sales_in_window"],
                d["url"], json.dumps(d.get("details", {})), time.time()
            ))
            saved += 1
        except sqlite3.IntegrityError:
            pass  # already have this listing
    conn.commit()
    conn.close()
    return saved


def get_recent_deals(limit=200):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM deals ORDER BY found_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_deals():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM deals")
    conn.commit()
    conn.close()
