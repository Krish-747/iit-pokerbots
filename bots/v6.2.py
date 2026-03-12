'''
alpha_q bot v7.1 — The True v5.py Upgrade

CRITICAL UPGRADES OVER v5:
1. Chen Formula Fix: Pocket pairs no longer trigger an array index bug that subtracted 5 points from their pre-flop score.
2. Monte Carlo Card Blocker: The MC simulator now perfectly utilizes the opponent's revealed card to calculate true equity.
3. Clean Architecture: All the messy, chip-bleeding "Opportunistic Bluffs" and poisoned dynamic tracking from v6+ have been purged. We are back to v5's disciplined value poker.
'''

from pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from pkbot.states import GameInfo, PokerState
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot

import random, time, collections
from collections import defaultdict

# ---------------------------------------------------------------------------
# EVAL7 SETUP
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

# ---------------------------------------------------------------------------
# CONSTANTS & CLASSIFIERS
# ---------------------------------------------------------------------------
RANK_MAP = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,
            'T':10,'J':11,'Q':12,'K':13,'A':14}
ALL_RANKS   = '23456789TJQKA'
ALL_SUITS   = 'shdc'
FULL_DECK   = [r+s for r in ALL_RANKS for s in ALL_SUITS]

OPP_RAISE_THRESH = [0.35, 0.45, 0.60, 0.75, 0.85]
BAYESIAN_DISCOUNT = 0.88       

def classify_hand(hole_cards, board_cards):
    if not board_cards: return 'preflop'
    all_cards   = hole_cards + board_cards
    ranks       = [RANK_MAP[c[0]] for c in all_cards]
    suits       = [c[1] for c in all_cards]
    rc          = collections.Counter(ranks)
    sc          = collections.Counter(suits)
    brc         = collections.Counter(RANK_MAP[c[0]] for c in board_cards)
    hole_ranks  = [RANK_MAP[c[0]] for c in hole_cards]
    board_ranks = [RANK_MAP[c[0]] for c in board_cards]

    is_flush = any(c >= 5 for c in sc.values())
    uniq = sorted(set(ranks), reverse=True)
    if 14 in uniq: uniq.append(1)
    is_straight = any(uniq[i] - uniq[i+4] == 4 for i in range(len(uniq)-4))

    if is_flush and is_straight: return 'straight_flush'
    counts = sorted(rc.values(), reverse=True)
    if counts[0] == 4: return 'quads'
    if counts[0] == 3 and len(counts) > 1 and counts[1] >= 2: return 'full_house'
    if is_flush:    return 'flush'
    if is_straight: return 'straight'

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
        sb = sorted(set(board_ranks), reverse=True)
        if pair_rank == sb[0]: return 'top_pair'
        if len(sb) > 1 and pair_rank == sb[1]: return 'middle_pair'
        return 'bottom_pair'

    flush_draw = any(c == 4 for c in sc.values())
    oesd = any(uniq[i] - uniq[i+3] == 3 for i in range(len(uniq)-3))
    if flush_draw and oesd: return 'combo_draw'
    if flush_draw: return 'flush_draw'
    if oesd:       return 'oesd'
    gutshot = any(uniq[i] - uniq[i+3] == 4 for i in range(len(uniq)-3))
    if gutshot: return 'gutshot'
    return 'air'

def board_texture(board_cards):
    if not board_cards: return 'preflop'
    ranks = [RANK_MAP[c[0]] for c in board_cards]
    suits = [c[1] for c in board_cards]
    rc = collections.Counter(ranks)
    sc = collections.Counter(suits)
    if max(rc.values()) >= 2: return 'paired'
    if max(sc.values()) >= 3: return 'wet_flush'
    uniq = sorted(set(ranks), reverse=True)
    if 14 in uniq: uniq.append(1)
    if any(uniq[i] - uniq[i+2] <= 3 for i in range(len(uniq)-2)): return 'wet_straight'
    if max(sc.values()) == 2: return 'drawy'
    return 'dry'

# ---------------------------------------------------------------------------
# MONTE CARLO (Leveraging Revealed Cards as Blockers)
# ---------------------------------------------------------------------------
def mc_winrate(my_cards, board_cards, opp_known=None, iterations=300):
    known = set(my_cards + board_cards)
    if opp_known: known.add(opp_known)
    deck  = [c for c in FULL_DECK if c not in known]
    
    board_needed    = 5 - len(board_cards)
    # OPTIMIZATION: Mathematically perfect opponent unknown reduction
    opp_unkn_needed = 1 if opp_known else 2
    need = board_needed + opp_unkn_needed
    wins = ties = total = 0

    if EVAL7_AVAILABLE:
        my_e7     = [_eval7.Card(c) for c in my_cards]
        board_e7  = [_eval7.Card(c) for c in board_cards]
        opp_kn_e7 = [_eval7.Card(opp_known)] if opp_known else []
        deck_e7   = [_eval7.Card(c) for c in deck]
        
        for _ in range(iterations):
            sample   = random.sample(deck_e7, need)
            opp_hand = opp_kn_e7 + sample[:opp_unkn_needed]
            sim_board = board_e7 + sample[opp_unkn_needed:]
            
            ms = _eval7.evaluate(my_e7 + sim_board)
            os_ = _eval7.evaluate(opp_hand + sim_board)
            
            if EVAL7_HIGHER_IS_BETTER:
                win = ms > os_; tie = ms == os_
            else:
                win = ms < os_; tie = ms == os_
                
            if win: wins += 1
            elif tie: ties += 1
            total += 1
            
    return (wins + 0.5 * ties) / max(1, total)

# ---------------------------------------------------------------------------
# OPPONENT MODEL (Strictly v5)
# ---------------------------------------------------------------------------
class OpponentModel:
    def __init__(self):
        self.postflop_raises = 0
        self.postflop_calls  = 0
        self.postflop_folds  = 0
        self.postflop_total  = 0
        self.pf_raises = 0
        self.pf_folds  = 0
        self.pf_total  = 0

    def rec_post(self, act):
        self.postflop_total += 1
        if act == 'raise': self.postflop_raises += 1
        elif act == 'call': self.postflop_calls += 1
        elif act == 'fold': self.postflop_folds += 1

    def rec_pf(self, act):
        self.pf_total += 1
        if act == 'raise': self.pf_raises += 1
        elif act == 'fold':  self.pf_folds  += 1

    @property
    def pf_raise_rate(self):
        return self.pf_raises / max(1, self.pf_total) if self.pf_total >= 10 else 0.50

# ---------------------------------------------------------------------------
# MAIN BOT
# ---------------------------------------------------------------------------
class Player(BaseBot):
    def __init__(self):
        self.opp = OpponentModel()
        self._hand_num    = 0
        self._cache       = {}
        self._prev_opp_wager = 0
        self._total_time  = 0.0
        self._time_budget = 18.5
        self._street_raises = defaultdict(int)
        self._opp_raises    = defaultdict(int)
        self._wr_discount   = 1.0
        self._hand_start_chips = 0
        self._current_street   = "preflop"
        self._was_pf_aggressor = False

    def _time_left(self):
        return max(0.05, self._time_budget - self._total_time)

    def _iters(self, street):
        per_round = self._time_left() / max(1, 1000 - self._hand_num)
        if per_round > 0.05: base = 400
        elif per_round > 0.02: base = 250
        elif per_round > 0.01: base = 150
        else: base = 80
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
        score = {14:10.0,13:8.0,12:7.0,11:6.0}.get(hi, hi/2.0)
        if r1 == r2: score = max(5.0, score*2.0)
        if cards[0][1] == cards[1][1]: score += 2.0
        gap = hi - lo - 1
        
        # FIX: prevent pocket pairs (gap=-1) from hitting the end of the array and subtracting 5.
        if gap >= 0:
            score -= [0,1,2,4,5][min(gap,4)]
            
        if gap in [0,1] and hi < 12 and r1 != r2: score += 1.0
        return max(0.0, score)

    def _track_opp(self, current_state, street):
        if self._current_street != street:
            self._current_street = street
            self._prev_opp_wager = 0
            self._wr_discount    = 1.0
            
        delta = current_state.opp_wager - self._prev_opp_wager
        if delta > 0:
            if street == 'pre-flop':
                self.opp.rec_pf('raise' if delta > current_state.cost_to_call else 'call')
            else:
                if delta > max(current_state.pot * 0.15, 15):
                    self.opp.rec_post('raise')
                    self._opp_raises[street] += 1
                    self._wr_discount *= BAYESIAN_DISCOUNT
                else:
                    self.opp.rec_post('call')
        self._prev_opp_wager = current_state.opp_wager

    def _min_wr(self, street):
        n = min(self._opp_raises[street], len(OPP_RAISE_THRESH)-1)
        return OPP_RAISE_THRESH[n]

    def _chips_lost(self, cs):
        return max(0, self._hand_start_chips - cs.my_chips)

    def _bet_size(self, cs, wr):
        mn, mx  = cs.raise_bounds
        pot     = cs.pot
        chips   = cs.my_chips
        if wr > 0.85: frac = random.uniform(0.75, 1.00)
        elif wr > 0.70: frac = random.uniform(0.55, 0.80)
        else:           frac = random.uniform(0.40, 0.65)
        bet = int(pot * frac)
        bet = min(bet, int(chips * 0.45))
        return max(mn, min(bet, mx))

    def _cbet_size(self, cs):
        mn, mx = cs.raise_bounds
        bet = int(cs.pot * random.uniform(0.50, 0.65))
        return max(mn, min(bet, mx))

    # -----------------------------------------------------------------------
    # AUCTION LOGIC (Restored to v5's immune percentage-based strict caps)
    # -----------------------------------------------------------------------
    def _auction_bid(self, current_state):
        my_cards = current_state.my_hand
        board    = current_state.board
        pot      = current_state.pot
        chips    = current_state.my_chips
        
        if chips <= 1: return 0
        wr_base = self._raw_wr(my_cards, board, None, 'auction')
        
        if wr_base > 0.80:
            target = int(pot * random.uniform(0.30, 0.45))
        elif wr_base > 0.60:
            target = int(pot * random.uniform(0.15, 0.30))
        elif wr_base > 0.45:
            target = int(pot * random.uniform(0.05, 0.15))
        else:
            target = int(pot * random.uniform(0.0, 0.05))
            
        ABS_CAP  = min(110, int(pot * 0.45))
        FRAC_CAP = int(chips * 0.15)
        cap = max(2, min(ABS_CAP, FRAC_CAP))
        
        return max(1, min(target, cap, chips-1, 4999))

    def on_hand_start(self, game_info: GameInfo, current_state: PokerState) -> None:
        self._hand_num    = game_info.round_num
        self._cache       = {}
        self._prev_opp_wager = 0
        self._street_raises  = defaultdict(int)
        self._opp_raises     = defaultdict(int)
        self._wr_discount    = 1.0
        self._hand_start_chips = current_state.my_chips
        self._current_street   = "preflop"
        self._was_pf_aggressor = False

    def on_hand_end(self, game_info: GameInfo, current_state: PokerState) -> None:
        pass

    def get_move(self, game_info: GameInfo, current_state: PokerState):
        legal = current_state.legal_actions
        def can(a): return a in legal

        street   = current_state.street
        my_cards = current_state.my_hand
        board    = current_state.board
        pot      = current_state.pot
        cost     = current_state.cost_to_call
        chips    = current_state.my_chips

        self._track_opp(current_state, street)
        opp_known = current_state.opp_revealed_cards[0] if current_state.opp_revealed_cards else None

        # ===================================================================
        # PRE-FLOP
        # ===================================================================
        if street == 'pre-flop':
            chen = self._chen(my_cards)
            r1, r2  = RANK_MAP[my_cards[0][0]], RANK_MAP[my_cards[1][0]]
            hi, lo  = max(r1,r2), min(r1,r2)
            suited  = (my_cards[0][1] == my_cards[1][1])
            is_pair = (r1 == r2)

            raise_level = 0
            if cost > 20:   raise_level = 1
            if cost > 150:  raise_level = 2
            if cost > 600:  raise_level = 3
            if cost > 2000: raise_level = 4

            mn, mx = current_state.raise_bounds
            is_maniac = self.opp.pf_raise_rate > 0.45 
            call_tolerance = 0.85 if is_maniac else 0.55

            if is_pair and hi >= 13:
                self._was_pf_aggressor = True
                if can(ActionRaise): return ActionRaise(max(mn, min(int(pot*3+cost*2), mx)))
                if can(ActionCall): return ActionCall()

            elif (is_pair and hi >= 10) or (hi==14 and lo>=11) or (hi==14 and lo>=10 and suited):
                self._was_pf_aggressor = True
                if raise_level <= 2 and can(ActionRaise): return ActionRaise(max(mn, min(int(pot*2.5), mx)))
                if can(ActionCall): return ActionCall()

            elif chen >= 7.0:
                if raise_level == 0 and can(ActionRaise):
                    self._was_pf_aggressor = True
                    return ActionRaise(max(mn, min(int(pot*2.5), mx)))
                elif raise_level == 1 and can(ActionCall) and cost <= int(pot * call_tolerance): return ActionCall()
                if can(ActionFold): return ActionFold()

            elif chen >= 5.0:
                if raise_level == 0 and can(ActionRaise):
                    self._was_pf_aggressor = True
                    return ActionRaise(max(mn, min(int(pot*2.2), mx)))
                elif raise_level == 1 and can(ActionCall) and cost <= int(pot * call_tolerance): return ActionCall()
                if can(ActionCheck): return ActionCheck()
                return ActionFold()

            elif chen >= 3.5:
                if raise_level == 0 and can(ActionCall) and cost <= 10: 
                    return ActionCall()
                elif raise_level == 1 and is_maniac and can(ActionCall) and cost <= int(pot * 0.70):
                    return ActionCall()
                if can(ActionCheck): return ActionCheck()
                return ActionFold()

            else:
                if can(ActionCheck): return ActionCheck()
                if can(ActionCall) and cost <= 10: return ActionCall()
                return ActionFold()

        # ===================================================================
        # AUCTION
        # ===================================================================
        if street == 'auction':
            return ActionBid(self._auction_bid(current_state))

        # ===================================================================
        # POST-FLOP
        # ===================================================================
        if street in ['flop', 'turn', 'river']:
            wr      = self._winrate(my_cards, board, opp_known, street)
            hclass  = classify_hand(my_cards, board)
            texture = board_texture(board)
            ev_call = (wr * pot) - ((1.0 - wr) * cost)

            my_r    = self._street_raises[street]
            opp_r   = self._opp_raises[street]
            total_r = my_r + opp_r
            mn, mx = current_state.raise_bounds

            if texture == 'paired':
                if hclass == 'two_pair':                              hclass = 'board_two_pair'
                elif hclass in ('top_pair','overpair','underpair'):   hclass = 'middle_pair'
            if texture in ('wet_straight', 'wet_flush'):
                if hclass in ('two_pair','overpair'):  hclass = 'top_pair'
                elif hclass == 'top_pair':             hclass = 'middle_pair'
            if hclass == 'board_trips': hclass = 'middle_pair'

            MONSTER = {'straight_flush','quads','full_house','flush','straight','set'}
            STRONG  = {'trips','two_pair','overpair'}
            DECENT  = {'top_pair'}
            DRAW    = {'combo_draw','flush_draw','oesd'}

            min_wr = self._min_wr(street)
            if wr < min_wr:
                if can(ActionFold):  return ActionFold()
                if can(ActionCheck): return ActionCheck()

            raise_allowed = (can(ActionRaise) and my_r < 2 and total_r < 4)

            # --- VALUE BET THE RIVER WITH THE NUTS ---
            if street == 'river' and wr >= 0.85:
                if can(ActionRaise): return ActionRaise(max(mn, min(int(pot*0.7), mx)))

            chips_lost = self._chips_lost(current_state)
            if chips_lost > 1500:
                if wr < 0.60 and cost > 0:
                    if can(ActionFold): return ActionFold()
                raise_allowed = raise_allowed and wr >= 0.70

            is_allin = (cost > chips * 0.75 or cost > 2000)
            if is_allin:
                if hclass in MONSTER or (hclass in STRONG and wr > 0.80):
                    if can(ActionCall): return ActionCall()
                if can(ActionFold): return ActionFold()
                if can(ActionCheck): return ActionCheck()

            if wr > 0.85:
                max_call_fraction = float('inf') 
            elif wr > 0.70:
                max_call_fraction = 3.0   
            elif wr > 0.58:
                max_call_fraction = 1.5   
            elif wr > 0.45:
                max_call_fraction = 0.80 
            else:
                max_call_fraction = 0.40

            if street == 'turn' and wr > 0.90:
                if can(ActionCheck): return ActionCheck()
                if can(ActionCall): return ActionCall()

            if street == 'flop' and self._was_pf_aggressor and opp_r == 0 and my_r == 0:
                if wr >= 0.45 or random.random() < 0.20:
                    if can(ActionRaise):
                        self._street_raises[street] += 1
                        return ActionRaise(self._cbet_size(current_state))

            # --- DECISION TREE ---
            if hclass in MONSTER:
                if raise_allowed:
                    self._street_raises[street] += 1
                    return ActionRaise(self._bet_size(current_state, wr))
                if can(ActionCall): return ActionCall()
                if can(ActionCheck): return ActionCheck()

            elif hclass in STRONG:
                if raise_allowed and opp_r == 0:
                    self._street_raises[street] += 1
                    return ActionRaise(self._bet_size(current_state, wr))
                if can(ActionCall) and ev_call > 0 and cost <= (pot * max_call_fraction):
                    return ActionCall()
                if can(ActionCheck): return ActionCheck()
                return ActionFold()

            elif hclass in DECENT:
                if opp_r >= 2:
                    if can(ActionFold): return ActionFold()
                    if can(ActionCheck): return ActionCheck()
                if raise_allowed and my_r == 0 and opp_r == 0:
                    self._street_raises[street] += 1
                    return ActionRaise(self._bet_size(current_state, wr))
                if can(ActionCall) and ev_call > 0 and cost <= (pot * max_call_fraction):
                    return ActionCall()
                if can(ActionCheck): return ActionCheck()
                return ActionFold()

            elif hclass in DRAW:
                if raise_allowed and street == 'turn' and opp_r == 0 and wr > 0.50:
                    self._street_raises[street] += 1
                    return ActionRaise(self._bet_size(current_state, wr))
                draw_call_fraction = min(max_call_fraction, 1.0)
                if can(ActionCall) and ev_call > 0 and cost <= (pot * draw_call_fraction):
                    return ActionCall()
                if can(ActionCheck): return ActionCheck()
                return ActionFold()

            else: 
                # Reverted back to strict v5 logic. Purely EV-based catching, no random floats.
                if can(ActionCheck): return ActionCheck()
                if can(ActionCall) and ev_call > pot * 0.05 and cost < 40:
                    return ActionCall()
                return ActionFold()

        if can(ActionCheck): return ActionCheck()
        if can(ActionCall) and cost <= 20: return ActionCall()
        return ActionFold()

if __name__ == '__main__':
    run_bot(Player(), parse_args())
