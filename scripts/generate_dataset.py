import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "warehouse"

END = datetime.now(timezone.utc)
START = END - timedelta(days=1400)

CATEGORIES = [
    ("Intimates", 17.92, 33.71, 118, "Women"),
    ("Jeans", 52.41, 97.85, 100, "Women"),
    ("Tops & Tees", 23.14, 41.34, 93, "Women"),
    ("Fashion Hoodies & Sweatshirts", 27.80, 53.92, 93, "Men"),
    ("Swim", 28.89, 57.82, 90, "Women"),
    ("Sleep & Lounge", 24.23, 49.22, 89, "Women"),
    ("Shorts", 22.92, 45.77, 88, "Men"),
    ("Sweaters", 36.09, 75.32, 87, "Women"),
    ("Accessories", 17.06, 42.57, 78, "Women"),
    ("Active", 21.22, 50.62, 72, "Men"),
    ("Outerwear & Coats", 64.98, 146.02, 71, "Men"),
    ("Underwear", 12.77, 27.16, 54, "Men"),
    ("Pants", 27.46, 59.81, 52, "Men"),
    ("Dresses", 37.93, 84.20, 48, "Women"),
    ("Socks", 12.32, 20.42, 45, "Men"),
    ("Maternity", 22.42, 50.80, 45, "Women"),
    ("Plus", 19.26, 38.43, 38, "Women"),
    ("Suits & Sport Coats", 50.80, 126.56, 37, "Men"),
    ("Socks & Hosiery", 6.74, 16.76, 33, "Women"),
    ("Pants & Capris", 28.87, 54.71, 31, "Women"),
    ("Leggings", 16.28, 27.15, 28, "Women"),
    ("Blazers & Jackets", 35.11, 92.60, 28, "Women"),
    ("Skirts", 20.86, 52.33, 18, "Women"),
    ("Suits", 70.18, 116.16, 9, "Men"),
    ("Jumpsuits & Rompers", 24.15, 45.42, 8, "Women"),
    ("Clothing Sets", 52.51, 84.84, 2, "Women"),
]

BRANDS = [
    "Calvin Klein", "Levi's", "Nike", "Carhartt", "Hanes", "Dockers", "Columbia",
    "Under Armour", "Wrangler", "Tommy Hilfiger", "Patagonia", "The North Face",
    "Lucky Brand", "Volcom", "Quiksilver", "Billabong", "Fruit of the Loom",
    "Gildan", "Champion", "Dickies", "Ralph Lauren", "Guess", "Diesel", "Puma",
]

STATES = [
    ("California", "United States", ["Los Angeles", "San Diego", "San Jose", "Fresno"], 36.78, -119.42, 100, 1.00, 1.00),
    ("Texas", "United States", ["Houston", "San Antonio", "Dallas", "Austin"], 31.97, -99.90, 68, 1.00, 0.78),
    ("New York", "United States", ["New York", "Buffalo", "Rochester"], 43.00, -75.00, 74, 1.04, 1.02),
    ("Florida", "United States", ["Jacksonville", "Miami", "Tampa", "Orlando"], 27.99, -81.76, 62, 0.95, 0.96),
    ("Illinois", "United States", ["Chicago", "Aurora", "Naperville"], 40.63, -89.40, 44, 0.98, 0.99),
    ("Pennsylvania", "United States", ["Philadelphia", "Pittsburgh", "Allentown"], 41.20, -77.19, 40, 0.96, 0.97),
    ("Ohio", "United States", ["Columbus", "Cleveland", "Cincinnati"], 40.42, -82.91, 36, 0.93, 0.95),
    ("Georgia", "United States", ["Atlanta", "Augusta", "Savannah"], 32.17, -82.91, 34, 0.94, 0.93),
    ("Washington", "United States", ["Seattle", "Spokane", "Tacoma"], 47.75, -120.74, 30, 1.08, 1.05),
    ("Arizona", "United States", ["Phoenix", "Tucson", "Mesa"], 34.05, -111.09, 28, 0.92, 0.90),
    ("Massachusetts", "United States", ["Boston", "Worcester", "Springfield"], 42.41, -71.38, 24, 1.10, 1.06),
    ("Colorado", "United States", ["Denver", "Colorado Springs", "Aurora"], 39.55, -105.78, 22, 1.05, 1.01),
    ("England", "United Kingdom", ["London", "Manchester", "Birmingham"], 52.36, -1.17, 46, 1.02, 0.98),
    ("Guangdong", "China", ["Shenzhen", "Guangzhou", "Dongguan"], 23.38, 113.77, 58, 0.88, 1.04),
    ("São Paulo", "Brasil", ["São Paulo", "Campinas", "Santos"], -23.55, -46.63, 42, 0.85, 0.94),
    ("Seoul", "South Korea", ["Seoul"], 37.57, 126.98, 26, 1.01, 1.08),
    ("Île-de-France", "France", ["Paris", "Boulogne-Billancourt"], 48.85, 2.35, 24, 1.03, 0.99),
    ("New South Wales", "Australia", ["Sydney", "Newcastle"], -33.87, 151.21, 20, 1.07, 0.97),
]

TRAFFIC = (("Search", 70), ("Organic", 15), ("Facebook", 6), ("Email", 5), ("Display", 4))
STATUSES = (("Shipped", 30), ("Complete", 25), ("Processing", 20), ("Cancelled", 15), ("Returned", 10))

FIRST_F = ["Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper",
           "Evelyn", "Abigail", "Emily", "Grace", "Chloe", "Zoe", "Lily", "Nora", "Hazel",
           "Aria", "Ellie", "Maria", "Ana", "Yan", "Min", "Camille"]
FIRST_M = ["Liam", "Noah", "Oliver", "Elijah", "James", "William", "Benjamin", "Lucas", "Henry",
           "Alexander", "Mason", "Michael", "Ethan", "Daniel", "Jacob", "Logan", "Jackson",
           "Levi", "Wei", "Jun", "Paulo", "Thomas", "Marc", "Diego", "Andre"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
        "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor",
        "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Chen",
        "Wang", "Silva", "Santos", "Dubois", "Kim", "Park", "Nguyen", "Patel"]
STREETS = ["Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake", "Hill", "Park", "Sunset",
           "Ridge", "River", "Spring", "Church", "Market", "Union", "Center", "Highland"]
SUFFIX = ["Street", "Avenue", "Road", "Lane", "Drive", "Court", "Trail", "Way"]

SPIKE = END - timedelta(days=120)
SPIKE_MONTH = (SPIKE.year, SPIKE.month)
SPIKE_CATEGORIES = {"Outerwear & Coats", "Sweaters", "Blazers & Jackets"}

SCHEMAS = {
    "users": [
        ("id", "INTEGER"), ("first_name", "STRING"), ("last_name", "STRING"), ("email", "STRING"),
        ("age", "INTEGER"), ("gender", "STRING"), ("state", "STRING"), ("street_address", "STRING"),
        ("postal_code", "STRING"), ("city", "STRING"), ("country", "STRING"),
        ("latitude", "FLOAT"), ("longitude", "FLOAT"), ("traffic_source", "STRING"),
        ("created_at", "TIMESTAMP"), ("user_geom", "GEOGRAPHY"),
    ],
    "products": [
        ("id", "INTEGER"), ("cost", "FLOAT"), ("category", "STRING"), ("name", "STRING"),
        ("brand", "STRING"), ("retail_price", "FLOAT"), ("department", "STRING"),
        ("sku", "STRING"), ("distribution_center_id", "INTEGER"),
    ],
    "orders": [
        ("order_id", "INTEGER"), ("user_id", "INTEGER"), ("status", "STRING"), ("gender", "STRING"),
        ("created_at", "TIMESTAMP"), ("returned_at", "TIMESTAMP"), ("shipped_at", "TIMESTAMP"),
        ("delivered_at", "TIMESTAMP"), ("num_of_item", "INTEGER"),
    ],
    "order_items": [
        ("id", "INTEGER"), ("order_id", "INTEGER"), ("user_id", "INTEGER"),
        ("product_id", "INTEGER"), ("inventory_item_id", "INTEGER"), ("status", "STRING"),
        ("created_at", "TIMESTAMP"), ("shipped_at", "TIMESTAMP"), ("delivered_at", "TIMESTAMP"),
        ("returned_at", "TIMESTAMP"), ("sale_price", "FLOAT"),
    ],
}


def ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.%f UTC") if value else None


def pick(pairs):
    return random.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def write(name, rows):
    path = OUT / f"{name}.ndjson"
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    (OUT / f"{name}.schema.json").write_text(
        json.dumps([{"name": n, "type": t, "mode": "NULLABLE"} for n, t in SCHEMAS[name]], indent=2)
    )
    return path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a thelook_ecommerce-shaped dataset")
    parser.add_argument("--users", type=int, default=8000)
    parser.add_argument("--products", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    rng = np.random.default_rng(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    span = int((END - START).total_seconds())

    products = []
    for pid in range(1, args.products + 1):
        category, cost, retail, _, department = random.choices(
            CATEGORIES, weights=[c[3] for c in CATEGORIES]
        )[0]
        brand = random.choice(BRANDS)
        factor = random.uniform(0.6, 1.7)
        retail_price = round(retail * factor, 2)
        products.append({
            "id": pid,
            "cost": round(cost * factor * random.uniform(0.92, 1.08), 4),
            "category": category,
            "name": f"{brand} {category.split(' ')[0]} {random.choice(['Classic', 'Slim', 'Relaxed', 'Premium', 'Essential', 'Lightweight'])}",
            "brand": brand,
            "retail_price": retail_price,
            "department": department,
            "sku": f"{brand[:3].upper()}{pid:06d}",
            "distribution_center_id": random.randint(1, 10),
        })
    by_category = {}
    for product in products:
        by_category.setdefault(product["category"], []).append(product)

    users, profiles = [], {}
    state_weights = [s[5] for s in STATES]
    for uid in range(1, args.users + 1):
        state, country, cities, lat, lon, _, spend_index, repeat_index = random.choices(
            STATES, weights=state_weights
        )[0]
        gender = random.choice(["F", "M"])
        first = random.choice(FIRST_F if gender == "F" else FIRST_M)
        last = random.choice(LAST)
        created = START + timedelta(seconds=random.randint(0, span))
        latitude = round(lat + random.uniform(-1.4, 1.4), 6)
        longitude = round(lon + random.uniform(-1.4, 1.4), 6)
        users.append({
            "id": uid,
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{uid}@example.com",
            "age": random.randint(12, 70),
            "gender": gender,
            "state": state,
            "street_address": f"{random.randint(1, 9999)} {random.choice(STREETS)} {random.choice(SUFFIX)}",
            "postal_code": f"{random.randint(10000, 99999)}",
            "city": random.choice(cities),
            "country": country,
            "latitude": latitude,
            "longitude": longitude,
            "traffic_source": pick(TRAFFIC),
            "created_at": ts(created),
            "user_geom": f"POINT({longitude} {latitude})",
        })
        profiles[uid] = (created, gender, state, spend_index, repeat_index)

    orders, items = [], []
    order_id, item_id = 1, 1
    for uid, (joined, gender, state, spend_index, repeat_index) in profiles.items():
        window = max(int((END - joined).total_seconds()), 86400)
        maturity = min(window / span, 1.0)
        expected = 2.4 * repeat_index * (0.45 + 0.55 * maturity)
        count = int(rng.poisson(expected))
        for _ in range(count):
            created = joined + timedelta(seconds=random.randint(0, window))
            status = pick(STATUSES)
            if (created.year, created.month) == SPIKE_MONTH and status in ("Shipped", "Complete"):
                if random.random() < 0.38:
                    status = "Returned"
            shipped = delivered = returned = None
            if status in ("Shipped", "Complete", "Returned"):
                shipped = created + timedelta(hours=random.randint(12, 96))
            if status in ("Complete", "Returned"):
                delivered = shipped + timedelta(hours=random.randint(24, 168))
            if status == "Returned":
                returned = delivered + timedelta(hours=random.randint(24, 480))

            n_items = random.choices([1, 2, 3, 4], weights=[62, 24, 10, 4])[0]
            orders.append({
                "order_id": order_id,
                "user_id": uid,
                "status": status,
                "gender": gender,
                "created_at": ts(created),
                "returned_at": ts(returned),
                "shipped_at": ts(shipped),
                "delivered_at": ts(delivered),
                "num_of_item": n_items,
            })
            for _ in range(n_items):
                if state == "Texas" and random.random() < 0.13:
                    pool = by_category.get("Outerwear & Coats") or products
                else:
                    pool = products
                product = random.choice(pool)
                item_status = status
                if (
                    status in ("Shipped", "Complete")
                    and (created.year, created.month) == SPIKE_MONTH
                    and product["category"] in SPIKE_CATEGORIES
                    and random.random() < 0.45
                ):
                    item_status = "Returned"
                items.append({
                    "id": item_id,
                    "order_id": order_id,
                    "user_id": uid,
                    "product_id": product["id"],
                    "inventory_item_id": item_id * 2,
                    "status": item_status,
                    "created_at": ts(created),
                    "shipped_at": ts(shipped),
                    "delivered_at": ts(delivered),
                    "returned_at": ts(returned if item_status == "Returned" else None),
                    "sale_price": round(product["retail_price"] * spend_index * random.uniform(0.97, 1.03), 3),
                })
                item_id += 1
            order_id += 1

    total = 0
    for name, rows in (("users", users), ("products", products), ("orders", orders), ("order_items", items)):
        size = write(name, rows)
        total += size
        print(f"{name:12} {len(rows):>8,} rows  {size / 1e6:>6.2f} MB")
    print(f"{'total':12} {'':>8}       {total / 1e6:>6.2f} MB  ->  {OUT}")


if __name__ == "__main__":
    main()
