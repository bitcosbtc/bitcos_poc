from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.api import auth, users, brokers, trading, websocket, utils
from app.services.mtm_service import mtm_manager


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Multi-Account Trading Platform",
    version="1.0.0",
    description="Trading platform for managing multiple Delta Exchange accounts"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.on_event("startup")
async def startup_event():
    await mtm_manager.start()

@app.on_event("shutdown")
async def shutdown_event():
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