#!/usr/bin/env python3
"""Inicia o FastAPI localmente ou dentro do Docker."""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "fastapi_app.main:create_app",
        factory=True,
        host=os.environ.get("WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEB_PORT", "5000")),
        reload=False,
        access_log=False,
    )
