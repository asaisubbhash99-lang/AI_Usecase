import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
import uuid
from sqlalchemy import create_engine, text

from utils.file_extractor import extract_invoice_items
from utils.gemini_calculator import calculate_profit_gemini
from utils.ai_insights import generate_profit_insights
from utils.app_chatbot import ask_app_question


# ---------------------------
# Load config
# ---------------------------
with open("configs/settings.json") as f:
    config = json.load(f)

API_KEY = config["API_KEY"]

DB_HOST = config["DB_HOST"]
DB_PORT = config["DB_PORT"]
DB_NAME = config["DB_NAME"]
DB_USER = config["DB_USER"]
DB_PASSWORD = config["DB_PASSWORD"]


# ---------------------------
# PostgreSQL connection
# ---------------------------
DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)


# ---------------------------
# Create tables if not exist
# ---------------------------
def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS invoices_metadata (
                invoice_id VARCHAR(50) PRIMARY KEY,
                upload_date TIMESTAMP,
                file_name TEXT,
                total_revenue NUMERIC,
                total_profit NUMERIC
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS consolidated_invoices (
                id SERIAL PRIMARY KEY,
                invoice_id VARCHAR(50),
                upload_date TIMESTAMP,
                file_name TEXT,
                item_name TEXT,
                qty NUMERIC,
                sold_price NUMERIC,
                cost_price NUMERIC,
                tax_rate NUMERIC,
                discount_percentage NUMERIC,
                tax_amount NUMERIC,
                discount_amount NUMERIC,
                revenue NUMERIC,
                profit NUMERIC,
                final_price NUMERIC
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reference_data (
                item_name TEXT PRIMARY KEY,
                cost_price NUMERIC,
                tax_rate NUMERIC,
                discount_percentage NUMERIC
            );
        """))


init_db()


# ---------------------------
# DB helpers
# ---------------------------
def read_table(table_name):
    try:
        return pd.read_sql(f"SELECT * FROM {table_name}", engine)
    except Exception:
        return pd.DataFrame()


def save_reference_data(df):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reference_data"))
    df.to_sql("reference_data", engine, if_exists="append", index=False)


def save_invoice(items, invoice_total, invoice_profit, file_name):
    invoice_id = str(uuid.uuid4())[:8]
    upload_date = datetime.now()

    rows = []
    for i in items:
        row = {
            "invoice_id": invoice_id,
            "upload_date": upload_date,
            "file_name": file_name,
            "item_name": i.get("item_name"),
            "qty": i.get("Qty", 1),
            "sold_price": i.get("sold_price", 0),
            "cost_price": i.get("cost_price", 0),
            "tax_rate": i.get("tax_rate", 0),
            "discount_percentage": i.get("discount_percentage", 0),
            "tax_amount": i.get("tax_amount", 0),
            "discount_amount": i.get("discount_amount", 0),
            "revenue": i.get("revenue", 0),
            "profit": i.get("profit", 0),
            "final_price": i.get("final_price", i.get("revenue", 0))
        }
        rows.append(row)

    df_items = pd.DataFrame(rows)
    df_items.to_sql("consolidated_invoices", engine, if_exists="append", index=False)

    metadata = pd.DataFrame([{
        "invoice_id": invoice_id,
        "upload_date": upload_date,
        "file_name": file_name,
        "total_revenue": invoice_total,
        "total_profit": invoice_profit
    }])

    metadata.to_sql("invoices_metadata", engine, if_exists="append", index=False)

    return invoice_id


# ---------------------------
# Sidebar Navigation
# ---------------------------
st.sidebar.title("Navigation")

page = st.sidebar.radio(
    "Go to",
    ["Home", "Analytics", "Invoice History", "Reference Data", "Chatbot"]
)


# =====================================================
# HOME PAGE
# =====================================================
if page == "Home":

    st.title("📊 AI Invoice Profit Analyzer")

    uploaded_file = st.file_uploader(
        "Upload Invoice (Excel)",
        type=["xlsx", "xls"]
    )

    if uploaded_file:
        file_bytes = uploaded_file.read()
        file_type = uploaded_file.type
        items = []

        if file_type in [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel"
        ]:
            df = pd.read_excel(uploaded_file)
            items = df.to_dict(orient="records")
        else:
            with st.spinner("Extracting invoice items ..."):
                items = extract_invoice_items(API_KEY, file_bytes, file_type)

        if not items:
            st.error("No items extracted from invoice")
            st.stop()

        for i in items:
            keys = list(i.keys())
            qty_key = next((k for k in keys if k.lower() in ["quantity", "qty"]), None)
            i["Qty"] = i.pop(qty_key) if qty_key else 1

        st.session_state["items"] = items
        st.session_state["file_name"] = uploaded_file.name

    if "items" in st.session_state:
        items = st.session_state["items"]

        st.subheader("Extracted Items")
        st.dataframe(pd.DataFrame(items), use_container_width=True)

        ref_df = read_table("reference_data")

        if ref_df.empty:
            st.error("Reference data is empty. Please add data in the Reference Data page.")
            st.stop()

        stock_prices = ref_df.set_index("item_name")["cost_price"].to_dict()
        tax_discount = ref_df.set_index("item_name")[["tax_rate", "discount_percentage"]].to_dict(orient="index")

        results, total_profit, total_cost, total_revenue = calculate_profit_gemini(
            API_KEY,
            items,
            stock_prices,
            tax_discount
        )

        st.session_state["results"] = results

        st.subheader("🧾 Final Invoice Table")

        final_rows = []
        for r in results:
            final_rows.append({
                "Item": r.get("item_name"),
                "Qty": r.get("Qty", 1),
                "Price": r.get("sold_price", 0),
                "Tax": r.get("tax_amount", 0),
                "Discount": r.get("discount_amount", 0),
                "Final": r.get("final_price", r.get("revenue", 0))
            })

        st.dataframe(pd.DataFrame(final_rows), use_container_width=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Revenue", f"${total_revenue:.2f}")
        col2.metric("Total Profit", f"${total_profit:.2f}")
        col3.metric("Total Tax", f"${sum(r.get('tax_amount', 0) for r in results):.2f}")

        if st.button("💾 Save Invoice"):
            invoice_id = save_invoice(
                results,
                total_revenue,
                total_profit,
                st.session_state["file_name"]
            )

            st.success(f"Invoice saved with ID: {invoice_id}")

            del st.session_state["items"]
            del st.session_state["file_name"]
            del st.session_state["results"]


# =====================================================
# REFERENCE DATA
# =====================================================
elif page == "Reference Data":

    st.title("📁 Reference Data")

    ref_df = read_table("reference_data")

    if ref_df.empty:
        ref_df = pd.DataFrame(columns=[
            "item_name",
            "cost_price",
            "tax_rate",
            "discount_percentage"
        ])

    edited_df = st.data_editor(
        ref_df,
        use_container_width=True,
        num_rows="dynamic"
    )

    if st.button("💾 Save Reference Data"):
        save_reference_data(edited_df)
        st.success("Reference data saved to PostgreSQL!")


# =====================================================
# ANALYTICS
# =====================================================
# =====================================================
# ANALYTICS
# =====================================================
elif page == "Analytics":

    st.title("📊 Business Analytics")

    df = read_table("consolidated_invoices")
    df_meta = read_table("invoices_metadata")

    if not df.empty and not df_meta.empty:
        st.subheader("Top Products by Profit")

        top_products = df.groupby("item_name")["profit"].sum().sort_values(
            ascending=False
        ).head(10)

        st.bar_chart(top_products)

        st.subheader("Revenue & Profit Over Time")

        df_meta["upload_date"] = pd.to_datetime(df_meta["upload_date"])
        df_meta = df_meta.sort_values("upload_date")

        chart_df = df_meta.groupby("upload_date")[["total_revenue", "total_profit"]].sum()
        st.line_chart(chart_df)

        st.subheader("🧠 AI Insights")

        try:
            analytics_results = []

            for _, row in df.iterrows():
                analytics_results.append({
                    "item_name": row.get("item_name"),
                    "Qty": float(row.get("qty", 1) or 1),
                    "sold_price": float(row.get("sold_price", 0) or 0),
                    "cost_price": float(row.get("cost_price", 0) or 0),
                    "tax_rate": float(row.get("tax_rate", 0) or 0),
                    "discount_percentage": float(row.get("discount_percentage", 0) or 0),
                    "tax_amount": float(row.get("tax_amount", 0) or 0),
                    "discount_amount": float(row.get("discount_amount", 0) or 0),
                    "revenue": float(row.get("revenue", 0) or 0),
                    "profit": float(row.get("profit", 0) or 0),
                    "final_price": float(row.get("final_price", 0) or 0)
                })

            insights = generate_profit_insights(API_KEY, analytics_results)

            if insights:
                st.write(insights)
            else:
                st.info("No AI insights generated.")

        except Exception as e:
            st.warning(f"Unable to generate AI insights: {e}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Revenue", f"${df_meta['total_revenue'].astype(float).sum():.2f}")
        col2.metric("Total Profit", f"${df_meta['total_profit'].astype(float).sum():.2f}")
        col3.metric("Total Invoices", len(df_meta))

    else:
        st.warning("No invoice data available for analytics.")


# =====================================================
# INVOICE HISTORY
# =====================================================
elif page == "Invoice History":

    import io

    st.title("🧾 Invoice History")

    df_meta = read_table("invoices_metadata")
    df_items = read_table("consolidated_invoices")

    if df_meta.empty:
        st.warning("No invoices found.")
    else:
        df_meta = df_meta.sort_values("upload_date", ascending=False).reset_index(drop=True)

        h1, h2, h3, h4, h5, h6 = st.columns([1.6, 1.8, 2.0, 1.2, 1.2, 1.4])
        h1.markdown("**Invoice ID**")
        h2.markdown("**Upload Date**")
        h3.markdown("**File Name**")
        h4.markdown("**Revenue**")
        h5.markdown("**Profit**")
        h6.markdown("**Download**")

        st.divider()

        for _, row in df_meta.iterrows():
            invoice_id = row["invoice_id"]
            invoice_items = df_items[df_items["invoice_id"] == invoice_id].copy()

            c1, c2, c3, c4, c5, c6 = st.columns([1.6, 1.8, 2.0, 1.2, 1.2, 1.4])
            c1.write(invoice_id)
            c2.write(str(row["upload_date"]))
            c3.write(str(row["file_name"]))
            c4.write(f"${float(row['total_revenue']):.2f}")
            c5.write(f"${float(row['total_profit']):.2f}")

            if not invoice_items.empty:
                output = io.BytesIO()

                preferred_cols = [
                    "invoice_id", "upload_date", "file_name", "item_name", "qty",
                    "sold_price", "cost_price", "tax_rate", "discount_percentage",
                    "tax_amount", "discount_amount", "revenue", "profit", "final_price"
                ]
                invoice_items = invoice_items[[c for c in preferred_cols if c in invoice_items.columns]]

                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    invoice_items.to_excel(writer, index=False, sheet_name="Invoice")

                output.seek(0)

                c6.download_button(
                    "Download",
                    data=output,
                    file_name=f"invoice_{invoice_id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_{invoice_id}"
                )
            else:
                c6.write("No data")

            st.divider()

# =====================================================
# CHATBOT
# =====================================================
elif page == "Chatbot":
    st.title("💬 Sales Chatbot")
    st.caption("Ask anything about invoices, analytics, reference data, invoice history, or how the app works.")

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [
            {
                "role": "assistant",
                "content": (
                    "Hi! I can answer questions about your invoice data, analytics, "
                    "reference data, invoice history, and app behavior."
                )
            }
        ]

    with st.expander("Example questions"):
        st.write("- What is the total profit?")
        st.write("- Show top 5 products by profit")
        st.write("- Which invoice has the highest total revenue?")
        st.write("- What is the tax rate for Laptop A?")
        st.write("- How many invoices were uploaded today?")
        st.write("- Which file has the highest profit?")
        st.write("- What does Save Invoice do?")
        st.write("- What pages are available in this app?")
        st.write("- How does this app calculate profit?")
        st.write("- What can I ask in this chatbot?")

    top_col1, top_col2 = st.columns([1, 5])
    with top_col1:
        if st.button("Clear Chat"):
            st.session_state["chat_messages"] = [
                {
                    "role": "assistant",
                    "content": (
                        "Chat cleared. Ask me anything about your invoice app."
                    )
                }
            ]
            st.rerun()

    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    prompt = st.chat_input("Ask your question")

    if prompt:
        st.session_state["chat_messages"].append({
            "role": "user",
            "content": prompt
        })

        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    result = ask_app_question(API_KEY, engine, prompt)
                    answer = result["answer"]
                except Exception as e:
                    answer = f"Error: {str(e)}"

            st.write(answer)

        st.session_state["chat_messages"].append({
            "role": "assistant",
            "content": answer
        })