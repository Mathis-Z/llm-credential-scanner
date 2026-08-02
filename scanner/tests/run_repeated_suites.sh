#!/bin/bash
# Repeatedly runs the test-network and evaluation-network suites, RUNS_PER_SUITE
# times each, both against the remote LLM (default settings) and with
# USE_LOCAL_LLM=True. The four backend/suite combinations are cycled round-robin:
# each round runs every combination once, local models first, so results are spread
# evenly over time instead of all remote runs happening before all local ones. Waits
# WAIT_BETWEEN_RUNS seconds between every individual run to let Docker/browser
# state settle.
#
# Usage: scanner/tests/run_repeated_suites.sh
#
# WARNING: this launches 4 x RUNS_PER_SUITE full suite runs (default: 40 total -
# 10x test-network + 10x evaluation-network, once remote and once local). Each
# full suite run can take hours, so budget accordingly before starting this.
# It is safe to interrupt (Ctrl+C) and resume manually later; already-written
# run directories are left untouched by re-running (each run overwrites only
# its own run-NN directory if reused).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="$REPO_ROOT/scanner/.venv/bin/python"
RESULTS_DIR="$SCRIPT_DIR/repeated_suite_results"
SUMMARY_FILE="$RESULTS_DIR/SUMMARY.txt"

RUNS_PER_SUITE=10
WAIT_BETWEEN_RUNS=60

if [ ! -x "$PYTHON" ]; then
    echo "error: venv python not found at $PYTHON (expected scanner/.venv to exist)" >&2
    exit 1
fi

run_suite() {
    # $1=model_backend ("remote"/"local"), $2=suite_name, $3=run_number, $4...=extra CLI args
    local model_backend="$1"
    local suite_name="$2"
    local run_number="$3"
    shift 3
    local suite_args=("$@")

    local run_dir
    run_dir=$(printf "%s/%s/%s/run-%02d" "$RESULTS_DIR" "$model_backend" "$suite_name" "$run_number")
    mkdir -p "$run_dir"

    echo "=== [$model_backend] $suite_name run $run_number/$RUNS_PER_SUITE started at $(date -Iseconds) ===" | tee "$run_dir/output.log"

    local start_epoch
    start_epoch=$(date +%s)

    (
        cd "$REPO_ROOT" || exit 1
        if [ "$model_backend" = "local" ]; then
            export USE_LOCAL_LLM=True
        fi
        "$PYTHON" -m scanner.tests.tests "${suite_args[@]}" --keep --kill-containers
    ) >> "$run_dir/output.log" 2>&1
    local exit_code=$?

    local end_epoch
    end_epoch=$(date +%s)
    local duration=$((end_epoch - start_epoch))

    echo "=== [$model_backend] $suite_name run $run_number/$RUNS_PER_SUITE finished at $(date -Iseconds) (exit code $exit_code, duration ${duration}s) ===" | tee -a "$run_dir/output.log"
    printf "%s\t%s\t%02d\t%s\t%ss\t%s\n" "$model_backend" "$suite_name" "$run_number" "$exit_code" "$duration" "$run_dir" >> "$SUMMARY_FILE"

    return "$exit_code"
}

# The four backend/suite combinations, cycled round-robin so a given round covers
# every combination before the next round starts. Local runs come first in each
# round so local-model evaluation starts immediately rather than waiting for all
# remote runs. Fields are separated by "|": model_backend|suite_name|extra CLI args
# (may be empty).
COMBINATIONS=(
    "local|test-network|"
    "local|evaluation-network|--evaluation"
    "remote|test-network|"
    "remote|evaluation-network|--evaluation"
)

mkdir -p "$RESULTS_DIR"
echo -e "model_backend\tsuite\trun\texit_code\tduration\tdir" > "$SUMMARY_FILE"

echo "Starting repeated suite runs: $RUNS_PER_SUITE rounds of ${#COMBINATIONS[@]} runs each (test-network + evaluation-network, remote + local (USE_LOCAL_LLM=True)), round-robin."
echo "Results directory: $RESULTS_DIR"

for run_number in $(seq 1 "$RUNS_PER_SUITE"); do
    for combination in "${COMBINATIONS[@]}"; do
        IFS="|" read -r model_backend suite_name suite_args <<< "$combination"
        # shellcheck disable=SC2086 # suite_args is intentionally word-split (may be empty)
        run_suite "$model_backend" "$suite_name" "$run_number" $suite_args
        echo "Waiting ${WAIT_BETWEEN_RUNS}s before next run..."
        sleep "$WAIT_BETWEEN_RUNS"
    done
done

echo "All repeated suite runs completed at $(date -Iseconds)."
echo "Summary: $SUMMARY_FILE"
echo "Full results: $RESULTS_DIR"
