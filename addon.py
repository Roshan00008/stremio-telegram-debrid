import asyncio
import logging

# Fix Pyrogram event loop crash on Python 3.12/3.14
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import Config
from routers import catalog, channels, health, manifest, meta, pages, proxy, stream, subtitles
from tg_client import tg_client_manager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] (%(name)s) - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("stremio_addon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        print("\n" + "=" * 60)
        print("   TELEGRAM ADDON BY SUNILROY-DEV")
        print("   GitHub: https://github.com/SunilRoy-dev/stremio-telegram-debrid")
        print("   For educational and personal testing only.")
        print("=" * 60 + "\n")

        Config.validate()
        await tg_client_manager.start()
        yield
    finally:
        await tg_client_manager.stop()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(channels.router)
app.include_router(pages.router)
app.include_router(manifest.router)
app.include_router(catalog.router)
app.include_router(meta.router)
app.include_router(stream.router)
app.include_router(subtitles.router)
app.include_router(proxy.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("addon:app", host="0.0.0.0", port=Config.PORT, reload=False)
