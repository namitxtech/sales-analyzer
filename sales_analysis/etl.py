"""Generate messy sales data -> clean with pandas -> load into SQLite."""
import numpy as np, pandas as pd, sqlite3, os
rng = np.random.default_rng(7)
REGIONS = ["North", "South", "East", "West", "Central"]
PRODUCTS = [  # name, category, cost, list price, popularity
    ("Laptop Pro", "Electronics", 42000, 58000, 3), ("Smartphone X", "Electronics", 26500, 30000, 4),
    ("Wireless Earbuds", "Electronics", 1500, 3500, 8), ("Smart Watch", "Electronics", 4800, 9000, 5),
    ("Office Chair", "Furniture", 5200, 9500, 4), ("Standing Desk", "Furniture", 11000, 17000, 3),
    ("Bookshelf", "Furniture", 3800, 6200, 3), ("Notebook Pack", "Stationery", 90, 220, 10),
    ("Premium Pen Set", "Stationery", 300, 650, 8), ("Air Fryer", "Appliances", 3200, 5600, 4),
    ("Mixer Grinder", "Appliances", 2100, 3400, 5), ("Water Purifier", "Appliances", 8500, 12500, 3)]

def generate(n=7500):
    P = pd.DataFrame(PRODUCTS, columns=["product_name", "category", "unit_cost", "list_price", "pop"])
    P.insert(0, "product_id", range(1, len(P) + 1))
    df = pd.DataFrame({"order_id": np.arange(n) + 10001,
        "date": pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 638, n), unit="D"),
        "region": rng.choice(REGIONS, n, p=[.24, .22, .18, .22, .14]),
        "product_id": rng.choice(P.product_id, n, p=P["pop"] / P["pop"].sum()), "qty": rng.integers(1, 5, n)})
    df = df.merge(P[["product_id", "category", "list_price"]], on="product_id")
    late = df.date >= "2026-07-01"                       # planted story: sales decline from July 2026
    keep = np.where(df.date.dt.month >= 10, 1.0, .85)
    keep = keep * np.where((df.region == "West") & late, .5, 1) * np.where((df.category == "Furniture") & late, .65, 1)
    df = df[rng.random(len(df)) < keep].copy()
    wl = (df.region == "West") & (df.date >= "2026-07-01")
    df["discount"] = rng.choice([0, 0, .05, .10], len(df))
    df.loc[wl, "discount"] = rng.uniform(.15, .30, wl.sum()).round(2)   # West over-discounting
    df["unit_price"] = df.list_price.astype(float)
    raw = df[["order_id", "date", "region", "product_id", "qty", "unit_price", "discount"]].sample(frac=1, random_state=1).reset_index(drop=True)
    m = len(raw); r = rng.random(m)
    raw["date"] = raw.date.dt.strftime("%Y-%m-%d")
    alt = rng.random(m) < .12; raw.loc[alt, "date"] = pd.to_datetime(raw.loc[alt, "date"]).dt.strftime("%d-%b-%Y")
    raw.loc[r < .06, "region"] = raw.region.str.lower(); raw.loc[(r >= .06) & (r < .10), "region"] = " " + raw.region + " "
    raw.loc[(r >= .10) & (r < .12), "region"] = raw.region.str.upper(); raw.loc[(r >= .12) & (r < .14), "region"] = None
    raw.loc[rng.random(m) < .015, "qty"] = np.nan; raw.loc[rng.random(m) < .01, "unit_price"] = np.nan
    return pd.concat([raw, raw.sample(frac=.03, random_state=2)], ignore_index=True), P.drop(columns="pop")

def clean(raw, P):
    log = [("Raw rows loaded", "Source: data/raw_sales.csv", len(raw))]
    d = raw.drop_duplicates().copy(); log.append(("Duplicates removed", "Exact repeated order records", len(raw) - len(d)))
    iso = pd.to_datetime(d.date, format="%Y-%m-%d", errors="coerce"); alt = pd.to_datetime(d.date, format="%d-%b-%Y", errors="coerce")
    log.append(("Dates standardised", "Mixed formats converted to YYYY-MM-DD", int(iso.isna().sum())))
    d["date"] = iso.fillna(alt).dt.strftime("%Y-%m-%d")
    r = d.region.str.strip().str.title()
    log.append(("Region labels fixed", "Case and whitespace variants (north, ' West ', EAST)", int((d.region.notna() & (d.region != r)).sum())))
    d["region"] = r; miss = d.region.isna()
    log.append(("Missing region dropped", "Cannot be attributed to a region", int(miss.sum()))); d = d[~miss]
    log.append(("Missing quantity imputed", "Filled with product median", int(d.qty.isna().sum())))
    d["qty"] = d.qty.fillna(d.groupby("product_id").qty.transform("median")).round().astype(int)
    log.append(("Missing price filled", "Looked up from product list price", int(d.unit_price.isna().sum())))
    d["unit_price"] = d.unit_price.fillna(d.product_id.map(P.set_index("product_id").list_price))
    log.append(("Clean rows ready", "Loaded into SQLite", len(d)))
    return d, pd.DataFrame(log, columns=["step", "detail", "rows"])

def build(db="sales.db"):
    raw, P = generate(); os.makedirs("data", exist_ok=True); raw.to_csv("data/raw_sales.csv", index=False)
    d, log = clean(raw, P)
    if os.path.exists(db): os.remove(db)
    con = sqlite3.connect(db)
    P.to_sql("products", con, index=False); d.to_sql("sales", con, index=False); log.to_sql("cleaning_log", con, index=False)
    con.execute("CREATE INDEX ix_date ON sales(date)"); con.commit(); con.close()

if __name__ == "__main__": build(); print("sales.db built")
