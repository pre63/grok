# src/grok_researcher.py
import concurrent.futures
import json
import re
import time
from typing import Any, Dict, List

from xai_sdk import Client
from xai_sdk.chat import assistant, system, user
from xai_sdk.tools import code_execution, web_search, x_search

from src.config import SYSTEM_PROMPT, XAI_API_KEY

from .storage import generate_id, save_chat

# Injected from main app
app_logger = None


def init_researcher(logger=None):
  global app_logger
  app_logger = logger


def _build_research_subchat(temp_messages: List[Dict], model: str, temperature: float, max_tokens: int):
  client = Client(api_key=XAI_API_KEY)
  tools_list = [web_search(), x_search(), code_execution()]
  chat = client.chat.create(
    model=model,
    temperature=temperature,
    max_tokens=max_tokens,
    tools=tools_list,
    include=["verbose_streaming"],
    store_messages=False,
  )
  chat.append(system(SYSTEM_PROMPT))
  for m in temp_messages:
    if m.get("role") == "user":
      chat.append(user(m.get("content", "")))
    elif m.get("role") == "assistant":
      chat.append(assistant(m.get("content", "")))
  return chat


def generate_research_plan(query: str, model: str) -> Dict[str, Any]:
  # (unchanged - same neutral planner as before)
  try:
    client = Client(api_key=XAI_API_KEY)
    plan_chat = client.chat.create(
      model=model,
      temperature=0.2,
      max_tokens=4096,
      tools=[web_search(), x_search(), code_execution()],
      store_messages=False,
    )
    plan_chat.append(
      system(
        """You are Grok Researcher — a strictly neutral, thorough, and objective research assistant.
Your only role is to create a comprehensive research plan by breaking the user's query into 4-8 independent, self-contained tasks.
Each task must be designed to collect raw facts, data, papers, sources, statistics, or quotes — never to interpret or conclude.
Focus on depth and completeness. Avoid any bias, opinion, or leading language.

Reply with **ONLY** valid JSON (no extra text, no markdown, no explanation):

{
  "research_plan_summary": "1-2 sentence neutral overview of the research strategy",
  "tasks": [
    {
      "task_id": 1,
      "title": "Short neutral task title",
      "description": "Detailed, actionable instructions focused solely on gathering objective information, sources, or data"
    }
  ]
}"""
      )
    )
    plan_chat.append(user(f"Query: {query}"))
    response = plan_chat.sample()
    content = (response.content or "").strip()
    json_match = re.search(r"\{[\s\S]*\}", content)
    json_str = json_match.group(0) if json_match else content
    return json.loads(json_str)
  except Exception as e:
    if app_logger:
      app_logger.error(f"Research plan failed: {e}")
    return {
      "research_plan_summary": "Comprehensive neutral research across all relevant sources",
      "tasks": [{"task_id": 1, "title": "Full objective research", "description": f"Gather all available factual information on: {query}"}],
    }


def execute_research_task(
  original_query: str, plan_summary: str, current_messages: List[Dict], task: Dict, task_idx: int, model: str, temperature: float, max_tokens: int
) -> str:
  temp_messages = [m.copy() for m in current_messages]
  instruction = f"""**RESEARCH TASK {task_idx} — NEUTRAL FACT-FINDING ONLY**
Original query: {original_query}
Plan: {plan_summary}
Task: {task.get('title')}
{task.get('description')}

You are a neutral researcher. Collect and report only objective facts, data, statistics, quotes, paper titles, dates, authors, and direct findings.
Do not interpret, analyze, opine, or draw any conclusions.
Use all available tools. Be thorough and precise."""
  temp_messages.append({"role": "user", "content": instruction})

  sub_chat = _build_research_subchat(temp_messages, model, temperature, max_tokens)
  try:
    resp = sub_chat.sample()
    return resp.content or "No content received."
  except Exception as e:
    if app_logger:
      app_logger.error(f"Task {task_idx} failed: {e}")
    return f"Task error: {str(e)}"


def generate_synthesis(original_query: str, plan_summary: str, current_messages: List[Dict], model: str, temperature: float, max_tokens: int) -> str:
  # (unchanged - long neutral synthesis)
  temp_messages = [m.copy() for m in current_messages]
  instruction = f"""**FINAL SYNTHESIS — COMPLETE NEUTRAL SUMMARY**

You are Grok Researcher. Your role is to produce a thorough, objective, and complete synthesis of all previous task findings.

Structure the response like a detailed academic paper abstract or executive summary, but significantly longer and more comprehensive:

1. Begin with a one-sentence restatement of the original query.
2. Present every key factual finding from the tasks, organized logically by topic or theme.
3. Highlight notable facts, statistics, dates, quotes, paper titles, authors, methodologies, and results exactly as they were reported — without any interpretation.
4. Relate the information neutrally and as-is. Do not analyze, compare, critique, or infer implications.
5. Be exhaustive: include all significant details uncovered across every task.

Do NOT add any conclusions, recommendations, opinions, or closing statements. Let the reader perform their own analysis and decision-making.

Use clear, precise, neutral language. Aim for maximum completeness and factual density."""
  temp_messages.append({"role": "user", "content": instruction})

  sub_chat = _build_research_subchat(temp_messages, model, temperature, max_tokens)
  try:
    resp = sub_chat.sample()
    return resp.content or "Synthesis complete."
  except Exception as e:
    if app_logger:
      app_logger.error(f"Synthesis failed: {e}")
    return f"Synthesis error: {str(e)}"


def perform_research_mode(original_query: str, messages: List[Dict], key: str, model: str, temperature: float, max_tokens: int) -> str:
  """Main entry point — now with full parallel task execution."""
  plan = generate_research_plan(original_query, model)
  tasks = plan.get("tasks", [])
  plan_summary = plan.get("research_plan_summary", "")

  if not tasks:
    tasks = [{"task_id": 1, "title": "Full research", "description": f"Research: {original_query}"}]

  # === PARALLEL EXECUTION ===
  results = []  # list of (task_idx, content)

  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    future_to_idx = {
      executor.submit(execute_research_task, original_query, plan_summary, messages, task, idx, model, temperature, max_tokens): idx
      for idx, task in enumerate(tasks, 1)
    }

    for future in concurrent.futures.as_completed(future_to_idx):
      idx = future_to_idx[future]
      try:
        content = future.result()
      except Exception as e:
        content = f"Task error: {e}"
      results.append((idx, content))

  # Sort results to preserve original task order (1, 2, 3...)
  results.sort(key=lambda x: x[0])

  # Append each task to chat history + incremental save
  for idx, content in results:
    # Find original task to get title
    task = next((t for t in tasks if t.get("task_id") == idx), {"title": f"Task {idx}"})
    messages.append({"id": generate_id(), "role": "assistant", "content": f"**Task {idx}: {task.get('title', f'Task {idx}')}**\n\n{content}"})
    save_chat(key, {"messages": messages})

  # === SYNTHESIS ONLY AFTER ALL TASKS FINISH ===
  synthesis = generate_synthesis(original_query, plan_summary, messages, model, temperature, max_tokens)
  return synthesis


def _handle_research_streaming(synthesis_content: str, chat_id: str, is_new_chat: bool, model: str, cmpl_id: str, created: int):
  def stream_response():
    if is_new_chat:
      yield f"data: {json.dumps({'chat_id': chat_id})}\n\n"
    chunk_size = 80
    for i in range(0, len(synthesis_content or ""), chunk_size):
      chunk = synthesis_content[i : i + chunk_size]
      yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]} ) }\n\n"
      time.sleep(0.012)
    yield f"data: {json.dumps({'id': cmpl_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}] }) }\n\n"
    yield "data: [DONE]\n\n"

  from flask import Response

  return Response(stream_response(), mimetype="text/event-stream")
