import re
import pandas as pd
from sqlalchemy import text
from google import genai


ALLOWED_TABLES = [
    "consolidated_invoices",
    "invoices_metadata",
    "reference_data"
]

SCHEMA_DESCRIPTION = """
Database schema:

1. Table: consolidated_invoices
Columns:
- id (integer)
- invoice_id (varchar)
- upload_date (timestamp)
- file_name (text)
- item_name (text)
- qty (integer)
- sold_price (numeric)
- cost_price (numeric)
- tax_rate (numeric)
- discount_percentage (numeric)
- tax_amount (numeric)
- discount_amount (numeric)
- revenue (numeric)
- profit (numeric)
- final_price (numeric)

2. Table: invoices_metadata
Columns:
- invoice_id (varchar)
- upload_date (timestamp)
- file_name (text)
- total_revenue (numeric)
- total_profit (numeric)

3. Table: reference_data
Columns:
- item_name (text)
- cost_price (numeric)
- tax_rate (numeric)
- discount_percentage (numeric)
"""

APP_CONTEXT = """
This is an AI Invoice Profit Analyzer Streamlit app.

App pages:
- Home:
  Upload invoice files (PDF/Image/Excel), extract items, calculate final invoice values,
  show extracted items, show final invoice table, show metrics like total revenue/profit/tax,
  and save invoice results into PostgreSQL.

- Analytics:
  Shows top products by profit, revenue & profit over time, total revenue, total profit,
  and total invoice count.

- Invoice History:
  Shows previously saved invoice metadata.

- Reference Data:
  Lets user maintain item_name, cost_price, tax_rate, and discount_percentage.

- Chatbot:
  Answers user questions about app data and app behavior.

Business meaning:
- revenue: sales value from invoice item
- profit: revenue minus cost and adjustments based on your existing app logic
- final_price: final value after tax/discount logic
- tax_amount: calculated tax for item
- discount_amount: discount applied for item
"""

GENERAL_APP_QUESTIONS = [
    "what does this app do",
    "how does this app work",
    "what pages are available",
    "what are the pages",
    "what pages does this app have",
    "how is profit calculated",
    "how is revenue calculated",
    "how is tax calculated",
    "how is discount calculated",
    "what happens when i save invoice",
    "what does save invoice do",
    "what is reference data",
    "what is invoice history",
    "what is analytics",
    "what is chatbot",
    "how does upload work",
    "what file types are supported",
    "what can i ask",
    "what questions can i ask",
    "how does this chatbot work"
]


def create_client(api_key: str):
    return genai.Client(api_key=api_key)


def extract_sql_from_response(response_text: str) -> str:
    if not response_text:
        return ""

    code_block = re.search(r"```sql\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip().rstrip(";") + ";"

    cleaned = response_text.strip()

    cleaned = re.sub(r"^```.*?\n", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"```$", "", cleaned).strip()

    if not cleaned.endswith(";"):
        cleaned += ";"

    return cleaned


def is_general_app_question(user_question: str) -> bool:
    q = user_question.lower().strip()
    return any(keyword in q for keyword in GENERAL_APP_QUESTIONS)


def is_safe_select_query(sql: str) -> bool:
    if not sql:
        return False

    sql_clean = sql.strip().lower()

    forbidden_keywords = [
        "insert ", "update ", "delete ", "drop ", "alter ", "truncate ",
        "create ", "grant ", "revoke ", "replace ", "merge ", "call ",
        "execute ", "exec ", "copy ", "vacuum ", "comment "
    ]

    if any(keyword in sql_clean for keyword in forbidden_keywords):
        return False

    if not sql_clean.startswith("select"):
        return False

    if not any(table in sql_clean for table in ALLOWED_TABLES):
        return False

    return True


def generate_sql_from_question(api_key: str, user_question: str) -> str:
    client = create_client(api_key)

    prompt = f"""
You are a PostgreSQL SQL assistant.

Convert the user's question into ONE PostgreSQL SELECT query.

Strict rules:
1. Use ONLY these tables:
   - consolidated_invoices
   - invoices_metadata
   - reference_data
2. Return ONLY one SQL SELECT query
3. Never return INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE
4. Use JOIN when needed
5. If the user asks for detailed rows, limit to 100 rows unless they explicitly ask for all
6. Prefer clear aliases
7. If the user asks for totals, averages, top items, comparisons, or trends, use SQL aggregation
8. If date grouping is needed, use upload_date
9. If the question is about invoice totals, invoices_metadata is usually the preferred table
10. If the question is about tax, discount, or cost reference, use reference_data
11. If the question is about item-level invoice data, use consolidated_invoices
12. Return only raw SQL, no explanation, no markdown

Schema:
{SCHEMA_DESCRIPTION}

User question:
{user_question}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    sql = extract_sql_from_response(response.text)
    return sql


def run_safe_query(engine, sql: str) -> pd.DataFrame:
    if not is_safe_select_query(sql):
        raise ValueError("Unsafe or invalid SQL generated.")

    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


def prepare_df_for_json(df: pd.DataFrame, max_rows: int = 50) -> str:
    if df.empty:
        return "[]"

    sample_df = df.head(max_rows).copy()

    for col in sample_df.columns:
        if "date" in col.lower():
            try:
                sample_df[col] = sample_df[col].astype(str)
            except Exception:
                pass

    return sample_df.to_json(orient="records", indent=2)


def answer_general_app_question(api_key: str, user_question: str) -> str:
    client = create_client(api_key)

    prompt = f"""
You are an assistant for a Streamlit AI Invoice Profit Analyzer app.

Use the app context below to answer the user's question clearly.
Do not invent features not mentioned.
If something depends on custom calculator logic, say that it depends on the app's calculation function.

App context:
{APP_CONTEXT}

User question:
{user_question}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text.strip()


def answer_from_sql_results(api_key: str, user_question: str, sql: str, df: pd.DataFrame) -> str:
    client = create_client(api_key)

    results_json = prepare_df_for_json(df)

    prompt = f"""
You are an app data assistant.

App context:
{APP_CONTEXT}

User question:
{user_question}

SQL used:
{sql}

Returned rows count:
{len(df)}

Returned data sample:
{results_json}

Instructions:
1. Answer directly and clearly
2. If no rows are returned, say no matching data was found
3. Mention totals, averages, top items, dates, file names, and invoice IDs clearly when relevant
4. Do not invent values
5. Keep the answer business-friendly
6. Summarize the result instead of dumping raw rows
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text.strip()


def ask_app_question(api_key: str, engine, user_question: str):
    if is_general_app_question(user_question):
        answer = answer_general_app_question(api_key, user_question)
        return {
            "mode": "app_help",
            "sql": None,
            "df": pd.DataFrame(),
            "answer": answer
        }

    sql = generate_sql_from_question(api_key, user_question)
    df = run_safe_query(engine, sql)
    answer = answer_from_sql_results(api_key, user_question, sql, df)

    return {
        "mode": "database",
        "sql": sql,
        "df": df,
        "answer": answer
    }