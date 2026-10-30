"""시연 점검 스크립트.

    docker compose run --rm rehearsal                  # 파트별 계약 점검 (LLM 없이 고정 요청)
    docker compose run --rm rehearsal --agent live -n 3  # agent로 시연 시나리오 전체 3회

각 항목은 PASS / FAIL / SKIP 로 표시합니다. 아직 안 만들어진 파트는 FAIL로 나오는 게 정상입니다.
"""
import argparse
import asyncio
import json
import os
import sys
import time

import httpx
import websockets

GW = os.environ.get("GW_URL", "http://gateway:8000")
OPS = os.environ.get("OPS_URL", "http://detector:8002")
UI = os.environ.get("UI_URL", "http://ops-ui:8003")
AGENT = os.environ.get("AGENT_URL", "http://agent:8004")

IP_A, IP_B = "203.0.113.24", "198.51.100.7"
INTERNAL = {"X-Internal-Request": "true"}

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(("PASS" if ok else "FAIL", name, detail))
    return ok


def skip(name: str, why: str) -> None:
    results.append(("SKIP", name, why))


async def safe(name: str, coro):
    """한 항목이 터져도 나머지는 계속 점검."""
    try:
        return await coro
    except Exception as e:
        check(name, False, f"{e.__class__.__name__}: {e}")
        return None


async def latest_event(ops: httpx.AsyncClient, path_prefix: str, ip: str, wait: float = 3.0) -> dict | None:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for e in reversed((await ops.get("/ops/events", params={"limit": 50})).json()):
            if e["path"].startswith(path_prefix) and e["ip"] == ip:
                return e
        await asyncio.sleep(0.2)
    return None


async def set_decoys(ops: httpx.AsyncClient, enabled: bool) -> None:
    (await ops.put("/ops/decoys", json={"enabled": enabled})).raise_for_status()
    (await ops.post("/ops/demo/reset")).raise_for_status()


# ---------- 1. 헬스 ----------

async def health(c: httpx.AsyncClient) -> None:
    for name, url in [("gateway", f"{GW}/healthz"), ("detector", f"{OPS}/healthz"),
                      ("ops-ui", f"{UI}/healthz"), ("agent", f"{AGENT}/healthz")]:
        try:
            r = await c.get(url)
            check(f"헬스: {name}", r.status_code == 200, str(r.status_code))
        except httpx.HTTPError as e:
            check(f"헬스: {name}", False, e.__class__.__name__)
    r = await c.get(f"{GW}/")
    check("헬스: gateway → bank 메인", r.status_code == 200 and "ㅁㅁ은행" in r.text, str(r.status_code))


# ---------- 2. bank 계약 ----------

async def bank(gw: httpx.AsyncClient) -> None:
    r = await gw.get("/api/v1/docs")
    check("bank: /api/v1/docs 200", r.status_code == 200, str(r.status_code))
    check("bank: 문서에 /api/v1/customers 소개", "/api/v1/customers" in r.text)

    r = await gw.get("/api/v1/customers", params={"id": 1001})
    check("bank: 세션 없이 customers → 401", r.status_code == 401, str(r.status_code))

    r = await gw.get("/api/v1/customers", params={"id": 1001}, headers=INTERNAL)
    check("bank: X-Internal-Request → 200 (취약점)", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        check("bank: 시드 고객 1001 존재", "1001" in r.text, "seed_customers 실행했는지 확인")
    r = await gw.get("/api/v1/customers", params={"id": 3400}, headers=INTERNAL)
    check("bank: 시드 고객 3400 존재 (2,400명)", r.status_code == 200, str(r.status_code))

    r = await gw.get("/admin-old")
    check("bank: /admin-old 403", r.status_code == 403, str(r.status_code))


# ---------- 3. 미끼 끔 ----------

async def decoys_off(gw: httpx.AsyncClient, ops: httpx.AsyncClient) -> None:
    await set_decoys(ops, False)
    r = await gw.get("/robots.txt")
    check("미끼 끔: robots에 /admin-old만", "/admin-old" in r.text and "/admin-legacy" not in r.text)
    r = await gw.get("/api/v1/docs")
    check("미끼 끔: 문서에 숨은 안내문 없음", "/api/internal/export" not in r.text)
    r = await gw.get("/admin-legacy")
    check("미끼 끔: /admin-legacy 404", r.status_code == 404, str(r.status_code))

    r = await gw.get("/api/v1/customers", params={"id": 1001}, headers={**INTERNAL, "X-Sim-IP": IP_A})
    await asyncio.sleep(0.5)
    stats = (await ops.get("/ops/stats")).json()
    check("미끼 끔: 실제 유출 집계 증가", stats["real_leaks"] >= 1, f"real_leaks={stats['real_leaks']}")


# ---------- 4. 미끼 켬: 함정, 격리, 토큰 묶음 ----------

async def decoys_on(gw: httpx.AsyncClient, ops: httpx.AsyncClient) -> None:
    await set_decoys(ops, True)
    r = await gw.get("/robots.txt")
    check("미끼 켬: robots에 /admin-legacy 추가", "/admin-legacy" in r.text)
    r = await gw.get("/api/v1/docs")
    check("미끼 켬: 문서에 숨은 안내문", "/api/internal/export" in r.text)
    check("미끼 켬: 안내문이 HTML 주석에도", "<!--" in r.text and "/api/internal/export" in r.text.split("<!--", 1)[-1])

    a = {"X-Sim-IP": IP_A}
    r = await gw.get("/admin-legacy", headers=a)
    check("미끼 켬: /admin-legacy 200", r.status_code == 200, str(r.status_code))
    check("미끼 켬: 내보내기 링크", "/api/internal/export" in r.text)

    e = await latest_event(ops, "/admin-legacy", IP_A)
    check("이벤트: admin-legacy가 decoy로 기록", bool(e) and e["routed_to"] == "decoy" and e["decoy_id"] == "admin_legacy",
          json.dumps({k: e.get(k) for k in ("routed_to", "decoy_id", "actor_id")}) if e else "이벤트 없음")
    actor_id = e.get("actor_id") if e else None
    check("즉시 격리: 공격 주체 id 부여", bool(actor_id) and actor_id.startswith("A-"), str(actor_id))

    r = await gw.get("/api/v1/customers", params={"id": 1001}, headers={**INTERNAL, **a})
    e = await latest_event(ops, "/api/v1/customers", IP_A)
    check("격리 라우팅: 같은 IP의 customers → 미끼", bool(e) and e["routed_to"] == "decoy",
          e["routed_to"] if e else "이벤트 없음")

    r = await gw.get("/api/internal/export", params={"page": 1}, headers=a)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    records = body.get("records") or body.get("data") or body.get("customers") or []
    token = body.get("next_token")
    check("endless_export: 50건", len(records) == 50, f"{len(records)}건")
    check("endless_export: next_token 형식", bool(token) and token.startswith(f"pt_{actor_id}_1_"), str(token))
    if records:
        email = json.dumps(records[0], ensure_ascii=False)
        check("가짜 레코드: 추적 표식", f"{(actor_id or '').lower()}.trace.example" in email, email[:80])

    if not token:
        skip("토큰 묶음: 다른 IP에서 재사용", "next_token 없음")
        return
    r = await gw.get("/api/internal/export", params={"page": 2, "token": token}, headers={"X-Sim-IP": IP_B})
    await asyncio.sleep(1.0)
    detail = (await ops.get(f"/ops/actors/{actor_id}")).json()
    ips = {l["value"] for l in detail.get("links", []) if l["kind"] == "ip"}
    check("토큰 묶음: IP 2개가 같은 공격 주체", {IP_A, IP_B} <= ips, f"{actor_id} ips={sorted(ips)}")
    check("토큰 묶음: 확정", any(l["confidence"] == "확정" for l in detail.get("links", [])))

    stats = (await ops.get("/ops/stats")).json()
    check("미끼 켬: 실제 유출 0", stats["real_leaks"] == 0, f"real_leaks={stats['real_leaks']}")
    check("미끼 켬: 가짜 레코드 집계", stats["fake_records"] >= 100, f"fake_records={stats['fake_records']}")


# ---------- 5. agent 시나리오 ----------

async def wait_end(timeout: float) -> int:
    """WS로 X-Agent-Note: __END__ 이벤트가 올 때까지 기다리며 이벤트 수를 셈."""
    n = 0
    ws_url = OPS.replace("http", "ws", 1) + "/ops/stream"
    async with websockets.connect(ws_url) as ws:
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            msg = json.loads(await asyncio.wait_for(ws.recv(), left))
            if msg["type"] == "event":
                n += 1
                if msg["data"].get("agent_note") == "__END__":
                    return n
    raise TimeoutError(f"{timeout}s 안에 __END__ 없음 (이벤트 {n}개)")


async def agent_round(ops: httpx.AsyncClient, mode: str, enabled: bool, timeout: float) -> dict:
    await set_decoys(ops, enabled)
    waiter = asyncio.create_task(wait_end(timeout))
    await asyncio.sleep(0.3)   # WS 연결 먼저
    r = await ops.post("/ops/demo/run", json={"mode": mode})
    if r.status_code >= 400:
        waiter.cancel()
        raise RuntimeError(f"/ops/demo/run {r.status_code}: {r.text[:100]}")
    t0 = time.monotonic()
    n = await waiter
    stats = (await ops.get("/ops/stats")).json()
    actors = (await ops.get("/ops/actors")).json()
    return {"events": n, "secs": round(time.monotonic() - t0, 1), "stats": stats, "actors": actors}


async def agent_scenario(ops: httpx.AsyncClient, mode: str, repeat: int, timeout: float) -> None:
    rows = []
    for i in range(1, repeat + 1):
        off = await safe(f"시나리오 {i}: 미끼 끔 실행", agent_round(ops, mode, False, timeout))
        if off:
            check(f"시나리오 {i}: 미끼 끔 → 실제 유출 발생", off["stats"]["real_leaks"] > 0,
                  f"real_leaks={off['stats']['real_leaks']}")
            rows.append((i, "끔", off))
        on = await safe(f"시나리오 {i}: 미끼 켬 실행", agent_round(ops, mode, True, timeout))
        if on:
            s = on["stats"]
            check(f"시나리오 {i}: 미끼 켬 → 실제 유출 0", s["real_leaks"] == 0, f"real_leaks={s['real_leaks']}")
            check(f"시나리오 {i}: 미끼 켬 → 가짜 레코드 제공", s["fake_records"] > 0, f"fake_records={s['fake_records']}")
            a01 = next((a for a in on["actors"] if a["id"] == "A-01"), None)
            check(f"시나리오 {i}: A-01로 묶임", bool(a01), f"actors={[a['id'] for a in on['actors']]}")
            if a01:
                check(f"시나리오 {i}: A-01 IP 2개 이상", a01.get("ip_count", 0) >= 2, f"ip_count={a01.get('ip_count')}")
            rows.append((i, "켬", on))

    if rows:
        print("\n실행 결과 비교")
        print(f"{'회차':>4} {'미끼':>4} {'이벤트':>6} {'초':>6} {'실제유출':>8} {'가짜레코드':>10} {'함정':>4} {'묶은초':>6}")
        for i, label, r in rows:
            s = r["stats"]
            print(f"{i:>4} {label:>4} {r['events']:>6} {r['secs']:>6} {s['real_leaks']:>8} "
                  f"{s['fake_records']:>10} {s['trap_hits']:>4} {s['held_seconds']:>6}")


# ---------- 실행 ----------

async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", choices=["live", "replay"], help="agent로 시나리오 전체 실행")
    p.add_argument("-n", "--repeat", type=int, default=1)
    p.add_argument("--timeout", type=float, default=300, help="실행 1회 최대 대기 초")
    p.add_argument("--only", choices=["health", "bank", "off", "on"], help="한 구간만 점검")
    args = p.parse_args()

    async with httpx.AsyncClient(timeout=10) as c, \
            httpx.AsyncClient(base_url=GW, timeout=10) as gw, \
            httpx.AsyncClient(base_url=OPS, timeout=10) as ops:
        if args.agent:
            await agent_scenario(ops, args.agent, args.repeat, args.timeout)
        else:
            steps = {"health": lambda: health(c), "bank": lambda: bank(gw),
                     "off": lambda: decoys_off(gw, ops), "on": lambda: decoys_on(gw, ops)}
            for key, step in steps.items():
                if args.only in (None, key):
                    await safe(f"{key} 구간 실행", step())
        # 다음 사람이 쓰기 좋게 미끼 켬 + 초기화 상태로 돌려둠
        await safe("마무리: 미끼 켬 + reset", set_decoys(ops, True))

    print()
    for status, name, detail in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭"}[status]
        print(f"{mark} {name}" + (f"  ({detail})" if detail else ""))
    fails = sum(1 for s, *_ in results if s == "FAIL")
    print(f"\nPASS {sum(1 for s, *_ in results if s == 'PASS')} / FAIL {fails} / SKIP {sum(1 for s, *_ in results if s == 'SKIP')}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
