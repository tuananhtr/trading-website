"""
run.py — entry point for Railway/production deployment.
Adds the backend/ directory to sys.path then starts uvicorn.
"""
import os
import sys

# Make sure backend/ modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
