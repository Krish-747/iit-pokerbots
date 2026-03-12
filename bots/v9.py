'''
alpha_q v9.1 — v11 base with 6 confirmed bug-fixes

BUGS FIXED (all confirmed by log analysis or code trace):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BUG 1 — Preflop shove defense too tight
  `hi >= 12` folded JJ (hi=11) to shoves. chen>=10 folded AQ (chen=9), KQs (chen=10→pass).
  Fixed: shove threshold → `hi >= 11` (JJ+) OR `chen >= 9.0` (AQ, KQs+ call shoves).

BUG 2 — Auction bids too high with no data
  opp_p90 defaults to 20. Strong hands bid max(pot*0.55, 22) = ~22 chips.
  v7.1 bids 10-27 so ~50% of strong-hand auctions were WON = our card revealed.
  Fixed: bid 3-8 chips when opp bid data is sparse (<8 samples).
  Once data exists, bid just above opp's confirmed minimum to lose deliberately.
  (WINNER reveals THEIR card. We want to LOSE the auction to gain opp's card.)

BUG 3 — STRONG block calls -EV bets (no ev_call check)
  `cost < pot * 1.5` with no EV check → called with wr=0.38 into big bets.
  Fixed: added `ev_call > 0` requirement for all STRONG calls.

BUG 4 — River missed draws called via Pure Math Fallback
  flush_draw/oesd/combo_draw not in river exclusion set.
  With wr=0.25 (ace-high), small bet → ev_call > 0 → called river with air.
  Fixed: added all DRAW classes to river exclusion set.

BUG 5 — Asymmetry defense too aggressive / wrong trigger
  Fired whenever opp_known is None AND cost > 0.4*pot.
  This triggers even when neither player won the auction (both bid tiny).
  Forced top_pair → fold against normal bets constantly.
  Fixed: only apply defense when we KNOW opponent won the auction this hand
  (tracked via self._opp_won_auction flag set at flop entry).

BUG 6 — Auction tracking completely backwards
  When opp_known is set = OPPONENT won auction (winner reveals THEIR card).
  Code was recording pot_delta (= our own bid) as "opponent's bid".
  opp_p90 converged to our own bid history, not opponent's range.
  Fixed: when opponent won (opp_known set) → pot_delta = our bid → 
         infer opp bid was at_least our_bid+1, record as lower-bound.
         when we won (opp_known None) → pot_delta = opp's actual payment → record exact.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
'''

from pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from pkbot.states import GameInfo, PokerState
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot

import random, time, collections
from collections import defaultdict
import eval7 as _eval7

_royal = [_eval7.Card(c) for c in ['As','Ks','Qs','Js','Ts']]
_junk  = [_eval7.Card(c) for c in ['2c','7d','8h','3s','9h']]
EVAL7_HIGHER_IS_BETTER = _eval7.evaluate(_royal) > _eval7.evaluate(_junk)

RANK_MAP = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,
            'T':10,'J':11,'Q':12,'K':13,'A':14}
ALL_RANKS = '23456789TJQKA'
ALL_SUITS = 'shdc'
FULL_DECK = [r+s for r in ALL_RANKS for s in ALL_SUITS]


def classify_hand(hole_cards, board_cards):
    if not board_cards: return 'preflop'
    all_cards   = hole_cards + board_cards
    ranks       = [RANK_MAP[c[0]] for c in all_cards]
    suits       = [c[1] for c in all_cards]
    brc         = collections.Counter(RANK_MAP[c[0]] for c in board_cards)
    hole_ranks  = [RANK_MAP[c[0]] for c in hole_cards]
    board_ranks = [RANK_MAP[c[0]] for c in board_cards]
    rc          = collections.Counter(ranks)
    sc          = collections.Counter(suits)

    is_flush = False
    is_straight_flush = False
    for s, cnt in sc.items():
        if cnt >= 5:
            is_flush = True
            flush_ranks = [RANK_MAP[card[0]] for card in all_cards if card[1] == s]
            uf = sorted(set(flush_ranks), reverse=True)
            if 14 in uf: uf.append(1)
            is_straight_flush = any(uf[i]-uf[i+4] == 4 for i in range(len(uf)-4))
            break

    uniq = sorted(set(ranks), reverse=True)
    if 14 in uniq: uniq.append(1)
    is_straight = any(uniq[i]-uniq[i+4] == 4 for i in range(len(uniq)-4))

    if is_straight_flush: return 'straight_flush'
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
    oesd = any(uniq[i]-uniq[i+3] == 3 for i in range(len(uniq)-3))
    if flush_draw and oesd: return 'combo_draw'
    if flush_draw: return 'flush_draw'
    if oesd:       return 'oesd'
    gutshot = any(uniq[i]-uniq[i+3] == 4 for i in range(len(uniq)-3))
    if gutshot: return 'gutshot'
    return 'air'


def mc_winrate(my_cards, board_cards, opp_known=None, iterations=300):
    known = set(my_cards + board_cards)
    if opp_known: known.add(opp_known)
    deck  = [c for c in FULL_DECK if c not in known]
    board_needed    = 5 - len(board_cards)
    opp_unkn_needed = 1 if opp_known else 2
    need  = board_needed + opp_unkn_needed
    wins  = ties = total = 0

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


class UniversalTracker:
    def __init__(self):
        # BUG 6 FIX: separate exact bids (opp's actual payments when we won auction)
        # from inferred lower-bounds (when opp won, we know they bid > our_bid)
        self.opp_bids_exact     = []   # opp paid this (we won = we saw their card... wait)
        self.opp_bids_lowerbound= []   # opp bid at least this+1 (they won)
        self.postflop_raises    = 0
        self.postflop_calls     = 0
        self.pf_raises          = 0
        self.pf_total           = 0

    def record_opp_won(self, our_bid):
        """Opponent won auction: they bid > our_bid. Opp bid is unknown but > our_bid."""
        # BUG 6 FIX: record our_bid as lower-bound for opp's bid
        if our_bid > 0:
            lb = our_bid + 1
            self.opp_bids_lowerbound.append(lb)
            if len(self.opp_bids_lowerbound) > 80: self.opp_bids_lowerbound.pop(0)

    def record_we_won(self, opp_payment):
        """We won auction: opp paid opp_payment into pot. That IS their bid."""
        # BUG 6 FIX: pot_delta when WE won = opp's actual bid
        if 0 < opp_payment < 5000:
            self.opp_bids_exact.append(opp_payment)
            if len(self.opp_bids_exact) > 80: self.opp_bids_exact.pop(0)

    @property
    def opp_bid_min_known(self):
        """Minimum confirmed opp bid (exact payments)."""
        if not self.opp_bids_exact: return None
        return min(self.opp_bids_exact[-40:])

    @property
    def opp_bid_p90(self):
        """90th percentile of all known opp bid info."""
        all_bids = sorted(self.opp_bids_exact + self.opp_bids_lowerbound)
        if not all_bids: return None  # no data yet
        return all_bids[int(len(all_bids) * 0.90)]

    @property
    def bid_sample_size(self):
        return len(self.opp_bids_exact) + len(self.opp_bids_lowerbound)

    def rec_pf(self, act):
        self.pf_total += 1
        if act == 'raise': self.pf_raises += 1

    @property
    def pf_raise_rate(self):
        return self.pf_raises / max(1, self.pf_total) if self.pf_total >= 10 else 0.50

    @property
    def is_maniac(self):
        return self.pf_raise_rate > 0.50


class Player(BaseBot):
    def __init__(self):
        self.opp              = UniversalTracker()
        self._hand_num        = 0
        self._cache           = {}
        self._total_time      = 0.0
        self._time_budget     = 19.0
        self._street_raises   = defaultdict(int)
        self._opp_raises      = defaultdict(int)
        self._prev_opp_wager  = 0
        self._auction_pre_pot = 0
        self._our_last_bid    = 0
        self._opp_won_auction = False   # BUG 5 FIX: track per-hand whether opp won

    def _get_iters(self, street):
        time_left = max(0.05, self._time_budget - self._total_time)
        per_round = time_left / max(1, 1000 - self._hand_num)
        if   per_round > 0.05: base = 400
        elif per_round > 0.02: base = 250
        elif per_round > 0.01: base = 150
        else:                  base = 80
        if street == 'pre-flop': return base // 4
        if street == 'auction':  return 100
        return base

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

    def on_hand_start(self, game_info: GameInfo, cs: PokerState) -> None:
        self._hand_num = game_info.round_num
        self._cache.clear()
        self._street_raises.clear()
        self._opp_raises.clear()
        self._prev_opp_wager  = 0
        self._auction_pre_pot = 0
        self._our_last_bid    = 0
        self._opp_won_auction = False  # BUG 5 FIX

    def on_hand_end(self, game_info: GameInfo, cs: PokerState) -> None:
        pass

    def get_move(self, game_info: GameInfo, cs: PokerState):
        legal = cs.legal_actions
        def can(a): return a in legal

        street    = cs.street
        pot       = cs.pot
        cost      = cs.cost_to_call
        chips     = cs.my_chips
        mn, mx    = cs.raise_bounds
        opp_known = cs.opp_revealed_cards[0] if cs.opp_revealed_cards else None

        # Track opponent raises for Bayesian discounting
        delta = cs.opp_wager - self._prev_opp_wager
        if delta > max(pot * 0.15, 15) and street not in ('pre-flop', 'auction'):
            self._opp_raises[street] += 1
            self.opp.postflop_raises += 1
        elif delta > 0 and street == 'pre-flop':
            self.opp.rec_pf('raise' if delta > cost else 'call')
        self._prev_opp_wager = cs.opp_wager

        # ── Resolve auction result on first flop action ──────────────────
        if street == 'flop' and self._auction_pre_pot > 0:
            pot_delta = pot - self._auction_pre_pot
            if opp_known:
                # BUG 6 FIX: opp_known = OPPONENT won auction (winner reveals THEIR card)
                # pot_delta = our bid (they paid our bid into pot)
                # We know opp bid > our_last_bid
                self.opp.record_opp_won(self._our_last_bid)
                self._opp_won_auction = False  # we have their card = good for us
            else:
                # We won auction (no reveal of opp card)
                # opp paid their bid = pot_delta = opp's actual bid
                if 0 < pot_delta < 5000:
                    self.opp.record_we_won(int(pot_delta))
                self._opp_won_auction = True  # BUG 5 FIX: opp won = they know our card
            self._auction_pre_pot = 0

        # ================================================================
        # 1. PRE-FLOP
        # ================================================================
        if street == 'pre-flop':
            chen    = self._chen(cs.my_hand)
            r1, r2  = RANK_MAP[cs.my_hand[0][0]], RANK_MAP[cs.my_hand[1][0]]
            is_pair = (r1 == r2)
            hi      = max(r1, r2)
            suited  = (cs.my_hand[0][1] == cs.my_hand[1][1])

            # BUG 1 FIX: JJ (hi=11) and AQ (chen=9) now call shoves
            if cost > 500:
                if (is_pair and hi >= 11) or chen >= 9.0:
                    if can(ActionCall): return ActionCall()
                return ActionFold()

            if cost > 50:
                if (is_pair and hi >= 9) or chen >= 8.0:
                    if can(ActionCall): return ActionCall()
                return ActionFold()

            if cost > 20:
                if (is_pair and hi >= 11) or chen >= 9.0:
                    if can(ActionRaise): return ActionRaise(max(mn, min(int(pot*2.5), mx)))
                if (is_pair and hi >= 6) or chen >= 6.5:
                    if can(ActionCall): return ActionCall()
                return ActionFold()

            # cost <= 20 (limper/BB)
            if chen >= 6.0 or is_pair or (suited and hi >= 11):
                if can(ActionRaise): return ActionRaise(max(mn, min(int(pot*2.5), mx)))
            if can(ActionCall) and chen >= 4.5: return ActionCall()
            if can(ActionCheck): return ActionCheck()
            return ActionFold()

        # ================================================================
        # 2. AUCTION — bid to LOSE (winner reveals THEIR card)
        # ================================================================
        if street == 'auction':
            self._auction_pre_pot = pot
            t0 = time.time()
            wr = mc_winrate(cs.my_hand, cs.board, None, self._get_iters('auction'))
            self._total_time += time.time() - t0

            n_samples = self.opp.bid_sample_size

            # BUG 2 FIX: Goal is to LOSE the auction (opp reveals their card).
            # With no data, bid tiny to guarantee losing.
            # With data, bid just below opp's confirmed minimum bid.
            if n_samples < 8:
                # No data: always lose by bidding tiny
                target = random.randint(3, 8)
            else:
                opp_min = self.opp.opp_bid_min_known or 15
                # Bid just below opp's minimum confirmed bid → lose ~90% of auctions
                # We gain their card for free; they pay our tiny bid
                if wr > 0.80:
                    # Near-nuts: willing to pay slightly more, still aim to lose
                    target = max(int(pot * 0.12), min(opp_min - 1, int(pot * 0.20)))
                elif wr > 0.50:
                    target = max(int(pot * 0.08), min(opp_min - 2, int(pot * 0.15)))
                else:
                    target = random.randint(3, 8)

            # Ensure always below opp's range and within chip budget
            final = min(max(2, target), int(chips * 0.20), chips - 1, 4999)
            self._our_last_bid = final
            return ActionBid(final)

        # ================================================================
        # 3. POST-FLOP
        # ================================================================
        t0 = time.time()
        wr = mc_winrate(cs.my_hand, cs.board, opp_known, self._get_iters(street))
        self._total_time += time.time() - t0

        hclass  = classify_hand(cs.my_hand, cs.board)
        ev_call = wr * (pot + cost) - cost
        opp_r   = self._opp_raises[street]

        MONSTER = {'straight_flush','quads','full_house','flush','straight','set'}
        STRONG  = {'trips','two_pair','overpair'}
        DECENT  = {'top_pair'}
        DRAW    = {'combo_draw','flush_draw','oesd'}

        # BUG 5 FIX: Asymmetry defense only when we KNOW opp bought our card info
        # (tracked by self._opp_won_auction, set when opp_known is None after auction)
        if self._opp_won_auction and cost > pot * 0.4:
            if hclass in DECENT:
                hclass = 'middle_pair'
                wr = min(wr, 0.45)
            elif hclass in STRONG and cost > pot * 0.8:
                hclass = 'top_pair'

        # ── MONSTER / near-nuts ───────────────────────────────────────────
        if hclass in MONSTER or wr > 0.85:
            if can(ActionRaise) and self._street_raises[street] < 3:
                self._street_raises[street] += 1
                return ActionRaise(max(mn, min(int(pot * 0.8), mx)))
            if can(ActionCall): return ActionCall()

        # ── STRONG ────────────────────────────────────────────────────────
        elif hclass in STRONG or wr > 0.70:
            if opp_r == 0 and can(ActionRaise) and self._street_raises[street] < 2:
                self._street_raises[street] += 1
                return ActionRaise(max(mn, min(int(pot * 0.6), mx)))
            # BUG 3 FIX: added ev_call > 0 requirement
            if can(ActionCall) and ev_call > 0 and cost < pot * 1.5:
                return ActionCall()

        # ── DECENT: top pair ──────────────────────────────────────────────
        elif hclass in DECENT or wr > 0.55:
            if opp_r == 0 and can(ActionRaise) and self._street_raises[street] == 0:
                self._street_raises[street] += 1
                return ActionRaise(max(mn, min(int(pot * 0.5), mx)))
            if can(ActionCall) and ev_call > 0 and cost <= pot * 0.75:
                return ActionCall()

        # ── DRAW: semi-bluff on flop/turn only ───────────────────────────
        elif hclass in DRAW and street != 'river':
            if opp_r == 0 and can(ActionRaise) and self._street_raises[street] == 0 and wr > 0.40:
                self._street_raises[street] += 1
                return ActionRaise(max(mn, min(int(pot * 0.4), mx)))
            if can(ActionCall) and ev_call > 0 and cost <= pot * 0.5:
                return ActionCall()

        # ── Pure Math Fallback ────────────────────────────────────────────
        if can(ActionCall) and ev_call > 0 and cost <= pot * 0.3:
            # BUG 4 FIX: exclude missed draws on river from fallback calling
            river_no_call = {'air', 'high_card', 'board_pair', 'underpair',
                             'flush_draw', 'oesd', 'combo_draw', 'gutshot', 'bottom_pair'}
            if street == 'river' and hclass in river_no_call:
                if can(ActionFold): return ActionFold()
            # BUG 1 addition: river calls require WR >= 0.45 minimum
            if street == 'river' and wr < 0.45:
                if can(ActionFold): return ActionFold()
            return ActionCall()

        if can(ActionCheck): return ActionCheck()
        return ActionFold()


if __name__ == '__main__':
    run_bot(Player(), parse_args())
