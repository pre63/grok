from typing import Any, Dict, Generator, List, Optional

from xai_sdk import Client
from xai_sdk.chat import assistant, system, user
from xai_sdk.tools import web_search, x_search

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
  stream_output: bool = False,  # New: If True, call sample() and return a streaming generator
) -> Any:  # Returns chat (non-streaming) or Generator[str] (streaming)
  client = Client(api_key=XAI_API_KEY)
  tools_list = [web_search(), x_search()] if use_tools else []
  last_response_id = get_last_assistant_id(messages)

  kwargs = {
    "model": model,
    "temperature": temperature,
    "max_tokens": max_tokens,
    "tools": tools_list,
    "include": ["verbose_streaming", "inline_citations"],
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

  if not stream_output:
    return chat  # Return the built chat for external sampling

  # Streaming: Call sample() and yield chunks (assumes SDK streams via verbose_streaming)
  def stream_generator():
    try:
      response = chat.sample()  # Assuming sample() returns a streamable response
      # Yield content chunks (adapt based on exact SDK response structure)
      for chunk in response:  # If response is iterable (e.g., yields deltas)
        if hasattr(chunk, "content"):
          yield chunk.content
        elif isinstance(chunk, dict) and "delta" in chunk:
          yield chunk["delta"].get("content", "")
    except Exception as e:
      print(f"Streaming failed: {e}")
      yield f"Error: {str(e)}"

  return stream_generator()
