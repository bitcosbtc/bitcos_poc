import json
import re
from pathlib import Path
import sys

backend_dir = Path("/mnt/c/Users/monuk/OneDrive/Desktop/Bitcos-Poc/bitcos_poc")
sys.path.insert(0, str(backend_dir))

from app.database import engine, Base, SessionLocal
from app.models.backtest_trade import BacktestTrade

# 1. Ensure table exists
Base.metadata.create_all(bind=engine)

transcript_path = Path("/mnt/c/Users/monuk/.gemini/antigravity/brain/c1f514f6-f44f-4d80-ac3b-07d1b65e54c0/.system_generated/logs/transcript_full.jsonl")
if not transcript_path.exists():
    transcript_path = Path("/mnt/c/Users/monuk/.gemini/antigravity/brain/c1f514f6-f44f-4d80-ac3b-07d1b65e54c0/.system_generated/logs/transcript.jsonl")

raw_content = ""
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("type") == "USER_INPUT":
            c = data.get("content", "")
            if "615.2" in c:
                raw_content = c

if not raw_content:
    print("Error: Could not find user input with 615.2")
    sys.exit(1)

# Find where the table starts: "Index\t\t\tCE+PE Exe." or similar
table_start = raw_content.find("Index")
if table_start == -1:
    print("Error: Could not find Index in content")
    sys.exit(1)

table_text = raw_content[table_start:]
lines = table_text.splitlines()

print(f"Total lines in table block: {len(lines)}")

parsed_trades = []
current_parent_index = "1"

for i, line in enumerate(lines):
    line_str = line.strip()
    if not line_str or line_str.startswith("Index") or "613\t346\t347" in line_str:
        continue
    
    parts = [p.strip() for p in line.split("\t")]
    if len(parts) < 2:
        continue
    
    idx = parts[0] if parts[0] else ""
    if not idx:
        continue
        
    is_parent = "." not in idx
    if is_parent:
        current_parent_index = idx
        parent_idx = idx
    else:
        parent_idx = idx.split(".")[0]
        
    # Helper to safely parse float
    def to_float(val):
        if not val:
            return None
        cleaned = re.sub(r"[^\d.-]", "", val)
        try:
            return float(cleaned)
        except ValueError:
            return None

    def to_int(val):
        if not val:
            return None
        try:
            return int(re.sub(r"[^\d]", "", val))
        except ValueError:
            return None

    # Line formats:
    # Parent row:
    # idx \t \t \t entry_date \t entry_time \t exit_date \t exit_time \t ... \t pnl
    # Child row:
    # idx \t ce_exe \t pe_exe \t ? \t entry_date \t entry_time \t exit_date \t exit_time \t type \t strike \t b_s \t qty \t entry_p \t exit_p \t pnl
    
    # Let's inspect parts
    pnl = None
    strike = None
    entry_p = None
    exit_p = None
    qty = None
    opt_type = None
    buy_sell = None
    entry_date = None
    entry_time = None
    exit_date = None
    exit_time = None
    ce_exe = None
    pe_exe = None
    
    # The last non-empty element is usually P/L
    non_empty = [p for p in parts if p]
    if not non_empty:
        continue
        
    # Find P/L from the end
    pnl = to_float(non_empty[-1])
    
    if is_parent:
        # e.g., ['1', '', '', '', 'Tue, Dec 31, 2024', '9:30:00 PM', 'Thu, Jan 2, 2025', '5:27:00 PM', '', '', '', '', '', '', '16917.55']
        # Find dates
        dates = [p for p in parts if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}-\d{2}-\d{2})\b", p)]
        times = [p for p in parts if re.search(r"\b(AM|PM)\b", p)]
        
        if len(dates) >= 1:
            entry_date = dates[0]
        if len(dates) >= 2:
            exit_date = dates[1]
        if len(times) >= 1:
            entry_time = times[0]
        if len(times) >= 2:
            exit_time = times[1]
            
        opt_type = "STRANGLE"
        buy_sell = "Sell"
        strategy = "0DTE/2DTE Short Strangle"
    else:
        # e.g. ['1.1', '1', '', '1', 'Tue, Dec 31, 2024', '9:30:00 PM', 'Thu, Jan 2, 2025', '5:27:00 PM', 'CE', '99600', 'Sell', '0.5', '267.83', '0.1', '11378.52']
        if "CE" in non_empty:
            opt_type = "CE"
            ce_exe = 1
        elif "PE" in non_empty:
            opt_type = "PE"
            pe_exe = 1
            
        if "Sell" in non_empty:
            buy_sell = "Sell"
        elif "Buy" in non_empty:
            buy_sell = "Buy"
            
        dates = [p for p in parts if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}-\d{2}-\d{2})\b", p)]
        times = [p for p in parts if re.search(r"\b(AM|PM)\b", p)]
        if len(dates) >= 1:
            entry_date = dates[0]
        if len(dates) >= 2:
            exit_date = dates[1]
        if len(times) >= 1:
            entry_time = times[0]
        if len(times) >= 2:
            exit_time = times[1]
            
        # Find strike, qty, entry_price, exit_price
        # Usually: ... type, strike, b_s, qty, entry_p, exit_p, pnl
        if opt_type in non_empty:
            type_idx = non_empty.index(opt_type)
            if type_idx + 1 < len(non_empty):
                strike = to_float(non_empty[type_idx + 1])
            # qty is usually after 'Sell' or 'Buy'
            if buy_sell in non_empty:
                bs_idx = non_empty.index(buy_sell)
                if bs_idx + 1 < len(non_empty):
                    qty = to_float(non_empty[bs_idx + 1])
                if bs_idx + 2 < len(non_empty):
                    entry_p = to_float(non_empty[bs_idx + 2])
                if bs_idx + 3 < len(non_empty):
                    exit_p = to_float(non_empty[bs_idx + 3])
                    
        strategy = f"BTC {opt_type} {buy_sell or 'Sell'}"
        
    parsed_trades.append({
        "trade_index": idx,
        "parent_index": parent_idx,
        "is_parent": is_parent,
        "ce_exe": ce_exe,
        "pe_exe": pe_exe,
        "entry_date": entry_date,
        "entry_time": entry_time,
        "exit_date": exit_date,
        "exit_time": exit_time,
        "option_type": opt_type,
        "strike": strike,
        "buy_sell": buy_sell,
        "qty": qty,
        "entry_price": entry_p,
        "exit_price": exit_p,
        "pnl": pnl,
        "strategy": strategy
    })

print(f"Successfully parsed {len(parsed_trades)} trade records!")

# Save to JSON
json_path = backend_dir / "data" / "backtest_trades.json"
json_path.parent.mkdir(parents=True, exist_ok=True)
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(parsed_trades, f, indent=2)

print(f"Saved to {json_path}")

# Seed into database
db = SessionLocal()
try:
    # Clear existing to avoid duplicates
    db.query(BacktestTrade).delete()
    db.commit()
    
    trade_objs = [BacktestTrade(**item) for item in parsed_trades]
    db.bulk_save_objects(trade_objs)
    db.commit()
    print(f"Successfully seeded {len(trade_objs)} records into 'backtest_trades' table!")
except Exception as e:
    db.rollback()
    print("Database seeding error:", e)
finally:
    db.close()

# Calculate stats
parents = [t for t in parsed_trades if t["is_parent"] and t["pnl"] is not None]
total_pnl = sum(t["pnl"] for t in parents)
wins = [t for t in parents if t["pnl"] > 0]
losses = [t for t in parents if t["pnl"] < 0]
win_rate = (len(wins) / len(parents) * 100) if parents else 0
total_win_pnl = sum(t["pnl"] for t in wins)
total_loss_pnl = abs(sum(t["pnl"] for t in losses))
profit_factor = (total_win_pnl / total_loss_pnl) if total_loss_pnl > 0 else 999.0

print(f"\n--- BACKTEST SUMMARY STATS ---")
print(f"Total Trading Sessions (Parent Strangle trades): {len(parents)}")
print(f"Total Records (Parents + Legs): {len(parsed_trades)}")
print(f"Total Net P&L: ${total_pnl:,.2f}")
print(f"Win Rate: {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
print(f"Profit Factor: {profit_factor:.2f}")
if wins:
    print(f"Average Win: ${sum(t['pnl'] for t in wins) / len(wins):,.2f}")
if losses:
    print(f"Average Loss: ${sum(t['pnl'] for t in losses) / len(losses):,.2f}")
