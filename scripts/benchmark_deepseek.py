import urllib.request
import json
import time
import psutil

url = "http://localhost:1234/v1/chat/completions"

prompt_content = (
    "You are an expert coding assistant with access to tools (bash, file_read, file_edit).\n"
    "Here is a Python file to refactor:\n"
    "def bubble_sort(arr):\n    n = len(arr)\n    for i in range(n):\n        for j in range(0, n-i-1):\n            if arr[j] > arr[j+1]:\n                arr[j], arr[j+1] = arr[j+1], arr[j]\n    return arr\n"
    "Refactor this to be more efficient, explain your changes, and provide a test case."
)

payload = {
    "model": "deepseek-coder-v2-lite-instruct",
    "messages": [
        {"role": "system", "content": "You are a helpful coding assistant. Follow instructions precisely."},
        {"role": "user", "content": prompt_content}
    ],
    "temperature": 0.2,
    "max_tokens": 256,
    "stream": False
}

print("Running benchmark for deepseek-coder-v2-lite-instruct...")
start_ram = psutil.virtual_memory().percent
start_time = time.time()

try:
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start_time
        end_ram = psutil.virtual_memory().percent
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        details = usage.get("completion_tokens_details", {})
        reasoning_tokens = details.get("reasoning_tokens", 0)
        
        content = data["choices"][0]["message"]["content"]
        print(f"[deepseek-coder-v2-lite-instruct] SUCCESS in {elapsed:.2f}s | RAM: {start_ram}% -> {end_ram}%")
        print(f"Tokens: prompt={prompt_tokens}, completion={completion_tokens}, reasoning={reasoning_tokens}")
        print(f"Preview:\n{content[:300]}...\n")
        
        result = {
            "model": "deepseek-coder-v2-lite-instruct",
            "status": "SUCCESS",
            "time": elapsed,
            "start_ram": start_ram,
            "end_ram": end_ram,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "preview": content[:300]
        }
        with open("scripts/deepseek_benchmark_result.json", "w") as f:
            json.dump(result, f, indent=2)
except Exception as e:
    elapsed = time.time() - start_time
    print(f"[deepseek-coder-v2-lite-instruct] Error after {elapsed:.2f}s: {e}")
