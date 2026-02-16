import hashlib
import json
import os
from operator import itemgetter

import boto3
import jwt
from botocore.exceptions import ClientError
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

SECRET_KEY = os.environ.get("SECRET_KEY", "a-very-long-secret-key-at-least-32-bytes-long-for-security")  # Longer default
S3_BUCKET = os.environ.get("S3_BUCKET", "xai-chatbot-chats")  # Default bucket name
XAI_API_KEY = os.environ.get("XAI_API_KEY")  # xAI API key from env
USERNAME = os.environ.get("USERNAME", "user")  # Fixed username from env
PASSWORD = os.environ.get("PASSWORD")  # Plain password from env, will hash
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)

HASHED_PASSWORD = hashlib.sha256(PASSWORD.encode()).hexdigest() if PASSWORD else None


def hash_password(password):
  return hashlib.sha256(password.encode()).hexdigest()


@app.route("/")
def serve_html():
  return send_file("index.html")


@app.route("/login", methods=["POST"])
def login():
  data = request.json
  username = data.get("username")
  password = hash_password(data.get("password", ""))

  if username != USERNAME or password != HASHED_PASSWORD:
    return jsonify({"error": "Invalid credentials"}), 401

  # Issue token without expiration
  token = jwt.encode({"username": USERNAME}, SECRET_KEY)
  return jsonify({"token": token, "api_key": XAI_API_KEY})


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
    # Sort by last_modified descending
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


if __name__ == "__main__":
  app.run(debug=True)
