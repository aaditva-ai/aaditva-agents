import urllib.request
import json
import time
import psutil

url = "http://localhost:1234/v1/chat/completions"

prompt_content = (
    "You are an expert full-stack coding assistant with access to tools (bash, file_read, file_edit).\n"
    "Please generate a complete, working prototype for a TicTacToe application:\n"
    "1. Backend: A FastAPI server (`main.py`) with endpoints to start a game, make a move, check winner, and reset.\n"
    "2. Frontend: A React component (`App.jsx`) styled with basic CSS or Tailwind, allowing two players to play TicTacToe by communicating with the FastAPI backend.\n"
    "Provide clear code blocks for both files and brief instructions on how to run them."
)

payload = {
    "model": "qwen2.5-coder-7b-instruct",
    "messages": [
        {"role": "system", "content": "You are a precise and expert full-stack coding assistant. Follow instructions and write clean, complete code."},
        {"role": "user", "content": prompt_content}
    ],
    "temperature": 0.2,
    "max_tokens": 1500,
    "stream": False
}

print("Running full-stack benchmark for qwen2.5-coder-7b-instruct (with speculative decoding)...")
start_ram = psutil.virtual_memory().percent
start_time = time.time()

try:
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start_time
        end_ram = psutil.virtual_memory().percent
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        details = usage.get("completion_tokens_details", {})
        reasoning_tokens = details.get("reasoning_tokens", 0)
        
        content = data["choices"][0]["message"]["content"]
        print(f"[qwen2.5-coder-7b-instruct] SUCCESS in {elapsed:.2f}s | RAM: {start_ram}% -> {end_ram}%")
        print(f"Tokens: prompt={prompt_tokens}, completion={completion_tokens}, reasoning={reasoning_tokens}")
        print(f"Preview (first 500 chars):\n{content[:500]}...\n")
        
        result = {
            "model": "qwen2.5-coder-7b-instruct",
            "status": "SUCCESS",
            "time": elapsed,
            "start_ram": start_ram,
            "end_ram": end_ram,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "full_response": content
        }
        with open("scripts/fullstack_benchmark_result.json", "w") as f:
            json.dump(result, f, indent=2)
        with open("scripts/generated_tictactoe_code.md", "w") as f:
            f.write(content)
        print("Benchmark results and generated code saved successfully.")
except Exception as e:
    elapsed = time.time() - start_time
    print(f"[qwen2.5-coder-7b-instruct] Error after {elapsed:.2f}s: {e}")
