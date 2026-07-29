# FRONTEND DEVELOPER SPECIFICATION: DELTA EXCHANGE UI TO WEBSOCKET FIELD MAPPING
# This document defines how to map and display the Delta Exchange Positions UI fields
# using the WebSocket payloads and formulas.

"""
================================================================================
PART 1: WEBSOCKET INCOMING MESSAGE ROUTING (TYPE-BASED HANDLING)
================================================================================

The WebSocket feeds all data through a single stream. The frontend developer should 
route the messages based on the \"type\" attribute:

1. IF (message.type == \"ticker\") -> Public Options chain price stream.
   * Use this to update live Mark Prices ("m") and Spot Prices ("sp").
   
2. IF (message.type == \"positions\") -> Private positions stream.
   * Receives the initial snapshot (action: \"snapshot\") of positions, 
     and updates (action: \"update\") when sizes change.

3. IF (message.type == \"orders\") -> Private orders stream.
   * Receives snapshots and lifecycle updates for standard and stop trigger orders.

================================================================================
PART 2: FIELD-BY-FIELD MAPPING SPECIFICATION FOR POSITIONS TAB
================================================================================

Referencing the columns shown in the Delta Exchange Positions UI:

--------------------------------------------------------------------------------
1. COLUMN Name: Symbol
   * What is it: The option contract code (e.g., "P-BTC-60400-150726").
   * Source    : DIRECT
   * WS Path   : positions.payload.product_symbol  (or product.symbol)
--------------------------------------------------------------------------------
2. COLUMN Name: Size
   * What is it: The active contract position in BTC/ETH (e.g., "-0.001 BTC").
   * Source    : CALCULATED
   * Formula   : Size_in_BTC = positions.payload.size * positions.payload.product.contract_value
   * Example   : Size = -1, contract_value = 0.001 
                 -1 * 0.001 = -0.001 BTC (Negative indicates Short/Sell)
--------------------------------------------------------------------------------
3. COLUMN Name: Notional
   * What is it: The total underlying value of the contract in USD (e.g., "64.07 USD").
   * Source    : CALCULATED
   * Formula   : Notional = abs(Size_in_BTC) * Spot_Price
   * Example   : |-0.001| * 64501.5 (sp from ticker) = 64.50 USD
--------------------------------------------------------------------------------
4. COLUMN Name: Entry Price
   * What is it: The premium price at which the trade was entered (e.g., "0.9").
   * Source    : DIRECT
   * WS Path   : positions.payload.entry_price
--------------------------------------------------------------------------------
5. COLUMN Name: TP / SL
   * What is it: Target Profit and Stop Loss triggers.
   * Source    : DIRECT (from bracket order flags or active trigger orders list)
   * WS Path   : positions.payload.bracket_take_profit_price (for TP)
                 positions.payload.bracket_stop_loss_price (for SL)
--------------------------------------------------------------------------------
6. COLUMN Name: Index Price
   * What is it: The current price of the underlying asset (e.g., "64072.5").
   * Source    : DIRECT (from Ticker stream)
   * WS Path   : ticker.sp (e.g. data.sp)
--------------------------------------------------------------------------------
7. COLUMN Name: Mark Price
   * What is it: The current option premium price (e.g., "0.6").
   * Source    : DIRECT (from Ticker stream)
   * WS Path   : ticker.d[0].m (e.g., data.d[0].m)
--------------------------------------------------------------------------------
8. COLUMN Name: Margin
   * What is it: The collateral locked for this position in USD (e.g., "0.37 USD").
   * Source    : DIRECT
   * WS Path   : positions.payload.margin
--------------------------------------------------------------------------------
9. COLUMN Name: UPNL (Unrealized Profit/Loss)
   * What is it: Live unrealized PnL (e.g., "-0.00 USD" or "-0.03%").
   * Source    : CALCULATED
   * Formula (USD):
       - If Size is positive (LONG):
         UPNL_USD = (Mark_Price - Entry_Price) * abs(Size) * contract_value * Spot_Price
       - If Size is negative (SHORT):
         UPNL_USD = (Entry_Price - Mark_Price) * abs(Size) * contract_value * Spot_Price
   * Formula (Percentage %):
       - UPNL_Pct = (UPNL_USD / Margin) * 100
--------------------------------------------------------------------------------
10. COLUMN Name: Est. Liq. Price (Estimated Liquidation Price)
    * What is it: The underlying price where the position gets liquidated.
    * Source    : DIRECT
    * WS Path   : positions.payload.liquidation_price
--------------------------------------------------------------------------------
"""
