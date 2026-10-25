"""
새 시험(예: 기말) 과목 칸을 cuts.json에 한꺼번에 만들기.
기준 시험의 과목 이름·학점·별명·공통과목 여부를 그대로 가져오고, 컷은 빈칸으로 둠.

python3 tools/add_exam.py --from "2026 2학기 중간" --to "2026 2학기 기말" --prefix 2026-2fin
  → id는 기준 과목 id의 앞부분(예: 2026-2mid)을 --prefix로 바꾼 것 (2026-2mid-calc → 2026-2fin-calc)

주의: 과목이 하나라도 들어가면 그 시험은 '준비 중'이 아니라 일반 시험 탭이 됨
      (기말 목표 계산기 대신 기말 컷 화면이 나옴). 컷이 실제로 들어올 때 실행할 것.
"""
import json, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True)
ap.add_argument("--to", dest="dst", required=True)
ap.add_argument("--prefix", required=True)
ap.add_argument("--cuts", default="cuts.json")
ap.add_argument("--only", help="쉼표로 구분한 과목 이름만 (예: 미적분I,영어II)")
a = ap.parse_args()

data = json.load(open(a.cuts, encoding="utf-8"))
base = [s for s in data["subjects"] if s["exam"] == a.src]
if not base:
    sys.exit(f"'{a.src}' 시험 과목이 없어요")
only = set(a.only.split(",")) if a.only else None
have = {s["id"] for s in data["subjects"]}
added = []
for s in base:
    if only and s["subject"] not in only:
        continue
    sid = a.prefix + "-" + s["id"].split("-", 2)[-1]
    if sid in have:
        print("이미 있음:", sid)
        continue
    new = {k: s[k] for k in ("subject", "cr", "alias", "common") if k in s}
    data["subjects"].append({"id": sid, "exam": a.dst, **new, "c": ["", "", "", ""]})
    added.append(sid)
json.dump(data, open(a.cuts, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"{len(added)}과목 추가:", ", ".join(added))
