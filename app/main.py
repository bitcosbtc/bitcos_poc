from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.api import auth, users, brokers, trading, websocket, utils, analytics, bot, cmio_agent
from app.services.mtm_service import mtm_manager
from app.services.trade_watchdog import trade_watchdog


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Multi-Account Trading Platform",
    version="1.0.0",
    description="Trading platform for managing multiple Delta Exchange accounts"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bitcos-frontend.vercel.app",
        "http://43.204.233.104",
        "http://localhost:9999",
        "http://127.0.0.1:9999",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(brokers.router)
app.include_router(trading.router)
app.include_router(websocket.router)
app.include_router(utils.router)
app.include_router(analytics.router, prefix="/api/analytics")
app.include_router(analytics.router, prefix="/api/trading/analytics")
app.include_router(bot.router)
app.include_router(cmio_agent.router)

@app.on_event("startup")
async def startup_event():
    await mtm_manager.start()
    await trade_watchdog.start()

@app.on_event("shutdown")
async def shutdown_event():
    await trade_watchdog.stop()
    await mtm_manager.stop()

@app.get("/")
async def root():
    return {
        "message": "Multi-Account Trading Platform API",
        "version": "1.0.0",
        "status": "active"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
