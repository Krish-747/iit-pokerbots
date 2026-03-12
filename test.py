import os
import re
import glob

def analyze_glogs(directory_path="./logs"):
    # Find all glog files in the specified directory
    log_files = glob.glob(os.path.join(directory_path, "*.glog"))
    
    if not log_files:
        print("No .glog files found in the current directory.")
        return

    results = []
    total_a_net = 0
    total_b_net = 0
    
    for file_path in log_files:
        with open(file_path, 'r') as f:
            content = f.read()
            
            # Extract all chip awards for this match
            awards = re.findall(r'(Bot[AB]) awarded (-?\d+)', content)
            
            # Extract the bankroll states to find the final net score
            rounds = re.findall(r'Round #\d+, (Bot[AB]) \((-?\d+)\), (Bot[AB]) \((-?\d+)\)', content)
            
            # Count how many auctions each bot won
            auction_wins = re.findall(r'(Bot[AB]) won the auction', content)
            bot_a_auctions = auction_wins.count("BotA")
            bot_b_auctions = auction_wins.count("BotB")
            
            bota_net = botb_net = 0
            
            # The last recorded round state gives us the near-final bankroll
            if rounds:
                last_round = rounds[-1]
                if last_round[0] == 'BotA':
                    bota_net = int(last_round[1])
                    botb_net = int(last_round[3])
                else:
                    bota_net = int(last_round[3])
                    botb_net = int(last_round[1])
                    
            # Calculate the largest single hand win/loss for variance tracking
            bota_awards = [int(amt) for bot, amt in awards if bot == 'BotA']
            
            max_win_a = max(bota_awards) if bota_awards else 0
            max_loss_a = min(bota_awards) if bota_awards else 0
            
            total_a_net += bota_net
            total_b_net += botb_net
            
            results.append({
                'file': os.path.basename(file_path),
                'BotA_Net': bota_net,
                'BotA_MaxWin': max_win_a,
                'BotA_MaxLoss': max_loss_a,
                'BotA_Auctions': bot_a_auctions,
                'BotB_Auctions': bot_b_auctions
            })
            
    # Print formatted results
    print(f"{'File Name':<30} | {'BotA Net':<10} | {'BotA Max Win':<15} | {'BotA Max Loss':<15} | {'Auction Wins (A vs B)'}")
    print("-" * 95)
    for r in results:
        auction_ratio = f"{r['BotA_Auctions']} - {r['BotB_Auctions']}"
        print(f"{r['file']:<30} | {r['BotA_Net']:<10} | {r['BotA_MaxWin']:<15} | {r['BotA_MaxLoss']:<15} | {auction_ratio}")
    
    print("-" * 95)
    print(f"OVERALL BotA Net: {total_a_net}")
    print(f"OVERALL BotB Net: {total_b_net}")

if __name__ == '__main__':
    analyze_glogs()
