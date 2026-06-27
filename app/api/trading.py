from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models.broker import Broker
from ..models.user import User
from ..models.position import Position
from ..models.order import Order
from ..models.mtm import MTMSettings
from ..schemas.position import StopLossRequest, TakeProfitRequest
from ..schemas.order import OrderCreate
from ..schemas.mtm import MTMSettingsUpdate, MTMSettingsResponse
from ..services.encryption import encryption_service
from ..services.delta_exchange import DeltaExchangeAPI
from .auth import get_current_active_user

router = APIRouter(prefix="/api/trading", tags=["Trading"])

def get_delta_api(broker_id: int, user_id: int, db: Session) -> DeltaExchangeAPI:
    broker = db.query(Broker).filter(
        Broker.id == broker_id,
        Broker.user_id == user_id
    ).first()
    
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    
    api_key = encryption_service.decrypt(broker.api_key_encrypted)
    secret_key = encryption_service.decrypt(broker.secret_key_encrypted)
    
    return DeltaExchangeAPI(api_key, secret_key, base_url=broker.redirect_url or "https://api.india.delta.exchange")

@router.get("/positions/{broker_id}")
async def get_positions(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        positions_data = delta_api.get_positions()
        
        if positions_data.get("success", True):
            for pos in positions_data.get("result", []):
                existing_pos = db.query(Position).filter(
                    Position.broker_id == broker_id,
                    Position.product_id == pos.get("product_id")
                ).first()
                
                if existing_pos:
                    existing_pos.size = pos.get("size", 0)
                    existing_pos.entry_price = pos.get("entry_price", 0)
                    existing_pos.mark_price = pos.get("mark_price", 0)
                    existing_pos.index_price = pos.get("index_price", 0)
                    existing_pos.notional = pos.get("notional", 0)
                    existing_pos.margin = pos.get("margin", 0)
                    existing_pos.unrealized_pnl = pos.get("unrealized_pnl", 0)
                else:
                    new_pos = Position(
                        broker_id=broker_id,
                        symbol=pos.get("symbol", ""),
                        product_id=pos.get("product_id"),
                        size=pos.get("size", 0),
                        entry_price=pos.get("entry_price", 0),
                        mark_price=pos.get("mark_price", 0),
                        index_price=pos.get("index_price", 0),
                        notional=pos.get("notional", 0),
                        margin=pos.get("margin", 0),
                        unrealized_pnl=pos.get("unrealized_pnl", 0)
                )
                db.add(new_pos)
        
            db.commit()
            return positions_data
        else:
            raise HTTPException(status_code=400, detail=positions_data.get("error"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions/all/summary")
async def get_all_positions_summary(
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        brokers = db.query(Broker).filter(Broker.user_id == current_user.id,Broker.status == "ACTIVE").all()
        all_positions = []
        total_upnl = 0.0

        for broker in brokers:
            try:
                delta_api = get_delta_api(broker.id, current_user.id, db)
                positions_data = delta_api.get_positions()
                
                if positions_data.get("success", True):
                    broker_positions = positions_data.get("result", [])
                    print(f"DEBUG: Processing positions for broker {broker.id} (v2.1-robust)")
                    for pos in broker_positions:
                        pos["broker_name"] = broker.name_tag
                        pos["broker_id"] = broker.id
                        # Defensive casting for strings/floats/commas
                        raw_pnl = pos.get("unrealized_pnl", 0)
                        try:
                            val = float(str(raw_pnl or 0).replace(',', ''))
                            total_upnl += val
                        except (ValueError, TypeError):
                            print(f"DEBUG: Failed to cast PnL '{raw_pnl}' to float")
                    
                    all_positions.extend(broker_positions)
            except Exception as e:
                print(f"Error fetching positions for broker {broker.id}: {str(e)}")
                continue

        return {
            "positions": all_positions,
            "total_upnl": total_upnl,
            "position_count": len(all_positions)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/{broker_id}/close/{product_id}")
async def close_position(
broker_id: int,
product_id: int,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        result = delta_api.close_position(product_id)
        if result.get("success", True):
            position = db.query(Position).filter(
                Position.broker_id == broker_id,
                Position.product_id == product_id
            ).first()
            
            if position:
                db.delete(position)
                db.commit()
            
            return {"message": "Position closed successfully", "data": result}
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/{broker_id}/close-all")
async def close_all_positions(
broker_id: int,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        result = delta_api.close_all_positions()
        if result.get("success", True):
            db.query(Position).filter(Position.broker_id == broker_id).delete()
            db.commit()
            
            return {"message": "All positions closed successfully", "data": result}
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/positions/close-all-brokers")
async def close_all_positions_all_brokers(
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    brokers = db.query(Broker).filter(Broker.user_id == current_user.id,Broker.status == "ACTIVE").all()
    results = []
    for broker in brokers:
        try:
            delta_api = get_delta_api(broker.id, current_user.id, db)
            result = delta_api.close_all_positions()
            
            results.append({
                "broker_id": broker.id,
                "broker_name": broker.name_tag,
                "success": result.get("success", True),
                "message": "Positions closed" if result.get("success", True) else result.get("error")
            })
            
            if result.get("success", True):
                db.query(Position).filter(Position.broker_id == broker.id).delete()
                
        except Exception as e:
            results.append({
                "broker_id": broker.id,
                "broker_name": broker.name_tag,
                "success": False,
                "message": str(e)
            })

    db.commit()
    return {"results": results}


@router.post("/positions/{broker_id}/stop-loss")
async def add_stop_loss(
broker_id: int,
sl_request: StopLossRequest,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):

    try:
        print(f"Adding stop loss for broker {broker_id}, product {sl_request.product_id}, price {sl_request.stop_loss_price}")
        delta_api = get_delta_api(broker_id, current_user.id, db)
        
        result = delta_api.add_stop_loss(
            int(sl_request.product_id),
            float(sl_request.stop_loss_price),
            float(sl_request.trail_amount) if sl_request.trail_amount else None
        )
        
        print(f"Delta API SL result: {result}")
        
        if result.get("success", False) or "error" not in result:
            # Update local DB
            position = db.query(Position).filter(
                Position.broker_id == broker_id,
                Position.product_id == int(sl_request.product_id)
            ).first()
            
            if position:
                position.stop_loss = float(sl_request.stop_loss_price)
                db.commit()
                print(f"Position updated in DB with SL: {sl_request.stop_loss_price}")
            else:
                print(f"Position not found in DB for product {sl_request.product_id}")
            
            return {"success": True, "message": "Stop loss added successfully", "data": result}
        else:
            error_msg = result.get("error", "Unknown Delta API error")
            print(f"Delta API SL Error: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
            
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"TP/SL Exception: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/{broker_id}/take-profit")
async def add_take_profit(
broker_id: int,
tp_request: TakeProfitRequest,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        print(f"Adding take profit for broker {broker_id}, product {tp_request.product_id}, price {tp_request.take_profit_price}")
        delta_api = get_delta_api(broker_id, current_user.id, db)
        
        result = delta_api.add_take_profit(
            int(tp_request.product_id),
            float(tp_request.take_profit_price)
        )
        
        print(f"Delta API TP result: {result}")
        
        if result.get("success", False) or "error" not in result:
            # Update local DB
            position = db.query(Position).filter(
                Position.broker_id == broker_id,
                Position.product_id == int(tp_request.product_id)
            ).first()
            
            if position:
                position.take_profit = float(tp_request.take_profit_price)
                db.commit()
                print(f"Position updated in DB with TP: {tp_request.take_profit_price}")
            else:
                print(f"Position not found in DB for product {tp_request.product_id}")
            
            return {"success": True, "message": "Take profit added successfully", "data": result}
        else:
            error_msg = result.get("error", "Unknown Delta API error")
            print(f"Delta API TP Error: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
            
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"TP/SL Exception: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/{broker_id}/place")
async def place_order(
broker_id: int,
order: OrderCreate,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        result = delta_api.place_order(
            order.product_id,
            order.side,
            order.order_type,
            order.size,
            order.price,
            order.stop_price,
            order.reduce_only
        )
        if result.get("success", True):
            order_data = result.get("result", {})
            
            new_order = Order(
                broker_id=broker_id,
                order_id=order_data.get("id", ""),
                symbol=order_data.get("symbol", ""),
                product_id=order.product_id,
                side=order.side,
                order_type=order.order_type,
                size=order.size,
                price=order.price,
                stop_price=order.stop_price,
                status=order_data.get("state", "open"),
                filled_size=order_data.get("filled_size", 0)
            )
            
            db.add(new_order)
            db.commit()
            
            return {"message": "Order placed successfully", "data": result}
        else:
            error_val = result.get("error", "Unknown error")
            if isinstance(error_val, dict):
                error_msg = error_val.get("message") or error_val.get("code") or str(error_val)
            else:
                error_msg = str(error_val)
            raise HTTPException(status_code=400, detail=error_msg)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/orders/place-multiple")
async def place_order_multiple_brokers(
order: OrderCreate,
broker_ids: List[int],
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    results = []
    for broker_id in broker_ids:
        try:
            delta_api = get_delta_api(broker_id, current_user.id, db)
            result = delta_api.place_order(
                order.product_id,
                order.side,
                order.order_type,
                order.size,
                order.price,
                order.stop_price
            )
            
            broker = db.query(Broker).filter(Broker.id == broker_id).first()
            
            if result.get("success", True):
                order_data = result.get("result", {})
                
                new_order = Order(
                    broker_id=broker_id,
                    order_id=order_data.get("id", ""),
                    symbol=order_data.get("symbol", ""),
                    product_id=order.product_id,
                    side=order.side,
                    order_type=order.order_type,
                    size=order.size,
                    price=order.price,
                    stop_price=order.stop_price,
                    status=order_data.get("state", "open"),
                    filled_size=order_data.get("filled_size", 0)
                )
                
                db.add(new_order)
                
                results.append({
                    "broker_id": broker_id,
                    "broker_name": broker.name_tag if broker else "Unknown",
                    "success": True,
                    "order_id": order_data.get("id"),
                    "message": "Order placed successfully"
                })
            else:
                error_val = result.get("error", "Unknown error")
                if isinstance(error_val, dict):
                    error_msg = error_val.get("message") or error_val.get("code") or str(error_val)
                else:
                    error_msg = str(error_val)
                    
                results.append({
                    "broker_id": broker_id,
                    "broker_name": broker.name_tag if broker else "Unknown",
                    "success": False,
                    "message": error_msg
                })
                
        except Exception as e:
            broker = db.query(Broker).filter(Broker.id == broker_id).first()
            results.append({
                "broker_id": broker_id,
                "broker_name": broker.name_tag if broker else "Unknown",
                "success": False,
                "message": str(e)
            })

    db.commit()
    return {"results": results}

@router.get("/profile/{broker_id}")
async def get_broker_profile(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        profile_res = delta_api.get_profile()
        if not profile_res.get("success"):
            return {"success": False, "error": profile_res.get("error")}
            
        margin_mode = profile_res.get("result", {}).get("margin_mode", "UNKNOWN")
        return {"success": True, "margin_mode": margin_mode.capitalize()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leverage/{broker_id}/{product_id}")
async def set_leverage(
    broker_id: int,
    product_id: int,
    leverage: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        res = delta_api.set_leverage(product_id, leverage)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/options/chain/{broker_id}")
async def get_options_chain(
    broker_id: int,
    underlying: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        
        # 1. Fetch products metadata
        products_res = delta_api.get_products()
        if not products_res.get("success"):
            return products_res
            
        all_products = products_res.get("result", [])
        
        filtered_products = []
        for p in all_products:
            c_type = p.get("contract_type", "")
            if c_type in ["call_options", "put_options"]:
                if underlying:
                    u_sym = p.get("underlying_asset_symbol") or (p.get("underlying_asset") or {}).get("symbol")
                    if u_sym != underlying:
                        continue
                filtered_products.append(p)
                
        # 2. Fetch pricing data via tickers
        tickers_res = delta_api.get_tickers(
            contract_types="call_options,put_options",
            underlying_symbols=underlying
        )
        
        if not tickers_res.get("success"):
            return tickers_res
            
        tickers = tickers_res.get("result", [])
        ticker_map = {t.get("symbol"): t for t in tickers}
        
        # 3. Merge ticker pricing into products flat
        joined_list = []
        for p in filtered_products:
            symbol = p.get("symbol")
            tick = ticker_map.get(symbol, {})
            merged = p.copy()
            merged.update(tick)
            joined_list.append(merged)
            
        return {"success": True, "result": joined_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/{broker_id}")
async def get_orders(
broker_id: int,
product_id: Optional[int] = None,
state: Optional[str] = None,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        orders_data = delta_api.get_orders(product_id, state=state)
        return orders_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orders/{broker_id}/cancel/{order_id}")
async def cancel_order(
broker_id: int,
order_id: str,
product_id: Optional[int] = None,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        result = delta_api.cancel_order(order_id, product_id)
        if result.get("success", True):
            order = db.query(Order).filter(
                Order.broker_id == broker_id,
                Order.order_id == order_id
            ).first()
            
            if order:
                order.status = "cancelled"
                db.commit()
            
            return {"message": "Order cancelled successfully", "data": result}
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orders/{broker_id}/cancel-all")
async def cancel_all_orders(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        result = delta_api.cancel_all_orders()
        
        # Optionally update database status for all orders of this broker
        db.query(Order).filter(
            Order.broker_id == broker_id,
            Order.status.in_(["open", "pending"])
        ).update({"status": "cancelled"}, synchronize_session=False)
        db.commit()
        
        return {"message": "All orders cancelled successfully", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/{broker_id}")
async def get_products(
broker_id: int,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        products = delta_api.get_products()
        return products
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ticker/{broker_id}/{symbol}")
async def get_ticker(
broker_id: int,
symbol: str,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        ticker = delta_api.get_ticker(symbol)
        return ticker
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/{broker_id}")
async def get_wallet(
    broker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        assets_res = delta_api.get_assets()
        
        if not assets_res.get("success"):
            return {"success": False, "error": assets_res.get("error")}
            
        assets = assets_res.get("result", [])
        balances = {}
        
        # To fix the slow connection time, ONLY fetch balances for USD or USDT instead of all 100+ crypto assets
        for asset in assets:
            symbol = asset.get("symbol")
            if symbol not in ["USD", "USDT"]:
                continue
                
            asset_id = asset.get("id")
            
            # Just fetch the balances for this asset_id
            bal_res = delta_api.get_wallet_balances(asset_id)
            if bal_res.get("success"):
                result_list = bal_res.get("result", [])
                
                # The API returns a list, find the one matching our asset_id
                filtered = [w for w in result_list if w.get("asset_id") == asset_id]
                balances[symbol] = filtered[0] if filtered else None
            else:
                # IMPORTANT: DO NOT swallow errors! Forward to frontend for whitelist checks
                return {"success": False, "error": bal_res.get("error")}
                
        return {"success": True, "result": balances}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fills/{broker_id}")
async def get_fills(
broker_id: int,
product_id: Optional[int] = None,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        fills = delta_api.get_fills(product_id)
        return fills
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/order-history/{broker_id}")
async def get_order_history(
broker_id: int,
product_id: Optional[int] = None,
db: Session = Depends(get_db),
current_user: User = Depends(get_current_active_user)
):
    try:
        delta_api = get_delta_api(broker_id, current_user.id, db)
        history = delta_api.get_order_history(product_id)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/mtm-settings", response_model=MTMSettingsResponse)
async def get_mtm_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    settings = db.query(MTMSettings).filter(MTMSettings.user_id == current_user.id).first()
    if not settings:
        settings = MTMSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@router.post("/mtm-settings", response_model=MTMSettingsResponse)
async def update_mtm_settings(
    mtm_data: MTMSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    settings = db.query(MTMSettings).filter(MTMSettings.user_id == current_user.id).first()
    if not settings:
        settings = MTMSettings(user_id=current_user.id)
        db.add(settings)
    
    settings.sl_pct = mtm_data.sl_pct
    settings.tp_pct = mtm_data.tp_pct
    settings.trail_pct = mtm_data.trail_pct
    settings.is_active = mtm_data.is_active
    if mtm_data.peak_upnl_pct is not None:
        settings.peak_upnl_pct = mtm_data.peak_upnl_pct
    
    db.commit()
    db.refresh(settings)
    return settings

