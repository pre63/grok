import json
import random
import string
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from xai_sdk import Client
from xai_sdk.chat import assistant, system, user

from .config import SYSTEM_PROMPT, XAI_API_KEY


def generate_title_with_grok(user_content: str) -> str:
  try:
    client = Client(api_key=XAI_API_KEY)
    title_chat = client.chat.create(
      model="grok-4-1-fast-reasoning",
      temperature=0.7,
      max_tokens=64,
      store_messages=False,
    )
    title_chat.append(
      system("You are an expert title generator. Reply with ONLY a short, catchy, descriptive title (3-60 chars). No quotes, no explanation, no extra text.")
    )
    title_chat.append(user(f"First user message: {user_content[:1000]}"))
    response = title_chat.sample()
    content = getattr(response, "content", "") or ""
    cleaned = str(content).strip()
    return cleaned[:100] if len(cleaned) > 3 else "New Conversation"
  except Exception as e:
    print(f"Title generation failed: {e}")
    return "New Conversation"


def get_good_title(key: str, messages: List[Dict], proposed_title: Optional[str]) -> str:
  bad_titles = {"New Chat", "New Conversation", "", None}
  if proposed_title and proposed_title not in bad_titles:
    return proposed_title

  if not messages:
    return "Untitled Chat"

  user_content = next((m.get("content", "") for m in messages if m.get("role") == "user" and m.get("content")), "")
  if user_content:
    gen_title = generate_title_with_grok(user_content)
    if gen_title and gen_title not in bad_titles:
      return gen_title

  return f"Untitled Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
