from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from ..database import get_db
from ..models.broker import Broker
from ..models.user import User
from ..schemas.broker import BrokerCreate, BrokerUpdate
from ..services.encryption import encryption_service
from ..services.delta_exchange import DeltaExchangeAPI
from ..utils.otp_manager import otp_manager
from .auth import get_current_active_user

router = APIRouter(prefix="/api/brokers", tags=["Brokers"])

def mask_string(s: str, visible_chars: int = 3) -> str:
    if len(s) <= visible_chars:
        return '*' * len(s)
    return s[:visible_chars] + '*' * (len(s) - visible_chars)

@router.post("/")
async def add_broker(
    broker: BrokerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    # Test connection immediately
    api_key_clean = broker.api_key.strip() if broker.api_key else ""
    if api_key_clean.startswith("gAAAAA"):
        try:
            api_key_clean = encryption_service.decrypt(api_key_clean)
        except Exception:
            pass

    secret_key_clean = broker.secret_key.strip() if broker.secret_key else ""
    if secret_key_clean.startswith("gAAAAA"):
        try:
            secret_key_clean = encryption_service.decrypt(secret_key_clean)
        except Exception:
            pass

    totp_secret_clean = broker.totp_secret.strip() if broker.totp_secret else None
    if totp_secret_clean and totp_secret_clean.startswith("gAAAAA"):
        try:
            totp_secret_clean = encryption_service.decrypt(totp_secret_clean)
        except Exception:
            pass
    
    resolved_base_url = broker.redirect_url
    
    # Determine which base URLs to try
    urls_to_try = []
    if resolved_base_url:
        urls_to_try.append(resolved_base_url)
        # Fallback to the other endpoint if the user-specified one fails
        alt_url = "https://api.delta.exchange" if "india" in resolved_base_url else "https://api.india.delta.exchange"
        urls_to_try.append(alt_url)
    else:
        urls_to_try = ["https://api.india.delta.exchange", "https://api.delta.exchange"]
        
    connection_success = False
    errors = []
    
    for url in urls_to_try:
        print(f"Testing connection against Delta Exchange: {url}")
        delta_api = DeltaExchangeAPI(api_key_clean, secret_key_clean, base_url=url)
        wallet = delta_api.get_wallet_balances()
        
        if wallet.get("success", True):
            resolved_base_url = url
            connection_success = True
            print(f"Successfully connected to Delta Exchange: {url}")
            break
        else:
            err_code = wallet.get("error")
            # If we get ip_not_whitelisted, the signature verification succeeded!
            # It means the API secret is correct and this is the correct exchange URL.
            if err_code == "ip_not_whitelisted_for_api_key":
                resolved_base_url = url
                client_ip = wallet.get("context", {}).get("client_ip", "your IP")
                raise HTTPException(
                    status_code=400,
                    detail=f"IP restriction error. Please whitelist your server/local IP ({client_ip}) on the Delta Exchange ({url}) API Key settings page."
                )
            
            errors.append(f"{url} error: {err_code}")
            
    if not connection_success:
        raise HTTPException(
            status_code=400,
            detail=f"Connection check failed. Details: {', '.join(errors)}"
        )

    encrypted_api_key = encryption_service.encrypt(api_key_clean)
    encrypted_secret_key = encryption_service.encrypt(secret_key_clean)
    
    new_broker = Broker(
        user_id=current_user.id,
        broker_name=broker.broker_name,
        broker_login_id=broker.broker_login_id.strip() if broker.broker_login_id else "",
        api_key_encrypted=encrypted_api_key,
        secret_key_encrypted=encrypted_secret_key,
        totp_secret_encrypted=encryption_service.encrypt(totp_secret_clean) if totp_secret_clean else None,
        name_tag=broker.name_tag,
        redirect_url=resolved_base_url,
        status="ACTIVE",
        token_generated_at=datetime.utcnow()
    )
    
    db.add(new_broker)
    db.commit()
    db.refresh(new_broker)
    
    return {"message": "Broker added and connected successfully", "broker_id": new_broker.id}

@router.get("/")
async def get_brokers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    brokers = db.query(Broker).filter(Broker.user_id == current_user.id).all()
    
    result = []
    for broker in brokers:
        api_key = encryption_service.decrypt(broker.api_key_encrypted)
        secret_key = encryption_service.decrypt(broker.secret_key_encrypted)
        
        # Get live OTP info for initial display
        otp = None
        remaining = 0
        if broker.totp_secret_encrypted:
            try:
                secret = encryption_service.decrypt(broker.totp_secret_encrypted)
                otp = otp_manager.generate_otp(secret)
                remaining = otp_manager.get_remaining_seconds(secret)
            except Exception:
                otp = "Error"
        
        result.append({
            "id": broker.id,
            "broker": broker.broker_name,
            "broker_id": mask_string(broker.broker_login_id, 2),
            "name_tag": broker.name_tag,
            "app_id": mask_string(api_key, 3),
            "app_secret_key": mask_string(secret_key, 7),
            "totp_secret": mask_string(encryption_service.decrypt(broker.totp_secret_encrypted), 3) if broker.totp_secret_encrypted else None,
            "otp": otp,
            "otp_remaining": remaining,
            "status": broker.status,
            "last_token_generated_at": broker.token_generated_at.strftime("%d-%m-%y, %H:%M") if broker.token_generated_at else "-",
            "added_at": broker.added_at.strftime("%d-%m-%y, %H:%M")
        })
    
    return result

@router.get("/{broker_id}")
async def get_broker(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == current_user.id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    return broker

@router.put("/{broker_id}")
async def update_broker(
    broker_id: int,
    broker_update: BrokerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == current_user.id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    if broker_update.broker_login_id:
        broker.broker_login_id = broker_update.broker_login_id.strip()
        
    if broker_update.api_key:
        api_key_clean = broker_update.api_key.strip()
        if api_key_clean.startswith("gAAAAA"):
            try:
                api_key_clean = encryption_service.decrypt(api_key_clean)
            except Exception:
                pass
        broker.api_key_encrypted = encryption_service.encrypt(api_key_clean)
        
    if broker_update.secret_key:
        secret_key_clean = broker_update.secret_key.strip()
        if secret_key_clean.startswith("gAAAAA"):
            try:
                secret_key_clean = encryption_service.decrypt(secret_key_clean)
            except Exception:
                pass
        broker.secret_key_encrypted = encryption_service.encrypt(secret_key_clean)
        
    if broker_update.totp_secret:
        totp_clean = broker_update.totp_secret.strip()
        if totp_clean.startswith("gAAAAA"):
            try:
                totp_clean = encryption_service.decrypt(totp_clean)
            except Exception:
                pass
        broker.totp_secret_encrypted = encryption_service.encrypt(totp_clean)
    if broker_update.name_tag:
        broker.name_tag = broker_update.name_tag
    if broker_update.status:
        broker.status = broker_update.status
    
    db.commit()
    db.refresh(broker)
    
    return {"message": "Broker updated successfully"}

@router.delete("/{broker_id}")
async def delete_broker(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == current_user.id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    db.delete(broker)
    db.commit()
    
    return {"message": "Broker deleted successfully"}

@router.post("/{broker_id}/generate-token")
async def generate_token(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == current_user.id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    api_key = encryption_service.decrypt(broker.api_key_encrypted)
    secret_key = encryption_service.decrypt(broker.secret_key_encrypted)
    
    try:
        delta_api = DeltaExchangeAPI(api_key, secret_key, base_url=broker.redirect_url or "https://api.india.delta.exchange")
        wallet = delta_api.get_wallet_balances()
        
        if wallet.get("success", True):
            broker.token_generated_at = datetime.utcnow()
            broker.status = "ACTIVE"
            db.commit()
            
            return {"message": "Token generated successfully", "status": "success"}
        else:
            return {"message": "Failed to generate token", "error": wallet.get("error"), "status": "failed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{broker_id}/otp")
async def get_broker_otp(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == current_user.id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    if not broker.totp_secret_encrypted:
        return {"otp": None, "remaining_seconds": 0, "message": "2FA Secret not set"}
    
    secret = encryption_service.decrypt(broker.totp_secret_encrypted)
    otp = otp_manager.generate_otp(secret)
    remaining = otp_manager.get_remaining_seconds(secret)
    
    return {
        "otp": otp,
        "remaining_seconds": remaining,
        "broker_id": broker.id,
        "name_tag": broker.name_tag
    }

