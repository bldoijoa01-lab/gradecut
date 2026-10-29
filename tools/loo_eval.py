"""
성적표 한 장씩 빼고 맞혀 보기 (leave-one-card-out) — 석차 계산이 처음 보는 점수를 얼마나 맞히는지 재는 도구.

각 (과목, 성적표 점수)마다 그 석차 사실만 빼고 계산한 뒤, 뺀 점수의 예상 석차(5%·50%·95%)를 학교 석차와 비교한다.
성적표가 새로 모이면 아래 CARDS에 (점수, 석차, 동석차 수)를 넣고 돌려서 index.html의 CAL(석차 범위 넓히는 배수)을 다시 정할 것.

  cd tools && python3 loo_eval.py                      # 전부 (코어 하나면 20~30분)
  python3 loo_eval.py --cards 1,2 --out a.json         # 일부만 (여러 개로 나눠 병렬로 돌릴 수 있음)
  python3 loo_eval.py --summary a.json b.json          # 결과 합쳐 보기: 평균 오차, 범위 안 비율(폭 1.0·1.3·1.6배)

2026-10 결과: 26개, 평균 절대 오차 2.0등, 계산 범위 그대로 22개(85%)·1.3배면 24개(92%)가 90% 범위 안 → CAL=1.3.
오차의 대부분은 구간 안 학생이 흩어지는 운(정보가 없는 부분)이라, 분포 모양을 더 자유롭게 해도(스플라인) 평균 계산을 정교하게 해도 줄지 않았음.
"""
import sys, json, copy, argparse
import numpy as np
import estimate as E

# 성적표 (이름 없이): {장 번호: {과목: (점수, 석차, 동석차 수)}}
CARDS = {
    1: {'hwaeon': (73.1, 24, 1), 'calc': (94.5, 8, 3), 'geometry': (89.4, 7, 1), 'english': (83.9, 52, 2), 'physics': (95.8, 2, 1), 'chem': (95.0, 12, 1), 'bio': (96.8, 4, 2)},
    2: {'hwaeon': (53.1, 92, 4), 'calc': (79.1, 38, 2), 'geometry': (53.1, 63, 1), 'english': (68.2, 90, 2), 'physics': (43.7, 62, 2), 'chem': (51.0, 80, 1), 'bio': (69.1, 51, 1)},
    3: {'hwaeon': (69.5, 33, 1), 'calc': (95.1, 5, 1), 'geometry': (74.2, 23, 1), 'english': (88.1, 31, 3), 'physics': (84.7, 15, 1), 'chem': (96.5, 5, 5), 'bio': (92.4, 15, 1)},
    4: {'hwaeon': (70.0, 30, 1), 'calc': (79.0, 40, 1), 'english': (68.1, 92, 2), 'geo': (97.4, 1, 1), 'econ': (92.9, 3, 2)},
}


def run(cards, families=None):
    out = []
    grid = E.xgrid
    for k in cards:
        for sub, (sc, rk, t) in CARDS[k].items():
            spec = copy.deepcopy(E.SPECS['2026-2mid-' + sub])
            spec['ranks'] = [r for r in spec.get('ranks', []) if abs(r[0] - sc) > 1e-6]
            if families:
                spec['families'] = families
            E.xgrid = lambda sp, sc=sc: np.array(sorted(set(np.round(grid(sp), 2).tolist()) | {round(sc, 2)}))
            members, _ = E.posterior(spec, quiet=True)
            ranks, grades, _, Ns, X = E.simulate(spec, members)
            r05, r50, r95, _ = E.summarize(ranks, grades, Ns)
            j = int(np.argmin(np.abs(X - sc)))
            row = dict(card=k, subject=sub, score=sc, rank=rk, lo=int(r05[j]), mid=int(r50[j]), hi=int(r95[j]))
            out.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    E.xgrid = grid
    return out


def summary(rows):
    n = len(rows)
    err = [r['rank'] - r['mid'] for r in rows]
    print(f"{n}개: 평균 절대 오차 {sum(abs(e) for e in err) / n:.2f}등, 편향(학교-예상 평균) {sum(err) / n:+.2f}")
    for cal in (1.0, 1.3, 1.6):
        ins = w = 0
        for r in rows:
            lo = max(1, round(r['mid'] - cal * (r['mid'] - r['lo']))); hi = round(r['mid'] + cal * (r['hi'] - r['mid']))
            ins += lo <= r['rank'] <= hi; w += hi - lo
        print(f"  범위 폭 {cal}배: {ins}/{n} ({ins / n * 100:.0f}%)가 90% 범위 안, 평균 폭 {w / n:.1f}등")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--cards', default=','.join(map(str, CARDS)))
    ap.add_argument('--families', help='쉼표로 구분한 분포 모양(기본: 과목별 설정)')
    ap.add_argument('--out')
    ap.add_argument('--summary', nargs='+', help='결과 json 파일들을 합쳐 요약만 보기')
    a = ap.parse_args()
    if a.summary:
        rows = []
        for f in a.summary:
            rows += json.load(open(f, encoding='utf-8'))
        summary(rows)
    else:
        rows = run([int(c) for c in a.cards.split(',')], a.families.split(',') if a.families else None)
        summary(rows)
        if a.out:
            json.dump(rows, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False)
