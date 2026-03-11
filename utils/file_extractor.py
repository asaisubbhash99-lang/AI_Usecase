import pandas as pd


def extract_invoice_items(api_key, file_bytes, mime_type):
    try:
        df = pd.read_excel(file_bytes)
    except Exception as e:
        print("EXCEL READ ERROR:", e)
        return []

    if df.empty:
        return []

    df.columns = [str(col).strip().lower() for col in df.columns]

    item_col = next(
        (c for c in df.columns if c in ["item_name", "item", "product", "description"]),
        None
    )
    price_col = next(
        (c for c in df.columns if c in ["sold_price", "price", "unit_price", "rate"]),
        None
    )
    qty_col = next(
        (c for c in df.columns if c in ["quantity", "qty"]),
        None
    )

    if not item_col:
        print("Missing item column")
        return []

    items = []

    for _, row in df.iterrows():
        item_name = str(row.get(item_col, "")).strip()

        if not item_name or item_name.lower() == "nan":
            continue

        sold_price = row.get(price_col, 0) if price_col else 0
        quantity = row.get(qty_col, 1) if qty_col else 1

        try:
            sold_price = float(sold_price)
        except Exception:
            sold_price = 0.0

        try:
            quantity = int(quantity)
        except Exception:
            quantity = 1

        items.append({
            "item_name": item_name,
            "sold_price": sold_price,
            "quantity": quantity
        })

    return items