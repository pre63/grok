import json
import time
from queue import Queue
from threading import Thread
from typing import Any

from flask import Response, jsonify

from .storage import save_chat


def _handle_streaming(chat, chat_id, messages, is_new_chat, model, cmpl_id, created, key):
  q = Queue()

  def worker():
    content_buffer = ""
    finish_reason = "stop"
    response_id = None
    try:
      for api_response, chunk in chat.stream():
        if response_id is None and hasattr(api_response, "id") and api_response.id:
          response_id = api_response.id
        if hasattr(chunk, "content") and chunk.content:
          content_buffer += chunk.content
          q.put(
            {
              "id": cmpl_id,
              "object": "chat.completion.chunk",
              "created": created,
              "model": model,
              "choices": [{"index": 0, "delta": {"content": chunk.content}, "finish_reason": None}],
            }
          )
      assistant_msg = {
        "id": response_id or generate_id(),
        "role": "assistant",
        "content": content_buffer,
      }
      messages.append(assistant_msg)
      save_chat(key, {"messages": messages})
    except Exception as e:
      print(f"Streaming error: {e}")
      finish_reason = "error"
      q.put(
        {
          "id": cmpl_id,
          "object": "chat.completion.chunk",
          "created": created,
          "model": model,
          "choices": [{"index": 0, "delta": {"content": f"Error: {str(e)}"}, "finish_reason": "error"}],
        }
      )
    finally:
      q.put(
        {
          "id": cmpl_id,
          "object": "chat.completion.chunk",
          "created": created,
          "model": model,
          "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
        }
      )
      q.put(None)

  Thread(target=worker, daemon=True).start()

  def stream_response():
    if is_new_chat:
      yield f"data: {json.dumps({'chat_id': chat_id})}\n\n"
    while True:
      item = q.get()
      if item is None:
        yield "data: [DONE]\n\n"
        break
      yield f"data: {json.dumps(item)}\n\n"

  return Response(stream_response(), mimetype="text/event-stream")


def _handle_non_streaming(chat, messages, model, cmpl_id, created, key):
  try:
    response = chat.sample()
    content = getattr(response, "content", "No response from underlying model")
    assistant_msg = {"id": response.id, "role": "assistant", "content": content}
    messages.append(assistant_msg)
    save_chat(key, {"messages": messages})
    return jsonify(
      {
        "id": cmpl_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"message": assistant_msg, "finish_reason": "stop", "index": 0}],
      }
    )
  except Exception as e:
    print(f"Non-streaming error: {e}")
    return (
      jsonify(
        {
          "id": cmpl_id,
          "object": "chat.completion",
          "created": created,
          "model": model,
          "choices": [{"message": {"role": "assistant", "content": f"Error: {str(e)}"}, "finish_reason": "error"}],
        }
      ),
      500,
    )
