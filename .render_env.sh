# Temporary build hook for the obsolete Render AIDY CI runner.
# Capture the real interpreter before defining the python shell function.
export AIDY_REAL_PYTHON="$(command -v python)"
python() {
  local real_python="${AIDY_REAL_PYTHON}"
  if [ "${AIDY_GOLD_BUILD_RUNNER:-0}" = "1" ] && [ "$#" -eq 1 ] && [ "$1" = "-V" ]; then
    export AIDY_GOLD_BUILD_RUNNER=0
    bash scripts/render_build_gold_rollout.sh
  fi
  command "$real_python" "$@"
}
