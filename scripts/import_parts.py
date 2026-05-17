"""
Import spare parts from the reference parts app database into intern.db.

Usage:
    python scripts/import_parts.py \
        --src /Users/cremer/Code/Aixtraball/parts/data/parts.db \
        --dst /Users/cremer/Code/Aixtraball/shared/data/intern.db
"""

import argparse
import sqlite3
import sys


def main(src: str, dst: str) -> None:
    src_conn = sqlite3.connect(src)
    src_conn.row_factory = sqlite3.Row
    dst_conn = sqlite3.connect(dst)

    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    # Ensure destination tables exist (minimal DDL matching models.py)
    dst_cur.executescript("""
        CREATE TABLE IF NOT EXISTS manufacturer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS part (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(300) NOT NULL,
            article_number VARCHAR(100),
            supplier VARCHAR(200),
            stock INTEGER NOT NULL DEFAULT 0,
            shelf VARCHAR(100),
            bin VARCHAR(100)
        );
        CREATE TABLE IF NOT EXISTS part_synonym (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_id INTEGER NOT NULL REFERENCES part(id) ON DELETE CASCADE,
            synonym VARCHAR(300) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS part_manufacturer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_id INTEGER NOT NULL REFERENCES part(id) ON DELETE CASCADE,
            manufacturer_id INTEGER NOT NULL REFERENCES manufacturer(id)
        );
    """)
    dst_conn.commit()

    # Check if parts already imported
    existing = dst_cur.execute("SELECT COUNT(*) FROM part").fetchone()[0]
    if existing > 0:
        print(f"intern.db already has {existing} parts — skipping import.")
        print("Delete existing rows first if you want to re-import.")
        return

    # Detect source schema
    src_tables = {r[0] for r in src_cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    print(f"Source tables: {src_tables}")

    # Handle both table name conventions:
    # Reference app: parts, synonyms, manufacturers, part_manufacturers
    # Intern app:    part, part_synonym, manufacturer, part_manufacturer
    src_parts_table = "parts" if "parts" in src_tables else "part"
    src_synonyms_table = "synonyms" if "synonyms" in src_tables else "part_synonym"
    src_mfr_table = "manufacturers" if "manufacturers" in src_tables else "manufacturer"
    src_join_table = "part_manufacturers" if "part_manufacturers" in src_tables else "part_manufacturer"

    parts = src_cur.execute(f"SELECT * FROM {src_parts_table}").fetchall()
    print(f"Importing {len(parts)} parts …")

    manufacturer_cache: dict[str, int] = {}

    def get_or_create_manufacturer(name: str) -> int:
        name = name.strip()
        if name in manufacturer_cache:
            return manufacturer_cache[name]
        row = dst_cur.execute("SELECT id FROM manufacturer WHERE name = ?", (name,)).fetchone()
        if row:
            mid = row[0]
        else:
            dst_cur.execute("INSERT INTO manufacturer (name) VALUES (?)", (name,))
            mid = dst_cur.lastrowid
        manufacturer_cache[name] = mid
        return mid

    for p in parts:
        p = dict(p)
        dst_cur.execute(
            "INSERT INTO part (name, article_number, supplier, stock, shelf, bin) VALUES (?,?,?,?,?,?)",
            (
                p.get("name", "").strip(),
                p.get("article_number") or None,
                p.get("supplier") or None,
                int(p.get("stock") or 0),
                p.get("shelf") or None,
                p.get("bin") or None,
            ),
        )
        new_part_id = dst_cur.lastrowid
        old_part_id = p["id"]

        # Synonyms — column may be called "synonym" or "name"
        if src_synonyms_table in src_tables:
            synonyms = src_cur.execute(
                f"SELECT * FROM {src_synonyms_table} WHERE part_id = ?", (old_part_id,)
            ).fetchall()
            for row in synonyms:
                row = dict(row)
                syn = row.get("synonym") or row.get("name") or ""
                if syn.strip():
                    dst_cur.execute(
                        "INSERT INTO part_synonym (part_id, synonym) VALUES (?, ?)",
                        (new_part_id, syn.strip()),
                    )

        # Manufacturers via join table
        if src_join_table in src_tables and src_mfr_table in src_tables:
            mfrs = src_cur.execute(
                f"""SELECT m.name FROM {src_mfr_table} m
                   JOIN {src_join_table} pm ON pm.manufacturer_id = m.id
                   WHERE pm.part_id = ?""",
                (old_part_id,),
            ).fetchall()
            for (mname,) in mfrs:
                if mname and mname.strip():
                    mid = get_or_create_manufacturer(mname)
                    dst_cur.execute(
                        "INSERT INTO part_manufacturer (part_id, manufacturer_id) VALUES (?, ?)",
                        (new_part_id, mid),
                    )

    dst_conn.commit()
    final = dst_cur.execute("SELECT COUNT(*) FROM part").fetchone()[0]
    mfr_count = dst_cur.execute("SELECT COUNT(*) FROM manufacturer").fetchone()[0]
    syn_count = dst_cur.execute("SELECT COUNT(*) FROM part_synonym").fetchone()[0]
    print(f"Done. {final} parts, {mfr_count} manufacturers, {syn_count} synonyms imported.")

    src_conn.close()
    dst_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import parts from reference DB into intern.db")
    parser.add_argument("--src", default="/Users/cremer/Code/Aixtraball/parts/data/parts.db")
    parser.add_argument("--dst", default="/Users/cremer/Code/Aixtraball/shared/data/intern.db")
    args = parser.parse_args()
    main(args.src, args.dst)
