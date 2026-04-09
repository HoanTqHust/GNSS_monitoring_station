#!/bin/bash

PORTS=("/dev/ttyACM0" "/dev/ttyACM1" "/dev/ttyACM2")
FILES=("raw_data_1.ubx" "raw_data_2.ubx" "raw_data_3.ubx")

FOLDER=$(date +%Y-%m-%d)
mkdir -p "$FOLDER"

record_port() {
    local PORT=$1
    local OUTFILE=$2
    echo "✅ Recording from $PORT -> $OUTFILE"
    dd if="$PORT" of="$OUTFILE" bs=1 iflag=nonblock &
}

trap "echo '🛑 Stopping...' ; kill $(jobs -p) ; exit" SIGINT SIGTERM

for i in "${!PORTS[@]}"; do
    OUT_PATH="$FOLDER/${FILES[$i]}"
    record_port "${PORTS[$i]}" "$OUT_PATH"
done

echo "🎯 Recording... Press Ctrl + C to stop."
wait
