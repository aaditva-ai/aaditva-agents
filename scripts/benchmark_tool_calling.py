import urllib.request
import json
import time
import psutil

url = "http://localhost:1234/v1/chat/completions"

tools_definition = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read content from a specified file path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to read"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": "Replace text in a specified file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "search": {"type": "string"},
                    "replace": {"type": "string"}
                },
                "required": ["path", "search", "replace"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"]
            }
        }
    }
]

prompt_tool_test = "I need to inspect the contents of the UI component in 'web/src/App.tsx'. Please read this file for me using appropriate tools."

def test_active_model():
    req = urllib.request.Request("http://localhost:1234/v1/models")
    with urllib.request.urlopen(req) as resp:
        models_info = json.loads(resp.read().decode("utf-8"))
        models = [m["id"] for m in models_info.get("data", []) if "nomic" not in m["id"]]

    if not models:
        print("No active models found in LM Studio!")
        return

    model_name = models[0]
    print(f"\n==========================================")
    print(f"Testing Tool-Calling & Speculative Benchmarks for: {model_name}")
    print(f"==========================================")

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are an agentic coding assistant with tool-calling capabilities. Select and call tools accurately."},
            {"role": "user", "content": prompt_tool_test}
        ],
        "tools": tools_definition,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 256,
        "stream": False
    }

    start_ram = psutil.virtual_memory().percent
    start_time = time.time()

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start_time
            end_ram = psutil.virtual_memory().percent

            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls", None)
            content = message.get("content", "")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            details = usage.get("completion_tokens_details", {})
            reasoning_tokens = details.get("reasoning_tokens", 0)

            has_tool_call = tool_calls is not None and len(tool_calls) > 0

            print(f"[{model_name}] SUCCESS in {elapsed:.2f}s | RAM: {start_ram}% -> {end_ram}%")
            print(f"Tokens: prompt={prompt_tokens}, completion={completion_tokens}, reasoning={reasoning_tokens}")
            print(f"Tool Calling Capability Verified: {has_tool_call}")
            if has_tool_call:
                print(f"Tool Call Payload:\n{json.dumps(tool_calls, indent=2)}")
            else:
                print(f"Plain Content Response:\n{content[:300]}")

            result = {
                "model": model_name,
                "status": "SUCCESS",
                "has_tool_call": has_tool_call,
                "tool_calls": tool_calls,
                "content_preview": content[:300] if content else "",
                "time": elapsed,
                "start_ram": start_ram,
                "end_ram": end_ram,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_tokens
            }

            # Save to JSON
            with open("scripts/tool_calling_benchmark_results.json", "w") as f:
                json.dump(result, f, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{model_name}] ERROR after {elapsed:.2f}s: {e}")

if __name__ == "__main__":
    test_active_model()
