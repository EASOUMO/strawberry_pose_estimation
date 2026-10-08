#!/bin/bash

SESSION="strawberry_perception"

tmux has-session -t "$SESSION" 2>/dev/null || {
    echo "No session '$SESSION' found."
    exit 0
}

WINDOWS=$(tmux list-windows -t "$SESSION" -F "#{window_name}")

for w in $WINDOWS; do
    echo "Sending Ctrl-C to $SESSION:$w"
    tmux send-keys -t "$SESSION:$w" C-c
done

sleep 2

echo "Killing session $SESSION"
tmux kill-session -t "$SESSION"
