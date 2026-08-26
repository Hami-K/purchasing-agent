import base64
import json
import os
import re

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import get_setting

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash", temperature=0, google_api_key=get_setting("GOOGLE_API_KEY")
)

_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

PROMPT = """You are digitizing a scanned/photographed internal supplier price \
comparison sheet (Hilton-style hotel purchasing format). The sheet has multiple \
supplier columns side by side. Each item row shows, per supplier: Packing, \
Brand, Origin, and Price (some suppliers show an Old and New price pair with \
a percent change instead of a single price). The number of suppliers and the \
number of items both vary per sheet.

The sheet may also show a totals block below the item rows (Total, Discount, \
Sub Total, VAT, Grand Total, Lead time, Payment terms per supplier) — ignore \
that part entirely, it is not needed.

Read the document carefully and extract every item row. Return ONLY strict \
JSON — no markdown code fences, no commentary, no trailing text — matching \
EXACTLY this shape:

{
  "items": [
    {
      "item_description": "<string>",
      "yearly_consumption": "<string or null>",
      "suppliers": [
        {
          "supplier_name": "<string>",
          "packing": "<string or null>",
          "brand": "<string or null>",
          "origin": "<string or null>",
          "unit_price": <number>,
          "old_price": <number or null>,
          "percent_change": <number or null>
        }
      ]
    }
  ]
}

Use the exact supplier name as printed on the sheet — consistency across \
items matters, so use the identical supplier_name string everywhere that \
supplier appears. If a value is illegible or absent, use null rather than \
guessing."""


def _guess_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return _MIME_TYPES.get(ext, "image/jpeg")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def extract_quote(file_path: str) -> dict:
    """
    Sends a photographed/scanned comparison sheet (image or PDF, given as a
    file path) to Gemini vision and returns the parsed structure:
    {"items": [...]}.

    Handles .content coming back as a list of blocks instead of a plain
    string. Raises ValueError (with the raw model response attached) if
    the reply isn't valid JSON, or is missing the expected top-level keys
    — never returns partial/guessed data silently.
    """
    mime_type = _guess_mime_type(file_path)
    with open(file_path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode("utf-8")

    message = HumanMessage(content=[
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": f"data:{mime_type};base64,{data_b64}"},
    ])

    raw_content = llm.invoke([message]).content
    if isinstance(raw_content, list):
        response = "".join(
            block["text"] if isinstance(block, dict) else str(block)
            for block in raw_content
        )
    else:
        response = raw_content

    cleaned = _strip_code_fence(response)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini did not return valid JSON ({e}). Raw response:\n\n{response}"
        ) from e

    if "items" not in parsed:
        raise ValueError(
            f"Gemini's JSON is missing 'items'. Raw response:\n\n{response}"
        )

    return parsed
