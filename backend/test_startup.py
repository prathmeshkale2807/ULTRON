import asyncio
from app.main import lifespan
from fastapi import FastAPI
import logging

logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

async def main():
    try:
        async with lifespan(app):
            print('Lifespan started successfully!')
    except Exception as e:
        print(f'FAILED: {e}')
        import traceback
        traceback.print_exc()

asyncio.run(main())
