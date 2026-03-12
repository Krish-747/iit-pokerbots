#!/bin/bash

# Check if the user provided the number of runs
if [ -z "$1" ]; then
    echo "Usage: ./run_matches.sh <number_of_runs>"
    echo "Example: ./run_matches.sh 15"
    exit 1
fi

NUM_RUNS=$1

# Optional: Clean up old .glog files before starting the new batch
# Uncomment the next line if you want a fresh slate every time you run the script
# rm -f *.glog

echo "========================================"
echo "Starting Pokerbots Engine ($NUM_RUNS Matches)"
echo "========================================"

for i in $(seq 1 $NUM_RUNS); do
    echo "Running match $i / $NUM_RUNS..."
    # Run the engine (suppress its standard output if it's too noisy, using > /dev/null)
    python engine.py 
done

echo "========================================"
echo "All matches completed. Analyzing logs..."
echo "========================================"

# Run your log analyzer script to print the summary table
python test.py
