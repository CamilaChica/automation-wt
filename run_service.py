"""Run the API and mailbox worker together for the single-disk SQLite deployment."""

import threading
import os

import uvicorn

from worker import run as run_mailbox_worker


if __name__ == "__main__":
    worker_thread = threading.Thread(target=run_mailbox_worker, name="mailbox-worker", daemon=True)
    worker_thread.start()
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
