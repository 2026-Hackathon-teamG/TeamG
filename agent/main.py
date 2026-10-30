"""
Red Agent 실행 진입점.

사용법:
    python main.py --trap-off     # 허니팟 꺼진 상태로 한 라운드
    python main.py --trap-on      # 허니팟 켜진 상태로 한 라운드
    python main.py                # trap 상태를 모를 때 (trap_enabled=None)

결과는 results/<round_id>.json 파일로 저장된다.
이 JSON이 Judge와 대시보드가 읽을 원재료가 된다.
"""

import argparse
import json
import os

from config import RESULTS_DIR
from red_agent import RedAgent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Red Agent: 프롬프트 인젝션 템플릿 공격 실행")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--trap-on",
        action="store_true",
        help="허니팟이 켜진 상태에서 실행했다는 라벨을 결과에 남긴다.",
    )
    group.add_argument(
        "--trap-off",
        action="store_true",
        help="허니팟이 꺼진 상태에서 실행했다는 라벨을 결과에 남긴다.",
    )
    return parser.parse_args()


def resolve_trap_enabled(args: argparse.Namespace) -> bool | None:
    if args.trap_on:
        return True
    if args.trap_off:
        return False
    return None


def main() -> None:
    args = parse_args()
    trap_enabled = resolve_trap_enabled(args)

    agent = RedAgent(trap_enabled=trap_enabled)
    results = agent.run_round()
    result_dicts = agent.results_to_dicts(results)

    round_id = result_dicts[0]["round_id"] if result_dicts else "empty_round"

    os.makedirs(RESULTS_DIR, exist_ok=True)
    output_path = os.path.join(RESULTS_DIR, f"{round_id}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dicts, f, ensure_ascii=False, indent=2)

    # 콘솔에는 사람이 바로 확인할 수 있게 요약만 찍는다.
    sent = sum(1 for r in result_dicts if r["error"] is None)
    failed = len(result_dicts) - sent
    print(f"[Red Agent] 라운드 {round_id} 완료")
    print(f"  trap_enabled = {trap_enabled}")
    print(f"  요청 전송 성공: {sent}건 / 요청 자체 실패: {failed}건")
    print(f"  결과 저장 위치: {output_path}")


if __name__ == "__main__":
    main()