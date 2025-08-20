from flask import Flask, g, render_template, request, jsonify, url_for
import sqlite3
import os

# === CONFIG ===
DB_PATH = os.environ.get(
    "DB_PATH",
    r"C:\Users\woogl\OneDrive\Documents\The CarGrader\Databases\GraderRater.db"
)

app = Flask(__name__)

# === DB HELPERS ===
def get_db():
    if "db" not in g:
        # Windows backslashes → forward slashes for SQLite URI
        db_uri_path = DB_PATH.replace("\\", "/")
        uri = f"file:{db_uri_path}?mode=ro"
        g.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# === PAGES ===
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    # avoid noisy 404s; add a real favicon later if you want
    return ("", 204)

# === DIAGNOSTICS ===
@app.route("/api/health")
def health():
    try:
        db = get_db()
        tables = [r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        exists = "AllCars" in tables
        count_all = db.execute("SELECT COUNT(*) AS c FROM AllCars").fetchone()["c"] if exists else 0
        count_ready = db.execute(
            "SELECT COUNT(*) AS c FROM AllCars WHERE Score IS NOT NULL AND Certainty IS NOT NULL"
        ).fetchone()["c"] if exists else 0
        return jsonify({
            "db_path": DB_PATH,
            "tables": tables,
            "allcars_exists": exists,
            "allcars_count": count_all,
            "with_score_certainty": count_ready
        })
    except Exception as e:
        return jsonify({"error": str(e), "db_path": DB_PATH}), 500

# === DATA APIS ===
@app.route("/api/years")
def years():
    """Years that have at least one row with both Score & Certainty."""
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT CAST(TRIM(ModelYear) AS INTEGER) AS Y
            FROM AllCars
            WHERE Score IS NOT NULL AND Certainty IS NOT NULL
                  AND ModelYear IS NOT NULL AND TRIM(ModelYear) <> ''
            ORDER BY Y DESC
        """).fetchall()
        return jsonify([r["Y"] for r in rows if r["Y"] is not None])
    except Exception as e:
        print("Error /api/years:", e)
        return jsonify([]), 500

@app.route("/api/makes")
def makes():
    year = request.args.get("year", type=int)
    if year is None:
        return jsonify([])
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT Make
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            ORDER BY Make
        """, (year,)).fetchall()
        return jsonify([r["Make"] for r in rows])
    except Exception as e:
        print("Error /api/makes:", e)
        return jsonify([]), 500

@app.route("/api/models")
def models():
    year  = request.args.get("year",  type=int)
    make  = request.args.get("make",  type=str)
    if year is None or not make:
        return jsonify([])
    try:
        db = get_db()
        rows = db.execute("""
            SELECT DISTINCT Model
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Make = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            ORDER BY Model
        """, (year, make)).fetchall()
        return jsonify([r["Model"] for r in rows])
    except Exception as e:
        print("Error /api/models:", e)
        return jsonify([]), 500

@app.route("/api/grade")
def grade():
    """Return Score & Certainty rounded to 1 decimal for a Y/M/M tuple."""
    year  = request.args.get("year", type=int)
    make  = request.args.get("make", type=str)
    model = request.args.get("model", type=str)

    if year is None or not make or not model:
        return jsonify({"error": "Missing params"}), 400

    try:
        db = get_db()
        row = db.execute("""
            SELECT
                ROUND(Score, 1)     AS ScoreRounded,
                ROUND(Certainty, 1) AS CertaintyRounded
            FROM AllCars
            WHERE CAST(TRIM(ModelYear) AS INTEGER) = ?
              AND Make  = ?
              AND Model = ?
              AND Score IS NOT NULL AND Certainty IS NOT NULL
            LIMIT 1
        """, (year, make, model)).fetchone()

        if not row:
            return jsonify({"error": "Not found"}), 404

        return jsonify({
            "year": year,
            "make": make,
            "model": model,
            "score": float(row["ScoreRounded"]) if row["ScoreRounded"] is not None else None,
            "certainty": float(row["CertaintyRounded"]) if row["CertaintyRounded"] is not None else None
        })
    except Exception as e:
        print("Error /api/grade:", e)
        return jsonify({"error": "Server error"}), 500

# === MAIN ===
if __name__ == "__main__":
    # If you prefer, run with:  set DB_PATH=C:\...\GraderRater.db  &&  python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)
