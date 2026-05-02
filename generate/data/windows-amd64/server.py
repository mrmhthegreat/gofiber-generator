import os
import sys
import subprocess
import threading
import json
import asyncio
import webbrowser
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List

app = FastAPI(title="GoFiber Generator Web Studio")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# When installed as a package, assets are inside the generators directory
ASSETS_DIR = os.path.join(BASE_DIR, "generators", "web_assets")

# Fallback for local development if not in generators
if not os.path.exists(ASSETS_DIR):
    ASSETS_DIR = os.path.join(BASE_DIR, "web_assets")

# Global log queue
log_queue = asyncio.Queue()

class GenRequest(BaseModel):
    config_path: str = "master_config.yaml"
    output_path: str = "./generated"
    skipped_steps: List[str] = []

# Mount static files
if os.path.exists(ASSETS_DIR):
    app.mount("/web_assets", StaticFiles(directory=ASSETS_DIR), name="web_assets")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(ASSETS_DIR, "index.html")
    with open(index_path, "r") as f:
        return f.read()

@app.get("/style.css")
async def get_css():
    with open(os.path.join(ASSETS_DIR, "style.css"), "r") as f:
        return StreamingResponse(f, media_type="text/css")

@app.get("/app.js")
async def get_js():
    with open(os.path.join(ASSETS_DIR, "app.js"), "r") as f:
        return StreamingResponse(f, media_type="application/javascript")

@app.post("/generate")
async def start_generation(req: GenRequest):
    cmd = [sys.executable, "generator.py", "--config", req.config_path, "--output", req.output_path]
    if req.skipped_steps:
        cmd.extend(["--skip"] + req.skipped_steps)

    threading.Thread(target=run_engine, args=(cmd,), daemon=True).start()
    return {"status": "started"}

async def log_generator():
    while True:
        msg = await log_queue.get()
        yield f"data: {json.dumps(msg)}\n\n"
        if msg.get("status") in ["completed", "failed"]:
            break

@app.get("/logs")
async def stream_logs():
    return StreamingResponse(log_generator(), media_type="text/event-stream")

def run_engine(cmd):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=BASE_DIR)
        loop.run_until_complete(log_queue.put({"message": f"🚀 Starting: {' '.join(cmd)}", "type": "system"}))
        for line in iter(process.stdout.readline, ""):
            loop.run_until_complete(log_queue.put({"message": line.strip(), "type": "info"}))
        process.wait()
        status = "completed" if process.returncode == 0 else "failed"
        loop.run_until_complete(log_queue.put({"message": f"🏁 Process finished", "status": status}))
    except Exception as e:
        loop.run_until_complete(log_queue.put({"message": str(e), "status": "failed"}))

def main():
    print("🚀 Syntax Genesis Server starting at http://127.0.0.1:8000")
    # Auto-open browser
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    # Start FastAPI
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    main()
