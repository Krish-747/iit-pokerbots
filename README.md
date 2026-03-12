IIT Pokerbots 2026 - Sneak Peek Hold'em Bot

My submission for IIT Pokerbots 2026 (Sneak Peek Hold'em variant). Advanced bot with Monte Carlo equity calculations, opponent modeling, dynamic auction strategy, and EV-based multi-street decisions.
Features

    Monte Carlo Equity Engine (eval7 accelerated, 300-400 iterations per decision)

        Simulates board runouts + opponent ranges on all streets

        Handles known opponent cards (when we win auction)

        Pure Python fallback evaluator if eval7 unavailable

    Hand Classification (7-tier system):

    text
    straight_flush → quads → full_house → flush → straight → set → trips → two_pair → overpair → top_pair → draws → air

        Board textures: dry, drawy, paired, wet_flush, wet_straight

    Opponent Modeling (OpponentModel class):

        Preflop raise rate (maniac detection: >45%, extreme maniacs >75%)

        Postflop aggression (raises/calls/folds)

        Auction bid tracking: Exact bids (when we see opp card) + inferred bids (when we lose)

        Bayesian winrate discounting for tight opponents who show strength

    Sneak Peek Auction Strategy:

        Equity-based bid sizing (35-70% pot max)

        Adapts to opponent's avg/75th percentile bids

        Caps at 25% stack, 55% pot to avoid spew

        Tracks auction outcomes for future adjustments

    Postflop Decision Making:

    text
    MONSTER = {straight_flush, quads, full_house, flush, straight, set}
    STRONG  = {trips, two_pair, overpair}
    DECENT  = {top_pair}
    DRAW    = {flush_draw, oesd, combo_draw}

        EV calls: (wr × (pot + cost)) - cost > 0

        C-bets when preflop aggressor

        Auction paranoia: Folds non-nuts when opponent sees our card

        Dynamic call sizing by hand strength + pot odds

Quick Start

bash
# 1. Setup virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt  # Installs eval7

# 3. Single match test
python engine.py

# 4. Batch testing (20 matches + auto-analysis)
chmod +x test.bash
./test.bash 20

Files
File	Purpose
new_bot.py	Core bot - Player(BaseBot) implementation
test.bash	Batch runner → engine → log analysis pipeline
test.py	.glog parser: net chips, max win/loss, auction stats
engine.py	IIT Pokerbots engine (1000 rounds × 5000-chip stacks)
config.py	EDIT THIS: bot_a = "new_bot.Player"
pkbot/	Framework package (states, actions, base, runner)
requirements.txt	eval7 + engine dependencies
Testing Output

text
File Name                     | BotA Net  | BotA Max Win   | BotA Max Loss  | Auction Wins (A:B)
--------------------------------------------------------------------------------------
match1.glog                   | +245      | +1567          | -892           | 23 - 17
match2.glog                   | -123      | +2345          | -1567          | 19 - 24
...
--------------------------------------------------------------------------------------
OVERALL BotA Net:  +12345           OVERALL BotB Net:  -12345

Key metrics:

    BotA Net: Total profit/loss across all matches

    Max Win/Loss: Single-hand variance

    Auction Wins: Information battle performance

Configuration

Edit config.py:

python
bot_a = "new_bot.Player"      # Your bot (BotA)
bot_b = "example_bot.Player"  # Opponent (BotB)
num_rounds = 1000             # Full match length

Key Parameters (new_bot.py)

Tune these for metagame:

python
OPP_RAISE_THRESH  = [0.20, 0.28, 0.42, 0.58, 0.72]  # Raise-level winrate floors
BAYESIAN_DISCOUNT = 0.88                             # Tight opponent WR adjustment
BAYESIAN_FLOOR    = 0.78                             # Prevent over-discounting

# Auction bid caps
abs_cap = max(22, min(110, int(pot * 0.55)))         # Max 55% pot
chip_cap = int(chips * 0.25)                         # Max 25% stack

Usage Workflow

bash
# 1. Quick test
python engine.py

# 2. Statistical testing (50 matches recommended)
./test.bash 50

# 3. Monitor BotA Net growth across runs
# 4. Tweak parameters → repeat

Performance Notes

    Time budget: Adaptive MC iterations (80-400) based on remaining time

    eval7: 5-10x faster than pure Python evaluator

    Auction tracking: 40-hand memory for bid percentiles

    Maniac detection: Widens calling ranges vs high preflop raise frequency


