# Temporary build hook for the obsolete Render AIDY CI runner.
# It only intercepts the runner's exact build command: python -V.
python() {
  local real_python="/opt/render/project/python/Python-3.13.15/bin/python"
  if [ "${AIDY_GOLD_BUILD_RUNNER:-0}" = "1" ] && [ "$#" -eq 1 ] && [ "$1" = "-V" ]; then
    export AIDY_GOLD_BUILD_RUNNER=0
    bash scripts/render_build_gold_rollout.sh
  fi
  command "$real_python" "$@"
}
