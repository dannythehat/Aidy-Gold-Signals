from pathlib import Path

bootstrap = Path("src/aidy/twelve_data_bootstrap.py")
text = bootstrap.read_text(encoding="utf-8")
old = "MAX_BOOTSTRAP_WINDOW_MINUTES = 120"
assert old in text
bootstrap.write_text(text.replace(old, "MAX_BOOTSTRAP_WINDOW_MINUTES = 30", 1), encoding="utf-8")

entry = Path("src/entry.py")
text = entry.read_text(encoding="utf-8")
start = '        if request.method == "POST" and url.path == "/day53/twelve-data-bootstrap":\n'
end = '        if request.method == "POST" and url.path == "/day53/live-gold-smoke":\n'
assert text.count(start) == 1 and text.count(end) == 1
before, rest = text.split(start, 1)
_, after = rest.split(end, 1)
block = '''        if request.method == "POST" and url.path == "/day53/twelve-data-bootstrap":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            if not _admin_authorized(request, self.env):
                return Response("Forbidden", status=403)
            if not _twelve_data_bootstrap_enabled(self.env):
                return Response.json(
                    {"ok": False, "error": "twelve_data_bootstrap_disabled"}, status=409
                )
            settings = AidySettings.from_worker_env(self.env)
            if settings.market_data_source != "twelve_data":
                return Response.json(
                    {"ok": False, "error": "twelve_data_not_configured"}, status=409
                )
            _, repository = _repository(self.env)
            market_gateway, market_store = _market_runtime_dependencies(self.env, settings)
            bootstrap_id = None
            try:
                assert isinstance(market_gateway, TwelveDataOhlcGateway)
                assert isinstance(market_store, D1TwelveDataMarketStore)
                as_of = datetime.now(UTC)
                latest_m1_open, _ = latest_completed_bucket(as_of, "1m")
                windows = plan_bootstrap_windows(as_of, latest_m1_open_utc=latest_m1_open)
                if not windows:
                    return Response.json({"ok": False, "error": "bootstrap_plan_empty"}, status=503)
                all_required = frozenset().union(*(window.required_opens for window in windows))
                admitted_rows = await market_store.latest_m1_bars(
                    start_utc=windows[0].start_utc,
                    end_utc=windows[-1].end_utc,
                )
                admitted_opens = set()
                for row in admitted_rows:
                    raw_open = row.get("open_time_utc")
                    parsed_open = raw_open if isinstance(raw_open, datetime) else datetime.fromisoformat(str(raw_open))
                    if parsed_open.tzinfo is None:
                        raise ValueError("Admitted Twelve M1 timestamp must be timezone-aware.")
                    admitted_opens.add(parsed_open.astimezone(UTC))
                missing_required = all_required - admitted_opens
                if not missing_required:
                    return Response.json(
                        {
                            "ok": True,
                            "bootstrap_id": None,
                            "state": "complete",
                            "planned_windows": 0,
                            "required_m1_minutes": len(all_required),
                            "remaining_m1_minutes": 0,
                            "window_results": [],
                            "decision_snapshot_created": False,
                            "decision_ready": False,
                            "next_step": "wait_for_fresh_scheduled_capture",
                        }
                    )
                target = next(window for window in windows if window.required_opens & missing_required)
                bootstrap_id = await market_store.start_bootstrap(
                    started_at=as_of,
                    as_of=as_of,
                    planned_windows=1,
                    required_m1_minutes=len(target.required_opens),
                )
                service = AidyTwelveDataBootstrapService(
                    repository=repository,
                    gateway=market_gateway,
                    store=market_store,
                )
                result = await service.ingest_window(bootstrap_id=bootstrap_id, window=target)
                complete = await market_store.finalize_bootstrap(
                    bootstrap_id=bootstrap_id,
                    completed_at=datetime.now(UTC),
                )
                if not complete or result.get("state") != "succeeded":
                    return Response.json(
                        {
                            "ok": False,
                            "bootstrap_id": str(bootstrap_id),
                            "state": "failed",
                            "window_results": [result],
                            "decision_snapshot_created": False,
                            "decision_ready": False,
                        },
                        status=503,
                    )
                remaining = missing_required - target.required_opens
                state = "complete" if not remaining else "in_progress"
                return Response.json(
                    {
                        "ok": True,
                        "bootstrap_id": str(bootstrap_id),
                        "state": state,
                        "planned_windows": 1,
                        "processed_window_index": target.index,
                        "processed_window_start_utc": target.start_utc.isoformat(),
                        "processed_window_end_utc": target.end_utc.isoformat(),
                        "required_m1_minutes": len(all_required),
                        "remaining_m1_minutes": len(remaining),
                        "window_results": [result],
                        "decision_snapshot_created": False,
                        "decision_ready": False,
                        "next_step": "wait_for_fresh_scheduled_capture" if state == "complete" else "continue_bootstrap",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - protected administrative bootstrap diagnosis
                if bootstrap_id is not None and isinstance(market_store, D1TwelveDataMarketStore):
                    try:
                        await market_store.finalize_bootstrap(
                            bootstrap_id=bootstrap_id,
                            completed_at=datetime.now(UTC),
                        )
                    except Exception:
                        pass
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)[:1000]},
                    status=500,
                )

'''
entry.write_text(before + block + end + after, encoding="utf-8")

wf = Path(".github/workflows/day53-bootstrap-admission-recovery.yml")
text = wf.read_text(encoding="utf-8")
text = text.replace('      - "src/aidy/twelve_data_bootstrap.py"\n', '      - "src/aidy/twelve_data_bootstrap.py"\n      - "src/entry.py"\n')
text = text.replace(
    "uv run ruff check src/aidy/twelve_data_bootstrap.py tests/test_day53_bootstrap_admission_recovery.py",
    "uv run ruff check src/aidy/twelve_data_bootstrap.py src/entry.py tests/test_day53_bootstrap_admission_recovery.py",
)
text = text.replace(
    '          grep -F "BOOTSTRAP_MIN_REQUEST_SPACING_SECONDS = 9.0" src/aidy/twelve_data_bootstrap.py\n',
    '          grep -F "BOOTSTRAP_MIN_REQUEST_SPACING_SECONDS = 9.0" src/aidy/twelve_data_bootstrap.py\n          grep -F "MAX_BOOTSTRAP_WINDOW_MINUTES = 30" src/aidy/twelve_data_bootstrap.py\n          grep -F \'"next_step": "continue_bootstrap"\' src/entry.py\n',
)
text = text.replace("    timeout-minutes: 30\n    env:\n      CLOUDFLARE_API_TOKEN:", "    timeout-minutes: 60\n    env:\n      CLOUDFLARE_API_TOKEN:", 1)

s = "      - name: Install Twelve secret and run bounded bootstrap\n"
e = "      - name: Remove ephemeral admin secret and restore capture-only Worker\n"
assert text.count(s) == 1 and text.count(e) == 1
pre, rest = text.split(s, 1)
_, post = rest.split(e, 1)
bootstrap_step = '''      - name: Install Twelve secret and run bounded bootstrap
        id: bootstrap
        shell: bash
        run: |
          set -euo pipefail
          printf '%s' "$AIDY_TWELVE_DATA_API_KEY" | npx --yes wrangler@4 secret put AIDY_TWELVE_DATA_API_KEY --config wrangler.day53.bootstrap.jsonc >/tmp/twelve-secret.txt
          ! grep -Fq "$AIDY_TWELVE_DATA_API_KEY" /tmp/twelve-secret.txt
          ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
          echo "::add-mask::$ADMIN_TOKEN"
          printf '%s' "$ADMIN_TOKEN" | npx --yes wrangler@4 secret put AIDY_DAY53_ADMIN_TOKEN --config wrangler.day53.bootstrap.jsonc >/tmp/admin-secret.txt
          ! grep -Fq "$ADMIN_TOKEN" /tmp/admin-secret.txt
          cp wrangler.day53.bootstrap.jsonc wrangler.jsonc
          deployed=0
          for attempt in 1 2 3 4 5; do
            if uv run pywrangler deploy 2>&1 | tee "/tmp/bootstrap-worker-deploy-${attempt}.txt"; then deployed=1; break; fi
            sleep $((attempt*5))
          done
          test "$deployed" -eq 1
          complete=0
          for chunk in $(seq 1 80); do
            result="/tmp/bootstrap-chunk-${chunk}.json"
            status="$(curl --silent --show-error --max-time 120 -o "$result" -w '%{http_code}' -X POST -H "X-AIDY-Admin-Token: ${ADMIN_TOKEN}" "$AIDY_TEST_WORKER_URL/day53/twelve-data-bootstrap")"
            test "$status" = "200" || { echo "bootstrap_http_status=$status"; cat "$result" || true; exit 1; }
            next="$(python - "$result" <<'PY'
import json, sys
payload=json.load(open(sys.argv[1], encoding='utf-8'))
assert payload.get('ok') is True, payload
assert payload.get('state') in {'in_progress','complete'}, payload
assert payload.get('decision_snapshot_created') is False, payload
assert payload.get('decision_ready') is False, payload
assert int(payload.get('required_m1_minutes') or 0)>=1380, payload
if payload['state']=='complete':
    assert payload.get('next_step')=='wait_for_fresh_scheduled_capture', payload
    assert int(payload.get('remaining_m1_minutes') or 0)==0, payload
    print('complete')
else:
    assert payload.get('next_step')=='continue_bootstrap', payload
    assert int(payload.get('remaining_m1_minutes') or 0)>0, payload
    rows=payload.get('window_results') or []
    assert len(rows)==1 and rows[0].get('state')=='succeeded', payload
    print('continue')
PY
            )"
            cat "$result"
            cp "$result" /tmp/bootstrap-result.json
            if test "$next" = "complete"; then complete=1; break; fi
            sleep 9
          done
          test "$complete" -eq 1
          echo 'bootstrap_complete=true'

'''
text = pre + bootstrap_step + e + post

s = "      - name: Remove ephemeral admin secret and restore capture-only Worker\n"
e = "      - name: Require fresh complete scheduled Twelve snapshot\n"
assert text.count(s) == 1 and text.count(e) == 1
pre, rest = text.split(s, 1)
_, post = rest.split(e, 1)
cleanup = '''      - name: Remove ephemeral admin secret and restore capture-only Worker
        if: always()
        shell: bash
        run: |
          set -uo pipefail
          admin_deleted=0
          for attempt in 1 2 3 4 5; do
            status="$(curl -sS -o /tmp/admin-delete.json -w '%{http_code}' -X DELETE -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H 'Content-Type: application/json' "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/aidy-signals-test/secrets/AIDY_DAY53_ADMIN_TOKEN" || true)"
            if test "$status" = "200" || test "$status" = "404"; then admin_deleted=1; break; fi
            sleep $((attempt*5))
          done
          cp wrangler.day53.restored.jsonc wrangler.jsonc
          worker_restored=0
          for attempt in 1 2 3 4 5; do
            if uv run pywrangler deploy 2>&1 | tee "/tmp/restored-worker-deploy-${attempt}.txt"; then worker_restored=1; break; fi
            sleep $((attempt*5))
          done
          scheduler_restored=0
          for attempt in 1 2 3 4 5; do
            if npx --yes wrangler@4 deploy --config wrangler.day53.scheduler.jsonc 2>&1 | tee "/tmp/restored-scheduler-deploy-${attempt}.txt"; then scheduler_restored=1; break; fi
            sleep $((attempt*5))
          done
          runtime_safe=0
          for attempt in $(seq 1 20); do
            curl -fsS -H 'Cache-Control: no-cache' "$AIDY_TEST_WORKER_URL/health?restore=${GITHUB_SHA}-${attempt}" > /tmp/restored-health.json || true
            if python -c "import json; h=json.load(open('/tmp/restored-health.json')); assert h.get('capture_enabled') is True; assert h.get('formal_forward_enabled') is False; assert h.get('market_data_source')=='twelve_data'"; then runtime_safe=1; break; fi
            sleep 3
          done
          secret_absent=0
          for attempt in 1 2 3 4 5; do
            if curl -fsS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/aidy-signals-test/secrets" > /tmp/worker-secrets-after.json; then
              if python -c "import json; p=json.load(open('/tmp/worker-secrets-after.json')); names={str(x.get('name')) for x in (p.get('result') or [])}; assert 'AIDY_DAY53_ADMIN_TOKEN' not in names"; then secret_absent=1; break; fi
            fi
            sleep $((attempt*5))
          done
          test "$admin_deleted" -eq 1
          test "$worker_restored" -eq 1
          test "$scheduler_restored" -eq 1
          test "$runtime_safe" -eq 1
          test "$secret_absent" -eq 1
          echo 'ephemeral_admin_secret_absent=true'
          echo 'capture_only_runtime_restored=true'

'''
text = pre + cleanup + e + post
text = text.replace("            /tmp/bootstrap-worker-deploy.txt\n", "            /tmp/bootstrap-worker-deploy-*.txt\n            /tmp/bootstrap-chunk-*.json\n")
text = text.replace("            /tmp/restored-worker-deploy.txt\n            /tmp/restored-scheduler-deploy.txt\n", "            /tmp/restored-worker-deploy-*.txt\n            /tmp/restored-scheduler-deploy-*.txt\n            /tmp/restored-health.json\n")
wf.write_text(text, encoding="utf-8")

tests = Path("tests/test_day53_bootstrap_admission_recovery.py")
text = tests.read_text(encoding="utf-8")
marker = "def test_resumable_bootstrap_runtime_is_bounded_and_retry_safe()"
if marker not in text:
    text += '''\n\n
def test_resumable_bootstrap_runtime_is_bounded_and_retry_safe() -> None:
    bootstrap = (ROOT / "src" / "aidy" / "twelve_data_bootstrap.py").read_text(encoding="utf-8")
    entry = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "day53-bootstrap-admission-recovery.yml").read_text(encoding="utf-8")
    assert "MAX_BOOTSTRAP_WINDOW_MINUTES = 30" in bootstrap
    assert '\"next_step\": \"continue_bootstrap\"' in entry
    assert '\"remaining_m1_minutes\"' in entry
    assert "for chunk in $(seq 1 80)" in workflow
    assert "sleep 9" in workflow
    assert "bootstrap_http_status=$status" in workflow
    assert "worker_restored=0" in workflow
    assert "scheduler_restored=0" in workflow
    assert "runtime_safe=0" in workflow
    assert "ephemeral_admin_secret_absent=true" in workflow
'''
tests.write_text(text, encoding="utf-8")
