from typing import Any, Dict, List, Optional

from xai_sdk import Client
from xai_sdk.chat import assistant, system, user
from xai_sdk.tools import code_execution, web_search, x_search

from .config import SYSTEM_PROMPT, XAI_API_KEY


def get_last_assistant_id(messages: List[Dict]) -> Optional[str]:
  for m in reversed(messages):
    if m.get("role") == "assistant" and "id" in m:
      return m["id"]
  return None


def build_xai_chat(
  messages: List[Dict],
  new_messages: List[Dict],
  model: str,
  temperature: float,
  max_tokens: int,
  use_tools: bool,
) -> Any:
  client = Client(api_key=XAI_API_KEY)
  tools_list = [web_search(), x_search(), code_execution()] if use_tools else []
  last_response_id = get_last_assistant_id(messages)

  kwargs = {
    "model": model,
    "temperature": temperature,
    "max_tokens": max_tokens,
    "tools": tools_list,
    "include": ["verbose_streaming"],
    "store_messages": True,
  }
  if last_response_id:
    kwargs["previous_response_id"] = last_response_id

  try:
    chat = client.chat.create(**kwargs)
  except Exception as e:
    print(f"xAI chat create failed: {e}. Falling back...")
    kwargs.pop("previous_response_id", None)
    chat = client.chat.create(**kwargs)

  if last_response_id is None:
    chat.append(system(SYSTEM_PROMPT))
    for m in messages:
      if m.get("role") == "user":
        chat.append(user(m.get("content")))
      elif m.get("role") == "assistant":
        chat.append(assistant(m.get("content")))
  else:
    for m in new_messages:
      if m.get("role") == "user":
        chat.append(user(m.get("content")))
      elif m.get("role") == "assistant":
        chat.append(assistant(m.get("content")))
  return chat
