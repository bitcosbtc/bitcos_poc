import requests
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/utils", tags=["utils"])

@router.get("/public-ip")
def get_public_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        return {"ok": True, "ip": data.get("ip")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

