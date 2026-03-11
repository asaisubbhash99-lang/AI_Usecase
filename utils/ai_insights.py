from google import genai
import json


def generate_profit_insights(api_key, results):

    client = genai.Client(api_key=api_key)

    prompt = f"""
You are a senior business analyst.

Analyze the following sales and stock cost data.

Data:
{json.dumps(results, indent=2)}

Provide insights:

1. Most profitable product
2. Least profitable product
3. Highest profit margin product
4. Products with low margin
5. Stock risks (missing cost prices)
6. Recommendations to increase profit

Keep the response short and clear.
"""

    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt
    )

    return response.text