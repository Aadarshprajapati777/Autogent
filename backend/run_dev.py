"""Local dev launcher. Sets the Windows SelectorEventLoop policy BEFORE
uvicorn creates its event loop — psycopg3 is incompatible with the Windows
default ProactorEventLoop.

Run: python run_dev.py
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
