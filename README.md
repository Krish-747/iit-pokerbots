# IIT Pokerbots 2026 - Sneak Peek Hold'em Bot

My submission for **IIT Pokerbots 2026** (Sneak Peek Hold'em variant). Advanced bot with Monte Carlo equity calculations, opponent modeling, dynamic auction strategy, and EV-based multi-street decisions.

## Features

### Monte Carlo Equity Engine (`eval7` accelerated, 300-400 iterations)
- Simulates board runouts + opponent ranges on all streets
- Handles known opponent cards (when we win auction)
- Pure Python fallback evaluator if `eval7` unavailable

### Hand Classification (7-tier system)
```
straight_flush → quads → full_house → flush → straight → set → trips 
→ two_pair → overpair → top_pair → draws → air
```
**Board textures**: `dry`, `drawy`, `paired`, `wet_flush`, `wet_straight`

### Opponent Modeling (`OpponentModel` class)
- Preflop raise rate (**maniac detection**: >45%, **extreme** >75%)
- Postflop aggression (raises/calls/folds)
- **Auction bid tracking**: Exact (when we see opp card) + inferred (when we lose)
- Bayesian winrate discounting for tight opponents

### Sneak Peek Auction Strategy
- Equity-based bid sizing (**35-70% pot max**)
- Adapts to opponent's avg/75th percentile bids
- Caps: **25% stack**, **55% pot**
- Tracks auction outcomes for adjustments

### Postflop Decision Making
```
MONSTER = {straight_flush, quads, full_house, flush, straight, set}
STRONG  = {trips, two_pair, overpair}
DECENT  = {top_pair}
DRAW    = {flush_draw, oesd, combo_draw}
```
- **EV calls**: `(wr * (pot + cost)) - cost > 0`
- C-bets (preflop aggressor)
- **Auction paranoia**: Fold non-nuts when opponent sees our card
- Dynamic sizing by hand strength + pot odds

## Quick Start

```bash
# 1. Setup venv (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/macOS

# 2. Install
pip install -r requirements.txt  # eval7

# 3. Single match
python engine.py

# 4. Batch test (20 matches + analysis)
chmod +x test.bash
./test.bash 20
```

## Files

| File | Purpose |
|------|---------|
| `new_bot.py` | **Core bot** - `Player(BaseBot)` |
| `test.bash` | Batch → engine → analysis |
| `test.py` | `.glog` parser (net, variance, auctions) |
| `engine.py` | Engine (1000 rounds × 5k stacks) |
| `config.py` | **EDIT**: `bot_a = "new_bot.Player"` |
| `pkbot/` | Framework |

## Testing Output

```
File Name          | BotA Net | Max Win  | Max Loss | Auctions (A:B)
----------------------------------------------------------------------------------------
match1.glog        | +245     | +1567    | -892     | 23-17
match2.glog        | -123     | +2345    | -1567    | 19-24
----------------------------------------------------------------------------------------
OVERALL BotA Net: +12345    BotB Net: -12345
```

**Metrics**:
- **BotA Net**: Total P/L
- **Max Win/Loss**: Variance
- **Auction Wins**: Info battle

## Configuration

**`config.py`**:
```python
bot_a = "new_bot.py"     # Opponent A
bot_b = "example_bot.py" # Opponent B
```

## Key Parameters (`new_bot.py`)

```python
OPP_RAISE_THRESH  = [0.20, 0.28, 0.42, 0.58, 0.72]  # Raise floors
BAYESIAN_DISCOUNT = 0.88                            # Tight opp adjustment
BAYESIAN_FLOOR    = 0.78                            # WR cap

# Auction caps
abs_cap = max(22, min(110, pot * 0.55))    # 55% pot
chip_cap = chips * 0.25                    # 25% stack
```

## Usage Workflow

```bash
python engine.py                    # Quick test
./test.bash 50                      # Stats (50+ matches)
# Monitor BotA Net ↑
# Tune params → repeat
```

## Performance Notes

| Feature | Detail |
|---------|--------|
| **Time** | Adaptive MC (80-400 iters) |
| **eval7** | 5-10x faster than Python |
| **Auction** | 40-hand bid memory |
| **Maniacs** | Wider calls vs high PF raise% |

