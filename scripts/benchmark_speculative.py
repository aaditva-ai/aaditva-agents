import urllib.request
import json
import time
import psutil

models_to_test = [
    "qwen2.5-coder-3b-instruct",
    "stable-code-instruct-3b-i1",
    "deepseek-coder-v2-lite-instruct",
    "deepseek/deepseek-r1-0528-qwen3-8b",
    "google/gemma-4-e4b",
    "qwen/qwen2.5-coder-14b"
]

url = "http://localhost:1234/v1/chat/completions"

prompt_content = (
    "You are an expert coding assistant with access to tools (bash, file_read, file_edit).\n"
    "Here is a Python file to refactor:\n"
    "def bubble_sort(arr):\n    n = len(arr)\n    for i in range(n):\n        for j in range(0, n-i-1):\n            if arr[j] > arr[j+1]:\n                arr[j], arr[j+1] = arr[j+1], arr[j]\n    return arr\n"
    "Refactor this to be more efficient, explain your changes, and provide a test case."
)

results = []

for m in models_to_test:
    print(f"\n==========================================")
    print(f"Benchmarking model: {m}")
    print(f"==========================================")
    
    payload = {
        "model": m,
        "messages": [
            {"role": "system", "content": "You are a helpful coding assistant. Follow instructions precisely."},
            {"role": "user", "content": prompt_content}
        ],
        "temperature": 0.2,
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
            print(f"[{m}] SUCCESS in {elapsed:.2f}s | RAM: {start_ram}% -> {end_ram}%")
            print(f"Tokens: prompt={prompt_tokens}, completion={completion_tokens}, reasoning={reasoning_tokens}")
            print(f"Preview:\n{content[:200]}...\n")
            
            results.append({
                "model": m,
                "status": "SUCCESS",
                "time": elapsed,
                "start_ram": start_ram,
                "end_ram": end_ram,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_tokens,
                "preview": content[:200]
            })
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        elapsed = time.time() - start_time
        print(f"[{m}] HTTPError {e.code} after {elapsed:.2f}s: {err_body}")
        results.append({
            "model": m,
            "status": f"HTTPError {e.code}",
            "error": err_body,
            "time": elapsed
        })
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{m}] Error after {elapsed:.2f}s: {e}")
        results.append({
            "model": m,
            "status": f"Error: {str(e)}",
            "time": elapsed
        })

print("\n\n==========================================")
print("SPECULATIVE & BASELINE BENCHMARK SUMMARY")
print("==========================================")
for r in results:
    print(f"Model: {r['model']} | Status: {r['status']} | Time: {r.get('time', 0):.2f}s | Reasoning Tokens: {r.get('reasoning_tokens', 0)}")

with open("scripts/speculative_benchmark_results.json", "w") as f:
    json.dump(results, f, indent=2)
