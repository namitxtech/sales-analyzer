import os, sqlite3
from flask import Flask, render_template, jsonify, request
import etl
DB = "sales.db"
if not os.path.exists(DB): etl.build(DB)
app = Flask(__name__)
REV = "s.qty*s.unit_price*(1-s.discount)"
PRF = "s.qty*(s.unit_price*(1-s.discount)-p.unit_cost)"
FROM = "FROM sales s JOIN products p ON p.product_id=s.product_id"

def run(sql, params=()):  # read-only connection: the SQL lab can never modify data
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    try: return [dict(r) for r in con.execute(sql, params)]
    finally: con.close()

def grp(col, order="profit DESC"):
    return (f"SELECT {col} AS label, ROUND(SUM({REV})) AS revenue, ROUND(SUM({PRF})) AS profit, "
            f"ROUND(100.0*SUM({PRF})/SUM({REV}),1) AS margin, COUNT(*) AS orders {FROM} GROUP BY 1 ORDER BY {order}")
Q = {"monthly": grp("substr(s.date,1,7)", "1"), "products": grp("p.product_name"), "regions": grp("s.region"),
     "categories": grp("p.category"),
     "region_month": f"SELECT substr(s.date,1,7) AS month, s.region AS label, ROUND(SUM({REV})) AS revenue {FROM} GROUP BY 1,2 ORDER BY 1"}

@app.get("/api/kpi")
def kpi():
    m = run(Q["monthly"]); t = lambda k: sum(x[k] for x in m)
    g = lambda a, b: round(100 * (a - b) / b, 1) if b else None
    return jsonify(revenue=t("revenue"), profit=t("profit"), margin=round(100 * t("profit") / t("revenue"), 1), orders=t("orders"),
                   mom=g(m[-1]["revenue"], m[-2]["revenue"]), yoy=g(m[-1]["revenue"], m[-13]["revenue"]) if len(m) > 12 else None)

@app.get("/api/<name>")
def api(name):
    return jsonify(run(Q[name])) if name in Q else (jsonify(error="unknown"), 404)

@app.post("/api/sql")
def sql_lab():
    q = (request.json.get("q") or "").strip().rstrip(";")
    if not q.lower().startswith(("select", "with")): return jsonify(error="Only SELECT queries are allowed."), 400
    try: rows = run(f"SELECT * FROM ({q}) LIMIT 200")
    except Exception as e: return jsonify(error=str(e)), 400
    return jsonify(cols=list(rows[0]) if rows else [], rows=[list(r.values()) for r in rows])

# ---- AI feature: hypotheses for the sales decline, each tested with SQL (recent 3 months vs the 3 before) ----
def hyp(label, metric, agg="SUM"):
    return (f"SELECT {label} AS label,\n  {agg}(CASE WHEN s.date>=:p0 AND s.date<:r0 THEN {metric} END) AS prev,\n"
            f"  {agg}(CASE WHEN s.date>=:r0 THEN {metric} END) AS recent\n{FROM}\nGROUP BY 1")
H = [("Demand fell: fewer orders", "Total order count dropped", hyp("'All regions'", "1"), "down", .08),
     ("Over-discounting in a region", "Average discount rose sharply somewhere", hyp("s.region", "s.discount", "AVG"), "up", .25),
     ("A region is under-performing", "Regional revenue fell", hyp("s.region", REV), "down", .25),
     ("A product category is declining", "Category revenue fell", hyp("p.category", REV), "down", .20),
     ("Customers are buying smaller baskets", "Average quantity per order fell", hyp("'All regions'", "s.qty", "AVG"), "down", .08)]

def periods():
    y, mo = map(int, run("SELECT MAX(date) d FROM sales")[0]["d"][:7].split("-"))
    f = lambda k: f"{(y*12+mo-1-k)//12}-{(y*12+mo-1-k)%12+1:02d}-01"
    return {"r0": f(2), "p0": f(5)}

@app.get("/ai")
def ai():
    P, out = periods(), []
    for title, why, sql, d, thr in H:
        rows = run(sql, P)
        for r in rows: r["chg"] = round(100 * (r["recent"] - r["prev"]) / r["prev"], 1) if r["prev"] else 0
        rows.sort(key=lambda r: r["chg"], reverse=(d == "up")); w = rows[0]
        out.append(dict(title=title, why=why, sql=sql, rows=rows, worst=w, ok=abs(w["chg"]) >= thr * 100 and (w["chg"] < 0) == (d == "down")))
    return render_template("ai.html", hs=out, P=P)

@app.get("/cleaning")
def cleaning(): return render_template("cleaning.html", log=run("SELECT * FROM cleaning_log"))
for path, page in [("/", "dashboard"), ("/products", "products"), ("/regions", "regions"), ("/sql", "sql")]:
    app.add_url_rule(path, page, (lambda p: lambda: render_template(p + ".html"))(page))

if __name__ == "__main__": app.run(debug=True)
