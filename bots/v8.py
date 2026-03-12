'''
alpha_q bot v9.3 - The Perfected Universal Adapter

CRITICAL UPGRADES FROM v9.2:
1. Zombie Draw Fix: Draw classification is instantly killed on the River. No more semi-bluffing with air.
2. Board-Playing Awareness: Differentiates between a made straight/flush and a board straight/flush to prevent overplaying.
3. Strict River Polarization: Refuses to call massive river overbets with anything less than Middle Pair (wr > 0.60).
'''

from pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from pkbot.states import GameInfo, PokerState
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot

import random, time, collections
from collections import defaultdict

# ---------------------------------------------------------------------------
# EVAL7 SETUP & DECK CONSTANTS
# ---------------------------------------------------------------------------
try:
    import eval7 as _eval7
    _royal = [_eval7.Card(c) for c in ['As','Ks','Qs','Js','Ts']]
    _junk  = [_eval7.Card(c) for c in ['2c','7d','8h','3s','9h']]
    EVAL7_HIGHER_IS_BETTER = _eval7.evaluate(_royal) > _eval7.evaluate(_junk)
    EVAL7_AVAILABLE = True
except ImportError:
    EVAL7_AVAILABLE = False
    EVAL7_HIGHER_IS_BETTER = True

RANK_MAP = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,
            'T':10,'J':11,'Q':12,'K':13,'A':14}
ALL_RANKS   = '23456789TJQKA'
ALL_SUITS   = 'shdc'
FULL_DECK   = [r+s for r in ALL_RANKS for s in ALL_SUITS]

OPP_RAISE_THRESH  = [0.35, 0.45, 0.60, 0.75, 0.85]
BAYESIAN_DISCOUNT = 0.88

# ---------------------------------------------------------------------------
# HAND CLASSIFICATION (v9.3 River/Board Fixed)
# ---------------------------------------------------------------------------
def classify_hand(hole_cards, board_cards):
    if not board_cards: return 'preflop'
    all_cards  = hole_cards + board_cards
    ranks      = [RANK_MAP[c[0]] for c in all_cards]
    suits      = [c[1] for c in all_cards]
    rc         = collections.Counter(ranks)
    sc         = collections.Counter(suits)
    brc        = collections.Counter(RANK_MAP[c[0]] for c in board_cards)
    hole_ranks = [RANK_MAP[c[0]] for c in hole_cards]
    board_ranks= [RANK_MAP[c[0]] for c in board_cards]

    is_flush   = any(c >= 5 for c in sc.values())
    uniq = sorted(set(ranks), reverse=True)
    if 14 in uniq: uniq.append(1)
    is_straight = any(uniq[i] - uniq[i+4] == 4 for i in range(len(uniq)-4))

    # Check if the board ITSELF is the flush or straight
    board_sc = collections.Counter([c[1] for c in board_cards])
    board_is_flush = any(c >= 5 for c in board_sc.values())
    
    board_uniq = sorted(set(board_ranks), reverse=True)
    if 14 in board_uniq: board_uniq.append(1)
    board_is_straight = any(board_uniq[i] - board_uniq[i+4] == 4 for i in range(len(board_uniq)-4)) if len(board_uniq) >= 5 else False

    if is_flush and is_straight: return 'straight_flush'
    counts = sorted(rc.values(), reverse=True)
    if counts[0] == 4: return 'quads'
    if counts[0] == 3 and len(counts) > 1 and counts[1] >= 2: return 'full_house'
    
    # Do not call it a MONSTER if the board is doing all the work
    if is_flush: return 'board_flush' if board_is_flush else 'flush'
    if is_straight: return 'board_straight' if board_is_straight else 'straight'

    if counts[0] == 3:
        trip_rank = [r for r,c in rc.items() if c == 3][0]
        if hole_ranks[0] == trip_rank and hole_ranks[1] == trip_rank: return 'set'
        if trip_rank in hole_ranks: return 'trips'
        return 'board_trips'

    if counts[0] == 2 and len(counts) > 1 and counts[1] >= 2:
        pairs = [r for r,c in rc.items() if c == 2]
        if not any(r in hole_ranks for r in pairs): return 'board_two_pair'
        if sum(1 for r,c in brc.items() if c >= 2) >= 2: return 'board_two_pair'
        return 'two_pair'

    if counts[0] == 2:
        pair_rank = [r for r,c in rc.items() if c == 2][0]
        if hole_ranks[0] == hole_ranks[1]:
            max_b = max(board_ranks) if board_ranks else 0
            if pair_rank > max_b: return 'overpair'
            if pair_rank == max_b: return 'top_pair'
            return 'underpair'
            
        if pair_rank in hole_ranks:
            sb = sorted(set(board_ranks), reverse=True)
            if pair_rank == sb[0]: return 'top_pair'
            if len(sb) > 1 and pair_rank == sb[1]: return 'middle_pair'
            return 'bottom_pair'
        return 'board_pair'

    flush_draw = any(c == 4 for c in sc.values())
    oesd = any(uniq[i] - uniq[i+3] == 3 for i in range(len(uniq)-3))
    if flush_draw and oesd: return 'combo_draw'
    if flush_draw: return 'flush_draw'
    if oesd:       return 'oesd'
    gutshot = any(uniq[i] - uniq[i+3] == 4 for i in range(len(uniq)-3))
    if gutshot: return 'gutshot'
    return 'air'

# ---------------------------------------------------------------------------
# MONTE CARLO WINRATE ENGINE (Time-Safe)
# ---------------------------------------------------------------------------
def mc_winrate(my_cards, board_cards, opp_known=None, iterations=300):
    known = set(my_cards + board_cards)
    if opp_known: known.add(opp_known)
    deck  = [c for c in FULL_DECK if c not in known]
    board_needed    = 5 - len(board_cards)
    opp_unkn_needed = 1 if opp_known else 2
    need = board_needed + opp_unkn_needed
    wins = ties = total = 0

    if EVAL7_AVAILABLE:
        my_e7     = [_eval7.Card(c) for c in my_cards]
        board_e7  = [_eval7.Card(c) for c in board_cards]
        opp_kn_e7 = [_eval7.Card(opp_known)] if opp_known else []
        deck_e7   = [_eval7.Card(c) for c in deck]
        for _ in range(iterations):
            sample    = random.sample(deck_e7, need)
            opp_hand  = opp_kn_e7 + sample[:opp_unkn_needed]
            sim_board = board_e7 + sample[opp_unkn_needed:]
            ms  = _eval7.evaluate(my_e7 + sim_board)
            os_ = _eval7.evaluate(opp_hand + sim_board)
            if EVAL7_HIGHER_IS_BETTER:
                win = ms > os_; tie = ms == os_
            else:
                win = ms < os_; tie = ms == os_
            if win:  wins += 1
            elif tie: ties += 1
            total += 1
    return (wins + 0.5 * ties) / max(1, total)

# ---------------------------------------------------------------------------
# DYNAMIC OPPONENT TRACKING
# ---------------------------------------------------------------------------
class OpponentModel:
    def __init__(self):
        self.opp_bid_pcts = []   
        self.postflop_raises = 0
        self.postflop_calls  = 0
        self.postflop_folds  = 0
        self.postflop_total  = 0
        self.pf_raises = 0
        self.pf_folds  = 0
        self.pf_total  = 0

    def record_auction_win(self, their_bid, pot):
        if 0 < their_bid < 5000 and pot > 0:
            self.opp_bid_pcts.append(their_bid / pot)
            if len(self.opp_bid_pcts) > 60: self.opp_bid_pcts.pop(0)

    def record_auction_loss(self, our_bid, pot):
        if our_bid > 0 and pot > 0:
            inferred_pct = (our_bid + 1) / pot
            self.opp_bid_pcts.append(inferred_pct)
            if len(self.opp_bid_pcts) > 60: self.opp_bid_pcts.pop(0)

    @property
    def avg_opp_bid_pct(self):
        if not self.opp_bid_pcts: return 0.50 
        return sum(self.opp_bid_pcts[-40:]) / len(self.opp_bid_pcts[-40:])

    def rec_post(self, act):
        self.postflop_total += 1
        if act == 'raise':  self.postflop_raises += 1
        elif act == 'call': self.postflop_calls  += 1
        elif act == 'fold': self.postflop_folds  += 1

    def rec_pf(self, act):
        self.pf_total += 1
        if act == 'raise': self.pf_raises += 1
        elif act == 'fold': self.pf_folds  += 1

    @property
    def pf_raise_rate(self):
        return self.pf_raises / max(1, self.pf_total) if self.pf_total >= 10 else 0.50

# ---------------------------------------------------------------------------
# CORE BOT LOGIC
# ---------------------------------------------------------------------------
class Player(BaseBot):
    def __init__(self):
        self.opp = OpponentModel()
        self._hand_num         = 0
        self._cache            = {}
        self._prev_opp_wager   = 0
        self._total_time       = 0.0
        self._time_budget      = 18.5
        self._street_raises    = defaultdict(int)
        self._opp_raises       = defaultdict(int)
        self._wr_discount      = 1.0
        self._hand_start_chips = 0
        self._auction_pre_pot  = 0
        self._our_last_bid     = 0
        self._current_street   = 'preflop'
        self._was_pf_aggressor = False

    def _time_left(self):
        return max(0.05, self._time_budget - self._total_time)

    def _iters(self, street):
        per_round = self._time_left() / max(1, 1000 - self._hand_num)
        if   per_round > 0.05: base = 400
        elif per_round > 0.02: base = 250
        elif per_round > 0.01: base = 150
        else:                  base = 80
        if street == 'pre-flop': return base // 4
        if street == 'auction':  return 60
        return base

    def _raw_wr(self, my_cards, board, opp_known=None, street='flop'):
        key = (tuple(my_cards), tuple(board), opp_known, street)
        if key not in self._cache:
            t0 = time.time()
            self._cache[key] = mc_winrate(my_cards, board, opp_known, self._iters(street))
            self._total_time += time.time() - t0
        return self._cache[key]

    def _winrate(self, my_cards, board, opp_known=None, street='flop'):
        return max(0.05, self._raw_wr(my_cards, board, opp_known, street) * self._wr_discount)

    def _chen(self, cards):
        r1, r2 = RANK_MAP[cards[0][0]], RANK_MAP[cards[1][0]]
        hi, lo = max(r1,r2), min(r1,r2)
        score  = {14:10.0, 13:8.0, 12:7.0, 11:6.0}.get(hi, hi/2.0)
        if r1 == r2: score = max(5.0, score * 2.0)
        if cards[0][1] == cards[1][1]: score += 2.0
        gap = hi - lo - 1
        if gap >= 0: score -= [0,1,2,4,5][min(gap,4)]
        if gap in [0,1] and hi < 12 and r1 != r2: score += 1.0
        return max(0.0, score)

    def _track_opp(self, cs, street):
        if self._current_street != street:
            self._current_street = street
            self._prev_opp_wager = 0
            self._wr_discount    = 1.0
        delta = cs.opp_wager - self._prev_opp_wager
        if delta > 0:
            if street == 'pre-flop':
                self.opp.rec_pf('raise' if delta > cs.cost_to_call else 'call')
            else:
                if delta > max(cs.pot * 0.15, 15):
                    self.opp.rec_post('raise')
                    self._opp_raises[street] += 1
                    if self.opp.pf_raise_rate <= 0.45:
                        self._wr_discount *= BAYESIAN_DISCOUNT
                else:
                    self.opp.rec_post('call')
        self._prev_opp_wager = cs.opp_wager

    def _auction_bid(self, cs):
        my_cards = cs.my_hand
        board    = cs.board
        pot      = cs.pot
        chips    = cs.my_chips

        if chips <= 2: return 0

        wr_base = self._raw_wr(my_cards, board, None, 'auction')
        expected_opp_bid_pct = self.opp.avg_opp_bid_pct
        expected_opp_bid = int(pot * expected_opp_bid_pct)
        
        # Bid Shading (Trap them into bloating the pot)
        if wr_base > 0.75:
            target = max(0, expected_opp_bid - 1)
            if random.random() < 0.30: target = expected_opp_bid + 2 
                
        # Bait (Bid artificially low to setup a Donk Bet)
        elif wr_base < 0.40:
            target = random.randint(3, 9)
            
        # Marginal hands (actually need info)
        else:
            target = expected_opp_bid + int(pot * 0.15) 

        chip_cap = int(chips * 0.60)
        final = min(max(1, min(target, chip_cap)), max(0, chips - 1), 4999)
        self._our_last_bid = final
        return final

    def on_hand_start(self, game_info: GameInfo, cs: PokerState) -> None:
        self._hand_num         = game_info.round_num
        self._cache            = {}
        self._prev_opp_wager   = 0
        self._street_raises    = defaultdict(int)
        self._opp_raises       = defaultdict(int)
        self._wr_discount      = 1.0
        self._hand_start_chips = cs.my_chips
        self._auction_pre_pot  = 0
        self._our_last_bid     = 0
        self._current_street   = 'preflop'
        self._was_pf_aggressor = False

    def on_hand_end(self, game_info: GameInfo, cs: PokerState) -> None:
        pass

    def get_move(self, game_info: GameInfo, cs: PokerState):
        legal = cs.legal_actions
        def can(a): return a in legal

        street   = cs.street
        my_cards = cs.my_hand
        board    = cs.board
        pot      = cs.pot
        cost     = cs.cost_to_call
        chips    = cs.my_chips

        self._track_opp(cs, street)
        opp_known = cs.opp_revealed_cards[0] if cs.opp_revealed_cards else None

        opp_won_auction = False
        we_won_auction  = False

        if street == 'flop' and self._auction_pre_pot > 0:
            pot_delta = pot - self._auction_pre_pot
            if opp_known:
                we_won_auction = True
                if 0 < pot_delta < 5000:
                    self.opp.record_auction_win(int(pot_delta), self._auction_pre_pot)
            else:
                opp_won_auction = True
                if self._our_last_bid > 0:
                    self.opp.record_auction_loss(self._our_last_bid, self._auction_pre_pot)
            self._auction_pre_pot = 0

        # ===================================================================
        # PRE-FLOP
        # ===================================================================
        if street == 'pre-flop':
            chen    = self._chen(my_cards)
            mn, mx = cs.raise_bounds
            
            if chen >= 6.0 or (my_cards[0][0] == my_cards[1][0]): 
                self._was_pf_aggressor = True
                if can(ActionRaise):
                    raise_amt = int(pot * random.uniform(2.5, 4.0)) 
                    return ActionRaise(max(mn, min(raise_amt, mx)))
                if can(ActionCall): return ActionCall()
                
            elif chen >= 4.0:
                if can(ActionRaise) and cost < 50:
                    self._was_pf_aggressor = True
                    return ActionRaise(max(mn, min(int(pot * 2.0), mx)))
                if can(ActionCall): return ActionCall()
                
            else:
                if can(ActionRaise) and random.random() < 0.10 and cost <= 20:
                    self._was_pf_aggressor = True
                    return ActionRaise(max(mn, min(int(pot * 2.5), mx)))
                if can(ActionCheck): return ActionCheck()
                if can(ActionCall) and cost <= 10: return ActionCall()
                self.opp.rec_pf('fold')
                return ActionFold()

        # ===================================================================
        # AUCTION
        # ===================================================================
        if street == 'auction':
            self._auction_pre_pot = pot
            return ActionBid(self._auction_bid(cs))

        # ===================================================================
        # POST-FLOP (v9.3 Hand/River Awareness)
        # ===================================================================
        if street in ['flop', 'turn', 'river']:
            wr      = self._winrate(my_cards, board, opp_known, street)
            hclass  = classify_hand(my_cards, board)
            ev_call = (wr * (pot + cost)) - cost  
            mn, mx  = cs.raise_bounds
            opp_r   = self._opp_raises[street]

            MONSTER = {'straight_flush','quads','full_house','flush','straight','set'}
            STRONG  = {'trips','two_pair','overpair'}

            # 1. TRAP DONK BET
            if street == 'flop' and opp_won_auction and wr < 0.45 and opp_r == 0:
                if can(ActionRaise):
                    donk_amt = int(pot * random.uniform(0.80, 1.20))
                    return ActionRaise(max(mn, min(donk_amt, mx)))

            # 2. ADAPTIVE C-BET
            if self._was_pf_aggressor and opp_r == 0 and street == 'flop':
                opp_fold_rate = self.opp.postflop_folds / max(1, self.opp.postflop_total)
                cbet_freq = 0.90 if opp_fold_rate > 0.40 else (0.40 if opp_fold_rate < 0.20 else 0.70)
                if random.random() < cbet_freq:
                    if can(ActionRaise):
                        cbet_amt = int(pot * random.uniform(0.60, 0.90))
                        return ActionRaise(max(mn, min(cbet_amt, mx)))

            # 3. SCALING AGGRESSION & RESPECT THE RAISE
            if hclass in MONSTER or hclass in STRONG or wr > 0.70:
                if opp_r >= 1: 
                    if hclass in {'top_pair', 'overpair'}:
                        if can(ActionCall) and cost < (pot * 0.40): return ActionCall()
                        self.opp.rec_post('fold')
                        return ActionFold() 
                elif can(ActionRaise) and opp_r == 0:
                    value_bet = int(pot * random.uniform(0.75, 1.30)) 
                    return ActionRaise(max(mn, min(value_bet, mx)))
                if can(ActionCall): return ActionCall()

            # 4. DRAW AGGRESSION (Fixed: No Zombie Draws)
            if hclass in {'combo_draw','flush_draw','oesd'}:
                if street != 'river': # NEVER draw on the river
                    if can(ActionRaise) and opp_r < 2:
                        semi_bluff = int(pot * random.uniform(0.50, 0.85))
                        return ActionRaise(max(mn, min(semi_bluff, mx)))
                    if can(ActionCall) and cost < (pot * 1.5): 
                        return ActionCall()
                else:
                    hclass = 'air' # Demote to air on river

            # 5. POLARIZED BLUFF CATCHING (Fixed: Strict exclusions)
            if street == 'river' and cost > 0:
                if cost < (pot * 0.40) and wr > 0.40:
                    if can(ActionCall): return ActionCall()
                elif cost >= (pot * 0.40) and wr > 0.60:
                    # Exclude weak pairs and unmade hands from calling massive river bets
                    WEAK_HANDS = {'air', 'high_card', 'gutshot', 'flush_draw', 'oesd', 'bottom_pair', 'board_pair', 'underpair'}
                    if hclass not in WEAK_HANDS:
                        if can(ActionCall): return ActionCall()

            # DEFAULT / FALLBACK ACTIONS
            if can(ActionCall) and ev_call > 0 and cost <= (pot * 0.60):
                return ActionCall()
            if can(ActionCheck): return ActionCheck()
            
            self.opp.rec_post('fold')
            return ActionFold()

        if can(ActionCheck): return ActionCheck()
        if can(ActionCall) and cost <= 10: return ActionCall()
        
        self.opp.rec_pf('fold')
        return ActionFold()

if __name__ == '__main__':
    run_bot(Player(), parse_args())
