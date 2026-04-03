import json
import random
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, TypedDict

from botocore.exceptions import ClientError

from .config import S3_BUCKET, s3
from .title import get_good_title


class ChatMessage(TypedDict):
  role: str
  content: str


class Chat(TypedDict):
  id: str
  title: str
  updated_at: float
  messages: Optional[List[ChatMessage]]  # None when listing


def generate_id() -> str:
  return "".join(random.choices(string.ascii_letters + string.digits, k=29))


def get_chat(key: str) -> Chat:
  chat_id = key.replace(".json", "")

  try:
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    data = json.loads(obj["Body"].read())

    messages = data.get("messages", [])
    title = data.get("title", "New Chat")

    messages = [m for m in messages if m.get("role") != "system"]

    return {
      "id": chat_id,
      "title": title,
      "updated_at": obj["LastModified"].timestamp(),
      "messages": messages,
    }

  except ClientError as e:
    if e.response["Error"]["Code"] == "NoSuchKey":
      return {
        "id": chat_id,
        "title": "New Chat",
        "updated_at": 0,
        "messages": [],
      }
    raise


# =========================
# Save Chat
# =========================


def save_chat(key: str, data: Dict[str, Any]) -> None:
  messages = data.get("messages", [])
  proposed_title = data.get("title")

  # if ttile none get title from storage
  if proposed_title is None:
    proposed_title = get_chat(key)["title"]

  title = get_good_title(key, messages, proposed_title)
  data["title"] = title

  try:
    s3.put_object(
      Bucket=S3_BUCKET,
      Key=key,
      Body=json.dumps(data),
      Metadata={"title": title},
    )
  except ClientError as e:
    print(f"S3 save failed for {key}: {e}")


# =========================
# Delete Chat
# =========================


def delete_chat(key: str) -> None:
  try:
    s3.delete_object(Bucket=S3_BUCKET, Key=key)
  except Exception:
    pass


# =========================
# Internal: Build Chat Preview
# =========================


def _build_chat(item) -> Chat:
  key = item["Key"]
  chat_id = key.replace(".json", "")

  title = "New Chat"

  try:
    head = s3.head_object(Bucket=S3_BUCKET, Key=key)
    title = head.get("Metadata", {}).get("title", "New Chat")
  except Exception:
    pass

  return {
    "id": chat_id,
    "title": title,
    "updated_at": item["LastModified"].timestamp(),
    "messages": None,  # 👈 important
  }


# =========================
# List Chats (FAST)
# =========================


def list_chats() -> List[Chat]:
  """
    Returns chats WITHOUT messages (messages=None).
    """
  try:
    response = s3.list_objects_v2(Bucket=S3_BUCKET)
    items = response.get("Contents", [])

    if not items:
      return []

    chats: List[Chat] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
      futures = [executor.submit(_build_chat, item) for item in items]

      for future in as_completed(futures):
        try:
          chats.append(future.result())
        except Exception:
          continue

    chats.sort(key=lambda x: x["updated_at"], reverse=True)

    return chats

  except Exception:
    return []
