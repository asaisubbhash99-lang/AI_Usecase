import json
import re
from google import genai
from google.genai import types
import pandas as pd

def load_stock_prices(stock_file):
    """
    Load the stock data (cost prices and stock quantities) from CSV.
    """
    stock_df = pd.read_csv(stock_file)
    stock_prices = stock_df.set_index("item_name")[["cost_price", "stock_quantity"]].to_dict(orient="index")
    return stock_prices


def load_tax_discount(tax_discount_file):
    """
    Load the tax and discount data from CSV.
    """
    tax_discount_df = pd.read_csv(tax_discount_file)
    tax_discount = tax_discount_df.set_index("item_name")[["tax_rate", "discount_percentage"]].to_dict(orient="index")
    return tax_discount

def generate_calculation_prompt(items, stock_prices, tax_discount):
    prompt = f"""
You are a finance assistant. Calculate financial metrics based on the provided data.

### CALCULATION RULES:
1. Total Price = sold_price * Quantity
2. Tax Amount = Total Price * (tax_rate / 100)
3. Discount Amount = Total Price * (discount_percentage / 100)
4. Final Price (Revenue) = Total Price - Discount Amount + Tax Amount
5. Profit = Final Price - (cost_price * Quantity)
6. Stock Status = "OK" if cost_price exists, else "Missing Cost"

### DATA:
Invoice Items:
{json.dumps(items)}

Tax/Discount Rates:
{json.dumps(tax_discount)}

Stock/Cost Data:
{json.dumps(stock_prices)}

### IMPORTANT
For every item, show the full calculation steps.

### OUTPUT FORMAT (RETURN ONLY JSON):

{{
 "results":[
   {{
     "item_name":"string",
     "sold_price":number,
     "Qty":number,
     "cost_price":number,
     "tax_rate":number,
     "discount_percentage":number,

     "calculation_steps":[
        "Total Price = sold_price * Qty",
        "Tax Amount = Total Price * tax_rate /100",
        "Discount = Total Price * discount_percentage /100",
        "Final Price = Total Price - Discount + Tax",
        "Profit = Final Price - (cost_price * Qty)"
     ],

     "total_price":number,
     "tax_amount":number,
     "discount_amount":number,
     "final_price":number,
     "profit":number,
     "stock_status":"string"
   }}
 ],
 "total_profit":number,
 "total_cost":number,
 "total_revenue":number
}}
"""
    return prompt

def calculate_profit_gemini(api_key, items, stock_prices, tax_discount):
    """
    Calculate the profit using Gemini AI.

    Returns:
        results: List[Dict] with fields: item_name, sold_price, Qty, cost_price, tax_amount, discount_percentage, revenue, profit, margin, stock_status
        total_profit, total_cost, total_revenue
    """
    # Initialize Gemini client with the provided API key
    client = genai.Client(api_key=api_key)

    # Generate the AI prompt with provided data
    prompt = generate_calculation_prompt(items, stock_prices, tax_discount)

    try:
        # Send the prompt to Gemini AI and get the response
        response = client.models.generate_content(
            model="gemini-flash-latest",  # Specify the model to use
            contents=[prompt]
        )

        text = response.text

        # Extract JSON object from AI response
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            data = {
                "results": [],
                "total_profit": 0,
                "total_cost": 0,
                "total_revenue": 0
            }

        # Return the results along with total profit, cost, and revenue
        return data.get("results", []), data.get("total_profit", 0), data.get("total_cost", 0), data.get("total_revenue", 0)

    except Exception as e:
        print("❌ AI ERROR:", e)
        return [], 0, 0, 0