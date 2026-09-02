import urllib.request
import json
import time
import psutil
import threading

def monitor_system(stop_event, metrics):
    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        metrics.append((time.time(), cpu, ram))

def run_benchmark():
    url = "http://localhost:1234/v1/chat/completions"
    
    # Test prompt with context (simulating python file + tools)
    prompt_content = "You are a coding assistant. Here is a python file:\n" + ("def calculate_factorial(n):\n    if n <= 1: return 1\n    return n * calculate_factorial(n-1)\n" * 50) + "\nRefactor this file and explain your changes."
    
    payload = {
        "model": "qwen/qwen3.5-9b",
        "messages": [
            {"role": "system", "content": "You have access to tools: bash, file_read, file_edit. Use them wisely."},
            {"role": "user", "content": prompt_content}
        ],
        "temperature": 0.2,
        "max_tokens": 512,
        "stream": False
    }

    metrics = []
    stop_event = threading.Event()
    t = threading.Thread(target=monitor_system, args=(stop_event, metrics))
    t.start()

    start_time = time.time()
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start_time
            stop_event.set()
            t.join()
            print(f"Benchmark completed in {elapsed:.2f} seconds")
            print("Usage:", data.get("usage"))
            if metrics:
                avg_cpu = sum(m[1] for m in metrics) / len(metrics)
                max_ram = max(m[2] for m in metrics)
                print(f"Avg CPU during call: {avg_cpu:.1f}%, Max RAM usage: {max_ram:.1f}%")
            return data
    except Exception as e:
        stop_event.set()
        t.join()
        elapsed = time.time() - start_time
        print(f"Benchmark failed/timed out after {elapsed:.2f}s: {e}")
        return None

if __name__ == "__main__":
    run_benchmark()
