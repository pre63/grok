import concurrent.futures
import json
import time
from datetime import datetime, timedelta

import jwt
from flask import Response, jsonify, request, send_file, send_from_directory

from .api import build_xai_chat
from .config import HASHED_PASSWORD, S3_BUCKET, SECRET_KEY, USERNAME, s3
from .grok_researcher import perform_research_mode
from .security import hash_password
from .storage import delete_chat, generate_id, get_chat, list_chats, save_chat
from .streaming import _handle_non_streaming, _handle_streaming


def register_routes(app):
  # Static routes
  @app.route("/<path:filename>")
  def serve_docs(filename):
    return send_from_directory("docs", filename)

  @app.route("/")
  @app.route("/new", methods=["GET"])
  def serve_html():
    return send_file("docs/index.html")

  # Chat CRUD
  @app.route("/chat/<chat_id>", methods=["GET", "POST", "DELETE"])
  def handle_chat(chat_id):
    if request.method == "GET" and not request.headers.get("Authorization"):
      return send_file("docs/index.html")

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
      jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except:
      return jsonify({"error": "Invalid token"}), 401

    key = f"{chat_id}.json"

    if request.method == "GET":
      try:
        chat = get_chat(key)
        return jsonify(chat)
      except Exception as e:
        print("there was an exception", e)
        return jsonify({"messages": [], "title": "Untitled Chat"})

    elif request.method == "POST":
      data = request.json
      save_chat(key, data)
      return jsonify({"success": True})

    elif request.method == "DELETE":
      delete_chat(key)
      return jsonify({"success": True})

  # Auth
  @app.route("/login", methods=["POST"])
  def login():
    data = request.json
    if hash_password(data.get("password", "")) != HASHED_PASSWORD or data.get("username") != USERNAME:
      return jsonify({"error": "Invalid credentials"}), 401
    payload = {"username": USERNAME, "exp": datetime.utcnow() + timedelta(minutes=60 * 24 * 365)}
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return jsonify({"token": token})

  @app.route("/verify", methods=["GET"])
  def verify():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
      data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
      if data.get("username") == USERNAME:
        return jsonify({"username": USERNAME})
      else:
        return jsonify({"error": "Invalid token"}), 401
    except:
      return jsonify({"error": "Invalid token"}), 401

  # Chat list
  @app.route("/chats", methods=["GET"])
  def list_chats_handler():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
      jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except:
      return jsonify({"error": "Invalid token"}), 401

    try:
      chats = list_chats()

      return jsonify(chats)
    except Exception as e:
      print(f"List chats error: {e}")
      return jsonify({"error": "Failed to list chats"}), 500

  # Main completions endpoint
  @app.route("/chat/completions", methods=["POST"])
  def chat_completions():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
      jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except:
      return jsonify({"error": "Invalid token"}), 401

    data = request.json
    chat_id = data.get("chat_id")
    new_messages = data.get("messages", [])
    model = data.get("model", "grok-4-1-fast-reasoning")
    temperature = data.get("temperature", 0.7)
    max_tokens = data.get("max_tokens", 8192)
    stream = data.get("stream", False)
    use_tools = data.get("use_tools", True)

    if not new_messages:
      if stream:
        return Response("data: [DONE]\n\n", mimetype="text/event-stream")
      return jsonify(
        {
          "id": generate_id(),
          "object": "chat.completion",
          "created": int(time.time()),
          "model": model,
          "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop no stream"}],
        }
      )

    is_new_chat = chat_id is None
    if is_new_chat:
      chat_id = generate_id()
    key = f"{chat_id}.json"

    try:
      chat = get_chat(key)
      messages = chat["messages"]
      stored_title = chat["title"]

    except Exception:
      messages = []
      stored_title = None

    if is_new_chat:
      messages = []
      user_content = next((m.get("content", "") for m in new_messages if m.get("role") == "user"), "")

    for m in new_messages:
      if "id" not in m:
        m["id"] = generate_id()
    messages.extend(new_messages)

    save_chat(key, {"messages": messages})

    cmpl_id = generate_id()
    created = int(time.time())

    # Grok Researcher
    if model == "grok-research":
      real_model = "grok-4-1-fast-reasoning"
      user_content = next((m.get("content", "") for m in new_messages if m.get("role") == "user"), "")
      synthesis_content = perform_research_mode(user_content, messages, key, real_model, temperature, max_tokens)
      synthesis_msg = {"id": generate_id(), "role": "assistant", "content": synthesis_content}
      messages.append(synthesis_msg)
      save_chat(key, {"messages": messages})

      if stream:
        return researcher_streaming(synthesis_content, chat_id, is_new_chat, model, cmpl_id, created)
      return jsonify(
        {
          "id": cmpl_id,
          "object": "chat.completion",
          "created": created,
          "model": model,
          "choices": [{"message": synthesis_msg, "finish_reason": "stop", "index": 0}],
        }
      )

    # Normal flow
    chat = build_xai_chat(messages, new_messages, model, temperature, max_tokens, use_tools)
    if stream:
      return _handle_streaming(chat, chat_id, messages, is_new_chat, model, cmpl_id, created, key)
    return _handle_non_streaming(chat, messages, model, cmpl_id, created, key)
