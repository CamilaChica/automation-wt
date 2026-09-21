"""Run only the FastAPI service.

Mailbox polling runs in the dedicated Render worker service so messages cannot
be processed twice by both the API process and the worker process.
"""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
