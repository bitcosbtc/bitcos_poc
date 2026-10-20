import asyncio
import json
from typing import Dict, Any, Optional, List
import requests
from ..config import settings


class AIAdvisorService:
    def __init__(self):
        self.model = "gpt-4o-mini"
        self.openai_url = "https://api.openai.com/v1/chat/completions"
        self.gemini_base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _get_api_key(self) -> Optional[str]:
        return getattr(settings, "GEMINI_API_KEY", None) or settings.OPENAI_API_KEY

    def _call_gemini_sync(self, api_key: str, system_prompt: str, user_content: str, timeout: float = 8.0) -> Optional[str]:
        model = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        url = f"{self.gemini_base_url}/{model}:generateContent?key={api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 900}
        }
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    parts = candidates[0]["content"].get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
        except Exception as e:
            print(f"[Gemini Advisor] Error: {e}")
        return None

    def _call_openai_sync(self, api_key: str, payload: Dict[str, Any], timeout: float = 6.0) -> Dict[str, Any]:
        res = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=timeout
        )
        return {
            "status_code": res.status_code,
            "text": res.text,
            "data": res.json() if res.status_code == 200 else None
        }

    async def generate_market_advisory(
        self,
        regime_metrics: Dict[str, Any],
        active_positions: Optional[List[Dict[str, Any]]] = None,
        custom_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calls OpenAI ChatGPT (gpt-4o-mini) to synthesize 11-factor scores, volatility structure,
        and open positions into institutional advice in professional English.
        """
        api_key = self._get_api_key()
        if not api_key:
            return {
                "success": True,
                "model": "rule-based",
                "advisory": self._generate_rule_based_fallback(regime_metrics)
            }

        expiries = regime_metrics.get("expiries", [])
        active_exp = expiries[0] if expiries else {}
        scores = active_exp.get("scores", {})
        unified = scores.get("unified_conclusion", {})
        market = regime_metrics.get("market", {})

        system_prompt = (
            "You are Bitcos AI Trading Advisor & Chief Risk Officer, an institutional quantitative options specialist "
            "for Bitcoin (BTC) on Delta Exchange. You strictly adhere to the BTC Options Regime Guide V2.6.1 rules:\n"
            "- Step 1: ATM IV vs RV spread (Vol Rich vs Cheap).\n"
            "- Step 2: 11-Factor Regime Scores (SELL vs BUY, >=10 pts dominance hurdle).\n"
            "- Step 3: Safety Risk Overrides (DTE penalty, Gamma shock, Skew, ATR expansion).\n"
            "- Step 4: ~18Δ Strangle Execution (Target Net Profit $25 USD / 2.5% ROC on $1,000 capital, 35% premium decay capture).\n"
            "- Step 5: Historical 20-session excursion survival rate.\n\n"
            "Communicate in clear, concise, institutional English with standard financial and quantitative terminology. "
            "Prioritize capital preservation: keep losses tiny, exit early on wing breach threats, and book profits when target decay is reached.\n"
            "Respond ONLY with a valid JSON object matching the requested schema."
        )

        user_content = {
            "spot_price": market.get("spot_price"),
            "underlying": regime_metrics.get("underlying", "BTC"),
            "active_expiry": active_exp.get("label"),
            "expiry_date": active_exp.get("expiry_date"),
            "atm_iv": active_exp.get("atm_iv"),
            "rv_0dte": active_exp.get("rv_0dte"),
            "iv_rv_spread": active_exp.get("iv_rv_spread"),
            "sell_score": scores.get("sell_score"),
            "buy_score": scores.get("buy_score"),
            "final_decision": unified.get("final_decision"),
            "action": unified.get("action"),
            "trade_selection": unified.get("trade_selection"),
            "confidence_score": unified.get("confidence_score"),
            "dominance_gap": unified.get("dominance_gap"),
            "passed_gates": f"{unified.get('passed_gates')}/5",
            "historical_survival_rate": f"{unified.get('survival_rate_pct')}%",
            "open_positions": active_positions or [],
            "custom_query": custom_query
        }

        json_instruction = """
        Return a JSON object with EXACTLY these keys:
        {
            "headline": "Short bold conclusion (e.g. 🎯 BTC 0DTE: Selective Sell - Short Strangle Favored)",
            "current_situation": "2 sentences explaining IV-RV spread and who has edge right now",
            "recommended_setup": "Specific trade recommendation (e.g. Short Strangle Sell 18Δ Put & Call, or Long Straddle, or Stay in Cash)",
            "risk_assessment": "SAFE / MODERATE / ELEVATED / CRITICAL with 1 sentence reason",
            "profit_booking_advice": "Clear advice on when/how to book profit (e.g. 'Close position promptly upon capturing 35% decay ($25 USD)')",
            "loss_protection_rule": "Strict stop-loss or adjustment trigger (e.g. 'Exit immediately if spot approaches within 25% of Put or Call wing')",
            "executive_summary_hinglish": "3-4 crisp sentences in natural professional English summarizing the exact game plan"
        }
        """

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this live market state and provide advisory:\n{json.dumps(user_content, indent=2)}\n\n{json_instruction}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }

        try:
            call_result = await asyncio.to_thread(self._call_openai_sync, api_key, payload, 6.0)
            if call_result["status_code"] == 200 and call_result["data"]:
                data = call_result["data"]
                reply_text = data["choices"][0]["message"]["content"]
                parsed_advisory = json.loads(reply_text)

                return {
                    "success": True,
                    "model": self.model,
                    "advisory": parsed_advisory
                }
            else:
                return {
                    "success": True,
                    "model": "rule-based",
                    "advisory": self._generate_rule_based_fallback(regime_metrics)
                }
        except Exception:
            return {
                "success": True,
                "model": "rule-based",
                "advisory": self._generate_rule_based_fallback(regime_metrics)
            }

    async def generate_live_alert_copy(
        self,
        alert_type: str,
        title: str,
        context_data: Dict[str, Any]
    ) -> str:
        """
        Uses ChatGPT to format a punchy, urgent alert text in professional English for Email / Telegram.
        """
        api_key = self._get_api_key()
        if not api_key:
            return f"[{alert_type}] {title}\nDetails: {json.dumps(context_data)}"

        prompt = (
            f"You are a live trading alert bot. Write a concise, high-urgency notification in clear, direct English. "
            f"Type: {alert_type}. Title: {title}. Data: {json.dumps(context_data)}.\n"
            "Format: 3-5 bullet points. Include Action to take, Risk level, and Profit/Stop recommendation. Maximum 70 words."
        )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }

        try:
            call_result = await asyncio.to_thread(self._call_openai_sync, api_key, payload, 10.0)
            if call_result["status_code"] == 200 and call_result["data"]:
                data = call_result["data"]
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        # Fallback if API fails
        return f"{title}\nMarket State: {context_data.get('summary', 'Regime updated.')}\nRecommended Action: {context_data.get('action', 'Check dashboard')}"

    async def answer_user_query(
        self,
        user_message: str,
        regime_metrics: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Interactive conversational endpoint: user can ask any trading question, request setup updates,
        or ask risk/profit guidance directly in natural English.
        """
        api_key = self._get_api_key()
        expiries = regime_metrics.get("expiries", [])
        active_exp = expiries[0] if expiries else {}
        scores = active_exp.get("scores", {})
        unified = scores.get("unified_conclusion", {})
        market = regime_metrics.get("market", {})
        spot = market.get("spot_price")

        if not api_key:
            return {
                "success": True,
                "reply": f"Live Market State: BTC Spot is currently ${spot}. Quantitative Consensus: {unified.get('final_decision')}, Recommended Setup: {unified.get('trade_selection')}. Strictly enforce the $25 USD profit capture target and the 25% wing proximity stop-loss rule.",
                "model": "rule-based"
            }

        system_prompt = (
            "You are Bitcos AI Trading Copilot & Chief Risk Officer, an elite quantitative Bitcoin options trading assistant "
            "for Delta Exchange. You strictly follow institutional BTC Options Regime Guide V2.6.1:\n"
            "- Step 1: ATM IV vs RV spread (Vol Rich = Selling edge, Vol Cheap = Buying edge).\n"
            "- Step 2: 11-Factor Regime Scores (SELL vs BUY, >=10 pts dominance hurdle).\n"
            "- Step 3: Safety Risk Overrides (DTE penalty, Gamma shock, Skew, ATR expansion).\n"
            "- Step 4: ~18Δ Strangle Execution (Target Net Profit $25 USD / 2.5% ROC on $1,000 capital, 35% decay capture).\n"
            "- Step 5: Historical 20-session excursion survival rate.\n\n"
            "CURRENT LIVE MARKET DATA:\n"
            f"- BTC Spot Price: ${spot}\n"
            f"- Expiry: {active_exp.get('label')} ({active_exp.get('expiry_date')})\n"
            f"- ATM IV: {active_exp.get('atm_iv')}%, RV: {active_exp.get('rv_0dte')}%, Spread: {active_exp.get('iv_rv_spread')} vol pts\n"
            f"- Sell Score: {scores.get('sell_score')}/100, Buy Score: {scores.get('buy_score')}/100\n"
            f"- Model Consensus: {unified.get('final_decision')} (Tilt: {unified.get('decision_tilt')})\n"
            f"- Recommended Setup: {unified.get('trade_selection')}\n"
            f"- Dominance Gap: {unified.get('dominance_gap')} pts, Confidence: {unified.get('confidence_score')}%\n"
            f"- Passed Gates: {unified.get('passed_gates')}/5, Historical Survival: {unified.get('survival_rate_pct')}%\n\n"
            "COMMUNICATION GUIDELINES:\n"
            "- Speak in a friendly, professional, authoritative institutional English tone like an elite quantitative crypto options trader.\n"
            "- Answer the user's specific prompt directly and concisely (under 130 words unless they ask for detailed steps).\n"
            "- Use bullet points or bold text where appropriate for clarity.\n"
            "- Always prioritize capital preservation: remind about the $25 USD / 35% profit target and the 25% wing proximity stop-loss rule."
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for item in conversation_history[-6:]:
                messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})

        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3
        }

        try:
            call_result = await asyncio.to_thread(self._call_openai_sync, api_key, payload, 15.0)
            if call_result["status_code"] == 200 and call_result["data"]:
                data = call_result["data"]
                reply_text = data["choices"][0]["message"]["content"].strip()
                return {
                    "success": True,
                    "reply": reply_text,
                    "model": self.model
                }
            else:
                return {
                    "success": False,
                    "error": call_result.get("text", "OpenAI call failed"),
                    "reply": f"Live Market Status: BTC Spot is currently ${spot}. Active Regime: {unified.get('final_decision')} | Setup: {unified.get('trade_selection')}. Profit target: $25 USD / 35% decay capture.",
                    "model": "fallback"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "reply": f"Live Market Status: BTC Spot is currently ${spot}. Setup: {unified.get('trade_selection')}. Maintain strict adherence to all risk gate protocols.",
                "model": "fallback"
            }

    def _generate_rule_based_fallback(self, regime_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fast mathematical fallback if OpenAI key is missing or offline.
        """
        expiries = regime_metrics.get("expiries", [])
        active_exp = expiries[0] if expiries else {}
        scores = active_exp.get("scores", {})
        unified = scores.get("unified_conclusion", {})

        decision = unified.get("final_decision", "EVALUATING")
        tilt = unified.get("decision_tilt", "NEUTRAL")

        return {
            "headline": f"🎯 Regime Consensus: {decision}",
            "current_situation": f"ATM IV {active_exp.get('atm_iv')}% vs RV {active_exp.get('rv_0dte')}%. Spread: {active_exp.get('iv_rv_spread')} vol pts.",
            "recommended_setup": unified.get("trade_selection", "Wait for high edge"),
            "risk_assessment": "MODERATE — Follow risk gate overrides strictly",
            "profit_booking_advice": "Exit position promptly upon capturing 35% premium decay ($25 USD).",
            "loss_protection_rule": "Cut losses immediately if strangle wing breach proximity exceeds 75%.",
            "executive_summary_hinglish": f"A quantitative edge is developing on the {tilt} side. Align with the multi-step consensus to {unified.get('action', 'monitor')} while keeping all risk gates clear."
        }


ai_advisor_service = AIAdvisorService()

