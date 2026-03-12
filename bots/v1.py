'''
Upgraded Heuristic Pokerbot, written in Python.
'''
from pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from pkbot.states import GameInfo, PokerState
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot

import random

class Player(BaseBot):
    '''
    A pokerbot built to crush passive/random bots using fast heuristics.
    '''

    def __init__(self) -> None:
        self.rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, 
                            '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        self.pair = []

    def _get_ranks(self, cards: list[str]) -> list[str]:
        return [card[0] for card in cards]

    def _evaluate_basic_strength(self, my_cards: list[str], board_cards: list[str]) -> float:
        my_ranks = self._get_ranks(my_cards)
        if not board_cards:
            if(my_ranks[0] == my_ranks[1]):
                return 1.0
            return 0.0

        
        board_ranks = self._get_ranks(board_cards)
        
        strength = 0.0
        self.pair = []
        board_rank_values = [self.rank_values[r] for r in board_ranks]
        my_rank_values = [self.rank_values[r] for r in my_ranks]
        highest_board_card = max(board_rank_values) if board_rank_values else 0
        

        if my_ranks[0] == my_ranks[1]:
            self.pair.append(my_ranks[0])
            strength = 2.0
            if self.rank_values[my_ranks[0]] > highest_board_card:
                strength = 2.5
                
        for r in my_ranks:
            if r in board_ranks:
                if(r in self.pair):
                    strength += 3.0
                else:
                    strength += 2.0
                    self.pair.append(my_ranks[0])
                if self.rank_values[r] == highest_board_card:
                    strength += 0.5
        if(len(self.pair) > 1):
            strength += 2.0
        if strength == 0.0:
            if max(my_rank_values) >= 13: 
                strength = 0.5 
                
        return strength

    def on_hand_start(self, game_info: GameInfo, current_state: PokerState) -> None:
        self.pair = []

    def on_hand_end(self, game_info: GameInfo, current_state: PokerState) -> None:
        pass

    def get_move(self, game_info: GameInfo, current_state: PokerState) -> ActionFold | ActionCall | ActionCheck | ActionRaise | ActionBid:
        # Cache the legal actions
        legal_actions = current_state.legal_actions

        # Helper function to keep conditionals clean
        def can_act(action_type):
            return action_type in legal_actions

        # ====================================================================
        # PRE-FLOP LOGIC
        # ====================================================================
        if current_state.street == 'pre-flop':
            r1 = self.rank_values[current_state.my_hand[0][0]]
            r2 = self.rank_values[current_state.my_hand[1][0]]
            
            score = r1 + r2
            if r1 == r2: score += 10 
            if current_state.my_hand[0][1] == current_state.my_hand[1][1]: score += 4 
            
            if score >= 25: 
                if can_act(ActionRaise):
                    min_raise, max_raise = current_state.raise_bounds
                    raise_amount = max(min_raise, min(60, max_raise))
                    return ActionRaise(raise_amount)
                elif can_act(ActionCall):
                    return ActionCall()
                
            elif score >= 18: 
                if can_act(ActionCall) and current_state.cost_to_call < (current_state.pot * 0.5): 
                    return ActionCall()
            
            # If the hand is weak, or we wanted to act but couldn't
            if can_act(ActionCheck): 
                return ActionCheck()
            elif can_act(ActionCall) and current_state.cost_to_call < 40:
                return ActionCall()
            return ActionFold()

        # ====================================================================
        # AUCTION LOGIC 
        # ====================================================================
        if current_state.street == 'auction':
            strength = self._evaluate_basic_strength(current_state.my_hand, current_state.board)
            
            # BotB is bidding aggressively (up to 1400+). We will meet them with hardcoded big bids.
            if strength >= 2.0:
                return ActionBid(int(1000*random.uniform(0.7, 1)))
            elif strength >= 0.5:
                return ActionBid(int(300*random.uniform(0.5, 1)))
            else:
                return ActionBid(1+int(random.uniform(0,1)*9))

        # ====================================================================
        # POST-FLOP LOGIC
        # ====================================================================
        if current_state.street in ['flop', 'turn', 'river']:
            strength = self._evaluate_basic_strength(current_state.my_hand, current_state.board)
            
            if current_state.opp_revealed_cards:
                opp_ranks = self._get_ranks(current_state.opp_revealed_cards)
                board_ranks = self._get_ranks(current_state.board)
                
                for opp_r in opp_ranks:
                    if opp_r in board_ranks:
                        if(self.pair and opp_r >= max(self.pair)):
                            strength -= 2.0 
                        else:
                            strength -= 1.0
                    elif self.rank_values[opp_r] > max([self.rank_values[r] for r in self._get_ranks(current_state.my_hand)]):
                        strength -= 0.5 
            print(strength, game_info.round_num)
            if strength >= 2.5:
                if can_act(ActionRaise):
                    min_raise, max_raise = current_state.raise_bounds
                    raise_to = max(min_raise, int(max_raise * random.uniform(0.5, 0.75)))
                    return ActionRaise(raise_to)
                elif can_act(ActionCall):
                    return ActionCall()
            if strength >= 1.5:
                if can_act(ActionRaise):
                    min_raise, max_raise = current_state.raise_bounds
                    raise_to = max(min_raise, min(int(current_state.pot * 0.5), max_raise))
                    return ActionRaise(raise_to)
                elif can_act(ActionCall):
                    return ActionCall()
                    
            elif strength >= 0.5:
                if current_state.cost_to_call > (current_state.pot * 0.5):
                    if can_act(ActionCheck): 
                        return ActionCheck()
                    return ActionFold()
                
                if can_act(ActionCheck): return ActionCheck()
                if can_act(ActionCall): return ActionCall()
                
        # ====================================================================
        # GLOBAL SAFETY FALLBACK
        # ====================================================================
        # If logic EVER falls through the above blocks, do the safest legal move.
        if can_act(ActionCheck):
            return ActionCheck()
        elif can_act(ActionCall) and current_state.cost_to_call < 50:
            return ActionCall()
        
        return ActionFold()

if __name__ == '__main__':
    run_bot(Player(), parse_args())
