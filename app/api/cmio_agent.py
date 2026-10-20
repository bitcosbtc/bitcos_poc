from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.cmio_agent_service import cmio_agent_service
from ..services.multi_agent_chat_service import multi_agent_chat_service

router = APIRouter(prefix="/api/agent", tags=["CMIO AI Agent & Council"])


class AgentChatRequest(BaseModel):
    agent_id: str = Field("chief", description="ID of the agent to communicate with")
    message: str = Field(..., description="User message / question")
    conversation_history: Optional[List[Dict[str, str]]] = Field(default=[], description="Previous conversation turns")
    delegate_to_subordinates: bool = Field(True, description="Whether Chief / Leads should consult subordinates")


@router.get("/hierarchy")
async def get_agent_hierarchy() -> Dict[str, Any]:
    """
    Returns the complete organizational hierarchy of the Chief Market Intelligence Officer (CMIO),
    the 5 Research Leads, and the 16 Specialized Analysts with full mandates and responsibilities.
    """
    return {
        "success": True,
        "data": cmio_agent_service.get_agent_hierarchy()
    }


@router.get("/backtest/stats")
async def get_backtest_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Returns aggregate performance analytics from the 615 historical backtested trading sessions
    ($2.67M Total Net P&L, 83.6% Win Rate, Profit Factor 4.53).
    """
    res = cmio_agent_service.get_backtest_statistics(db)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error"))
    return res


@router.get("/backtest/trades")
async def get_backtest_trades(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    filter_type: Optional[str] = Query(None, description="PARENTS_ONLY, CE, PE, WINS, LOSSES"),
    search: Optional[str] = Query(None, description="Search by index, date, or type"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Returns paginated, searchable, and filterable trade records from the backtest database.
    """
    return cmio_agent_service.get_backtest_trades(
        db=db,
        limit=limit,
        offset=offset,
        filter_type=filter_type,
        search=search
    )


@router.get("/next-day-setup")
async def get_next_day_trade_setup(
    underlying: str = Query("BTC", description="Underlying symbol"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Terminal-First MCP Engine:
    Computes exact strikes, entry timing (9:30 PM), profit targets, and stop-loss buffer
    for the upcoming trading session based on live Delta market data + 615-session backtest edge.
    """
    return await cmio_agent_service.generate_next_day_trade_setup(db=db, underlying=underlying)


@router.post("/run-council")
async def run_council_deliberation(
    underlying: str = Query("BTC"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Triggers an on-demand council deliberation cycle across all 5 research leads.
    """
    return await cmio_agent_service.generate_next_day_trade_setup(db=db, underlying=underlying)


@router.get("/directory")
async def get_agents_directory() -> Dict[str, Any]:
    """
    Returns full directory of all 22 institutional AI agents (Chief, 5 Leads, 16 Analysts)
    with roles, status, avatars, and quick prompt suggestions.
    """
    return multi_agent_chat_service.get_directory()


@router.post("/chat")
async def chat_with_agent(
    req: AgentChatRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    1-on-1 personal chat or hierarchical consultation with any of the 22 agents.
    Chief can consult 5 Leads, Leads can consult their Analysts, or user can question any Analyst directly.
    """
    return await multi_agent_chat_service.chat_with_agent(
        agent_id=req.agent_id,
        message=req.message,
        conversation_history=req.conversation_history,
        delegate_to_subordinates=req.delegate_to_subordinates,
        db=db
    )


@router.get("/autonomous-consensus")
async def get_autonomous_consensus(
    underlying: str = Query("BTC", description="Underlying crypto asset (default: BTC)"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Synthesizes Multi-Model Consensus (Regime + ML + Risk Gates + Microstructure + News)
    along with clarity and votes from all 5 specialized research leads to produce an
    autonomous Direct Entry Signal for BTC with strict risk management.
    """
    return await cmio_agent_service.get_autonomous_consensus(db=db, underlying=underlying)


class DispatchAutonomousOrderRequest(BaseModel):
    underlying: str = Field("BTC", description="Asset symbol")
    execution_mode: str = Field("SIMULATED", description="SIMULATED or LIVE")


@router.post("/dispatch-autonomous-order")
async def dispatch_autonomous_order(
    req: DispatchAutonomousOrderRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Executes or simulates the Direct Entry order generated by the CMIO Multi-Model Consensus,
    arming the real-time watchdog stop loss and profit target decay capture.
    """
    return await cmio_agent_service.dispatch_autonomous_order(
        db=db,
        underlying=req.underlying,
        execution_mode=req.execution_mode
    )


@router.get("/live-radar")
async def get_live_radar(
    underlying: str = Query("BTC", description="Underlying asset (default: BTC)"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Returns real-time visual telemetry for CMIO Live Strike Radar:
    - Strikes Watching vs On Hold vs Executed
    - 3-Tier Multi-Agent Hierarchy (16 Analysts -> 5 Managers -> CMIO)
    - Individual Manager Reports & Platform Data Feeds
    """
    return await cmio_agent_service.get_live_radar_state(db=db, underlying=underlying)


@router.get("/ai-status")
async def get_ai_engine_status() -> Dict[str, Any]:
    """
    Returns transparency details about which free-tier AI models and keys are active
    (Google Gemini Free Tier, DeepSeek Open Source, or Deterministic Quant Engine).
    """
    return multi_agent_chat_service.get_ai_engine_status()



