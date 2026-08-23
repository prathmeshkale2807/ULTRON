import asyncio
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn
import sys

app = FastAPI()

@app.get("/redirect_private")
def redirect_private():
    return RedirectResponse("http://192.168.1.1")

@app.get("/redirect_localhost")
def redirect_localhost():
    return RedirectResponse("http://localhost:8000")

@app.get("/redirect_nip")
def redirect_nip():
    return RedirectResponse("http://127.0.0.1.nip.io")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
