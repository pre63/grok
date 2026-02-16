import hashlib
import json
import os
import random
import string
import time
from operator import itemgetter

import boto3
import jwt
from botocore.exceptions import ClientError
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS
from xai_sdk import Client
from xai_sdk.chat import assistant, system, tool, user
from xai_sdk.tools import code_execution, web_search, x_search

app = Flask(__name__)
CORS(app)

SECRET_KEY = os.environ.get("SECRET_KEY", "a-very-long-secret-key-at-least-32-bytes-long-for-security")
S3_BUCKET = os.environ.get("S3_BUCKET", "xai-chatbot-chats")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
USERNAME = os.environ.get("USERNAME", "user")
PASSWORD = os.environ.get("PASSWORD")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)

HASHED_PASSWORD = hashlib.sha256(PASSWORD.encode()).hexdigest() if PASSWORD else None


@app.route("/manifest.json")
def manifest():
  return send_file("docs/manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
  return send_file("docs/sw.js", mimetype="application/javascript")


def hash_password(password):
  return hashlib.sha256(password.encode()).hexdigest()


def generate_id():
  return "chatcmpl-" + "".join(random.choices(string.ascii_letters + string.digits, k=29))


@app.route("/")
def serve_html():
  return send_file("docs/index.html")


@app.route("/login", methods=["POST"])
def login():
  data = request.json
  username = data.get("username")
  password = hash_password(data.get("password", ""))

  if username != USERNAME or password != HASHED_PASSWORD:
    return jsonify({"error": "Invalid credentials"}), 401

  token = jwt.encode({"username": USERNAME}, SECRET_KEY)
  return jsonify({"token": token})


@app.route("/verify", methods=["GET"])
def verify():
  token = request.headers.get("Authorization", "").replace("Bearer ", "")
  try:
    data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    if data["username"] != USERNAME:
      raise ValueError
    return jsonify({"username": USERNAME})
  except:
    return jsonify({"error": "Invalid token"}), 401


@app.route("/chats", methods=["GET"])
def list_chats():
  token = request.headers.get("Authorization", "").replace("Bearer ", "")
  try:
    data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    if data["username"] != USERNAME:
      raise ValueError
  except:
    return jsonify({"error": "Invalid token"}), 401

  try:
    response = s3.list_objects_v2(Bucket=S3_BUCKET, Delimiter="/")
    chat_list = []
    for obj in response.get("Contents", []):
      if obj["Key"].endswith(".json"):
        chat_id = obj["Key"].replace(".json", "")
        obj_data = s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])
        chat_data = json.loads(obj_data["Body"].read())
        chat_list.append({"id": chat_id, "title": chat_data.get("title", "Untitled"), "last_modified": obj["LastModified"].isoformat()})
    chat_list.sort(key=itemgetter("last_modified"), reverse=True)
    return jsonify(chat_list)
  except ClientError as e:
    app.logger.error(f"Error listing chats: {e}")
    return jsonify({"error": "Failed to list chats"}), 500


@app.route("/chat/<chat_id>", methods=["GET", "POST", "DELETE"])
def handle_chat(chat_id):
  token = request.headers.get("Authorization", "").replace("Bearer ", "")
  try:
    data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    if data["username"] != USERNAME:
      raise ValueError
  except:
    return jsonify({"error": "Invalid token"}), 401

  key = f"{chat_id}.json"
  if request.method == "GET":
    try:
      obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
      return jsonify(json.loads(obj["Body"].read()))
    except ClientError as e:
      if e.response["Error"]["Code"] == "NoSuchKey":
        return jsonify({"messages": []})
      app.logger.error(f"Error getting chat: {e}")
      return jsonify({"error": "Failed to get chat"}), 500

  elif request.method == "POST":
    data = request.json
    try:
      s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(data))
      return jsonify({"success": True})
    except ClientError as e:
      app.logger.error(f"Error saving chat: {e}")
      return jsonify({"error": "Failed to save chat"}), 500

  elif request.method == "DELETE":
    try:
      s3.delete_object(Bucket=S3_BUCKET, Key=key)
      return jsonify({"success": True})
    except ClientError as e:
      app.logger.error(f"Error deleting chat: {e}")
      return jsonify({"error": "Failed to delete chat"}), 500


@app.route("/chat/completions", methods=["POST"])
def chat_completions():
  token = request.headers.get("Authorization", "").replace("Bearer ", "")
  try:
    data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    if data["username"] != USERNAME:
      raise ValueError
  except:
    return jsonify({"error": "Invalid token"}), 401

  data = request.json
  messages = data.get("messages", [])
  model = data.get("model", "grok-4-1-fast-reasoning")
  temperature = data.get("temperature", 0.7)
  max_tokens = data.get("max_tokens", 8192)
  stream = data.get("stream", True)
  use_tools = data.get("use_tools", True)

  def stream_response():
    client = Client(api_key=XAI_API_KEY)
    tools_list = (
      [
        web_search(),
        x_search(),
        code_execution(),
      ]
      if use_tools
      else []
    )
    chat = client.chat.create(model=model, temperature=temperature, max_tokens=max_tokens, tools=tools_list, include=["verbose_streaming"])

    for msg in messages:
      role = msg.get("role")
      content = msg.get("content")
      if role == "system":
        chat.append(system(content))
      elif role == "user":
        chat.append(user(content))
      elif role == "assistant":
        chat.append(assistant(content))
      elif role == "tool":
        chat.append(tool(tool_call_id=msg.get("tool_call_id"), name=msg.get("name"), content=content))

    cmpl_id = generate_id()
    created = int(time.time())

    while True:
      tool_calls_buffer = []
      content_buffer = ""
      citations = None

      for response, chunk in chat.stream():
        chunk_data = {
          "id": cmpl_id,
          "object": "chat.completion.chunk",
          "created": created,
          "model": model,
          "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        }
        delta = chunk_data["choices"][0]["delta"]

        if hasattr(chunk, "tool_calls") and chunk.tool_calls:
          for tc in chunk.tool_calls:
            tc_index = next((i for i, b in enumerate(tool_calls_buffer) if b["id"] == tc.id), len(tool_calls_buffer))
            if tc_index == len(tool_calls_buffer):
              tool_calls_buffer.append({"id": tc.id if tc.id else generate_id("call_"), "type": "function", "function": {"name": "", "arguments": ""}})
            if tc.function.name:
              tool_calls_buffer[tc_index]["function"]["name"] += tc.function.name
            if tc.function.arguments:
              tool_calls_buffer[tc_index]["function"]["arguments"] += tc.function.arguments
          delta["tool_calls"] = [
            {"index": i, "id": tc["id"], "type": "function", "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
            for i, tc in enumerate(tool_calls_buffer)
          ]

        if hasattr(chunk, "content") and chunk.content:
          content_buffer += chunk.content
          delta["content"] = chunk.content

        if hasattr(response, "citations"):
          citations = response.citations

        yield f"data: {json.dumps(chunk_data)}\n\n"

      # After stream ends, send final chunk with finish_reason
      finish_reason = "tool_calls" if tool_calls_buffer else "stop"
      chunk_data = {
        "id": cmpl_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
      }
      yield f"data: {json.dumps(chunk_data)}\n\n"

      if finish_reason != "tool_calls":
        break

      # Append assistant message
      if tool_calls_buffer:
        if content_buffer:
          chat.append(assistant(content_buffer))
        chat.append(assistant(tool_calls=tool_calls_buffer))
      else:
        chat.append(assistant(content_buffer))

      # Execute tools
      for tc in tool_calls_buffer:
        function_name = tc["function"]["name"]
        try:
          args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
          content = "Invalid arguments provided."
        else:
          try:
            if function_name == web_search.name:
              content = web_search(**args)
            elif function_name == x_search.name:
              content = x_search(**args)
            elif function_name == code_execution.name:
              content = code_execution(**args)
            else:
              content = "Unknown tool."
          except Exception as e:
            content = f"Tool execution error: {str(e)}"
        chat.append(tool(tool_call_id=tc["id"], name=function_name, content=json.dumps(content) if not isinstance(content, str) else content))

    yield "data: [DONE]\n\n"

  return Response(stream_response(), mimetype="text/event-stream")


if __name__ == "__main__":
  from waitress import serve

  if os.environ.get("DEV"):
    app.run(debug=True)
  else:
    serve(app, host="0.0.0.0", port=5000)
