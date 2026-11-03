"""
기말 목표 계산기(학기말 등급 확률) 점검 도구 — 가상의 반으로 시험한다.

1) 계산 검증: index.html의 계산(semModel·semProbs·semGpRank)을 난수 만드는 법까지 똑같이 옮긴 SiteModel을 만든다
   (실제 사이트 화면의 확률과 소수점까지 같은지는 아래 '화면과 비교' 참고).
   사이트가 가정한 범위 안에서 '진짜' 반을 만들어 보면 확률이 잘 맞는지(보정) 본다 → 계산 코드에 오류가 없는지.
2) 민감도: 진짜 반이 사이트 가정 밖일 때(상관·기말 난이도·퍼짐·다른 학생 수행) 확률이 얼마나 빗나가는지 본다
   → 어떤 가정이 가장 위험한지, 그 가정을 재려면 어떤 자료가 필요한지 알 수 있다.

  cd tools && python3 sem_check.py                       # 미적분I 분포로 전부 (몇 분)
  python3 sem_check.py --subject 2026-2mid-hwaeon --classes 40
  python3 sem_check.py --compare-js 62 70                # 화면과 비교용 숫자 (중간 62점·기말 70점) 출력

보는 법: 각 시나리오에서 '학기말 n등급 이내' 예측 확률을 모아, (평균 예측 − 실제 비율) = 치우침, 구간별 |예측−실제| 평균 = ECE.
(치우침이 +면 사이트가 실제보다 좋은 등급을 낙관, −면 비관.)
"""
import json, math, argparse
import numpy as np
from scipy.stats import binom

RHOS = [0.65, 0.8, 0.9]; SHIFTS = [-8, 0, 8]; SCALES = [0.75, 1, 1.25]; DRAWS = 4000
Q = [0.10, 0.34, 0.66, 0.90]


# ---- index.html과 같은 난수 (mulberry32)와 정규 누적분포 근사
def js_rng(seed):
    state = [seed & 0xFFFFFFFF]
    M = 0xFFFFFFFF

    def imul(a, b):
        return (a * b) & M

    def r():
        state[0] = (state[0] + 0x6D2B79F5) & M
        s = state[0]
        t = imul(s ^ (s >> 15), 1 | s)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) ^ t) & M
        return ((t ^ (t >> 14)) & M) / 4294967296
    return r


def Phi(z):
    z = np.asarray(z, float)
    x = np.abs(z) / math.sqrt(2); t = 1 / (1 + 0.3275911 * x)
    e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return 0.5 * (1 + np.where(z < 0, -e, e))


def load_bins(sid, cuts='../cuts.json'):
    d = next(x for x in json.load(open(cuts, encoding='utf-8'))['subjects'] if x['id'] == sid)
    known = {}
    for x in d.get('dist', []):
        a, b = [float(v) for v in str(x['r']).split('~')]
        if b - a == 5:
            known[a] = x['n']
    n = [known.get(i * 5, round(h)) if i * 5 in known else round(h) for i, h in enumerate(d['hist'])]
    return np.array(n, float), int(d['n'])


def inv_of(n):
    keep = n > 0
    lo = (np.arange(20) * 5.0)[keep]; cnt = n[keep]; cum = np.cumsum(cnt); tot = cum[-1]

    def inv(u):
        t = np.asarray(u, float) * tot
        i = np.searchsorted(cum, t, side='left')
        out = np.full(t.shape, 100.0)
        ok = i < len(cnt)
        ii = i[ok]
        out[ok] = lo[ii] + (t[ok] - (cum[ii] - cnt[ii])) / cnt[ii] * 5
        return out
    return inv, tot


class SiteModel:
    """index.html semModel(기말 분포를 중간과 같은 모양으로 본 경우)의 똑같은 복사."""

    def __init__(self, n, N, perf_pen=None):
        self.N = N; self.n = n; self.ft = n.sum()
        self.lo = np.arange(20) * 5.0
        inv, self.tot = inv_of(n)
        self.mu = float((n * (self.lo + 2.5)).sum() / self.ft)
        r = js_rng(20261024)
        Z1 = np.zeros(DRAWS); Z3 = np.zeros(DRAWS)
        for i in range(DRAWS):
            R = math.sqrt(-2 * math.log(max(r(), 1e-12))); a = 2 * math.pi * r()
            Z1[i] = R * math.cos(a); Z3[i] = R * math.sin(a)
        X = inv(Phi(Z1))
        kpen = int(round(perf_pen[1] / N * DRAWS)) if perf_pen else 0
        sh = 4 * perf_pen[0] if perf_pen else 0
        self.sets = []
        for rho in RHOS:
            c = math.sqrt(1 - rho * rho)
            Y = inv(Phi(rho * Z1 + c * Z3))
            for dx in SHIFTS:
                for k in SCALES:
                    s = X + np.clip(self.mu + k * (Y - self.mu) + dx, 0, 100)
                    if kpen:
                        s[:kpen] -= sh
                    self.sets.append(dict(s=np.sort(s), rho=rho, dx=dx, k=k))
        self.R = [int(math.floor(q * N + 0.5)) for q in Q]

    def above(self, x, k=1.0):
        y = self.mu + (x - self.mu) / k
        return self.N * float(np.sum(np.where(y <= self.lo, self.n, np.where(y < self.lo + 5, self.n * (self.lo + 5 - y) / 5, 0)))) / self.ft

    def score_at_rank(self, rr):
        if self.above(0) <= rr:
            return 0.0
        a, b = 0.0, 100.0
        for _ in range(40):
            c = (a + b) / 2
            if self.above(c) > rr: a = c
            else: b = c
        return (a + b) / 2

    def probs(self, s, sets=None):
        """합계 s(배열)일 때 학기말 1~5등급 확률 (sets 평균)."""
        s = np.atleast_1d(np.asarray(s, float)); sets = sets or self.sets
        out = np.zeros((len(s), 5))
        for st in sets:
            a = np.searchsorted(st['s'], s, side='right')
            p = (len(st['s']) - a) / len(st['s'])
            prev = np.zeros(len(s))
            for g in range(5):
                cum = binom.cdf(self.R[g] - 1, self.N - 1, p) if g < 4 else np.ones(len(s))
                out[:, g] += (cum - prev) / len(sets); prev = cum
        return out

    def probs_rank(self, m, rr, adj):
        """내 중간 m(배열), 기말 목표 등수 rr(배열), 수행 보정 adj(배열) → 확률. 기말 r등의 점수를 시나리오마다 바꿔서 계산."""
        m = np.atleast_1d(m); rr = np.atleast_1d(rr); adj = np.atleast_1d(adj)
        q = np.array([self.score_at_rank(int(r)) for r in rr])
        out = np.zeros((len(m), 5))
        for st in self.sets:
            f = np.clip(self.mu + st['k'] * (q - self.mu) + st['dx'], 0, 100)
            out += self.probs(m + f + adj, [st]) / len(self.sets)
        return out


def make_class(model, N, rng, rho, dx, k, perf=(50, 0)):
    """진짜 반 하나: 중간·기말(상관 rho, 기말 이동 dx·퍼짐 k)·수행. 사이트와 같은 분포에서 뽑음."""
    inv, _ = inv_of(model.n)
    z1 = rng.standard_normal(N); z3 = rng.standard_normal(N)
    X = inv(Phi(z1)); Y = inv(Phi(rho * z1 + math.sqrt(1 - rho * rho) * z3))
    F = np.clip(model.mu + k * (Y - model.mu) + dx, 0, 100)
    if perf[0] == 'bottom':      # ('bottom', 비율, 평균, 표준편차): 중간+기말 합이 아래쪽 비율인 학생만 수행이 깎임, 나머지는 만점
        base = X + F; thr = np.quantile(base, perf[1])
        P = np.where(base <= thr, np.clip(rng.normal(perf[2], perf[3], N), 0, 50), 50.0)
    else:
        P = np.clip(rng.normal(perf[0], perf[1], N), 0, 50) if perf[1] > 0 else np.full(N, float(perf[0]))
    T = X + F + 4 * (P - 50)
    rank_sem = 1 + (T[None, :] > T[:, None]).sum(axis=1)
    rank_fin = 1 + (F[None, :] > F[:, None]).sum(axis=1)
    grade = 1 + sum((rank_sem > model.R[g]).astype(int) for g in range(4))
    return dict(X=X, F=F, P=P, T=T, rank_fin=rank_fin, grade=grade)


def evaluate(model, N, rng, classes, truth, mode):
    """사이트 예측(누적 확률 1·2·3등급 이내)을 실제 등급과 비교. 반환: 등급별 (치우침, ECE), 브라이어 평균."""
    preds, obs = [], []
    for _ in range(classes):
        c = make_class(model, N, rng, *truth)
        adj = 4 * (c['P'] - 50)
        pr = model.probs(c['T']) if mode == 'score' else model.probs_rank(c['X'], c['rank_fin'], adj)
        preds.append(np.cumsum(pr, axis=1)[:, :3]); obs.append(np.stack([(c['grade'] <= g).astype(float) for g in (1, 2, 3)], axis=1))
    P = np.concatenate(preds); O = np.concatenate(obs)
    res = []
    edges = [0, .05, .2, .4, .6, .8, .95, 1.0001]
    for g in range(3):
        bias = float(P[:, g].mean() - O[:, g].mean())
        ece = 0.0
        for a, b in zip(edges[:-1], edges[1:]):
            s = (P[:, g] >= a) & (P[:, g] < b)
            if s.any():
                ece += s.mean() * abs(P[s, g].mean() - O[s, g].mean())
        res.append((bias, ece))
    brier = float(((P - O) ** 2).mean())
    return res, brier


SCEN = [
    # (이름, (상관, 기말 이동, 기말 퍼짐, (수행 평균, 수행 표준편차)))
    ('사이트 가정 한가운데 (상관 .8, 같은 난이도, 수행 만점)', (0.8, 0, 1.0, (50, 0))),
    ('가정 안쪽 끝 (상관 .65, 기말 -8점·퍼짐 .75)', (0.65, -8, 0.75, (50, 0))),
    ('가정 안쪽 끝 (상관 .9, 기말 +8점·퍼짐 1.25)', (0.9, 8, 1.25, (50, 0))),
    ('상관이 가정보다 낮음 (.5)', (0.5, 0, 1.0, (50, 0))),
    ('상관이 가정보다 높음 (.95)', (0.95, 0, 1.0, (50, 0))),
    ('기말이 훨씬 어려움 (-12점)', (0.8, -12, 1.0, (50, 0))),
    ('기말이 훨씬 쉬움 (+12점)', (0.8, 12, 1.0, (50, 0))),
    ('기말 점수가 훨씬 퍼짐 (1.5배)', (0.8, 0, 1.5, (50, 0))),
    ('기말 점수가 훨씬 몰림 (0.6배)', (0.8, 0, 0.6, (50, 0))),
    ('다른 학생 수행이 약간 깎임 (평균 48, 표준편차 2)', (0.8, 0, 1.0, (48, 2))),
    ('다른 학생 수행이 많이 깎임 (평균 45, 표준편차 4)', (0.8, 0, 1.0, (45, 4))),
    ('다른 학생 수행이 크게 깎임 (평균 42, 표준편차 6)', (0.8, 0, 1.0, (42, 6))),
    # 실제에 가까운 경우: 수행은 대부분 만점이고 감점은 하위권만
    ('하위 20%만 수행 깎임 (평균 42, 표준편차 6)', (0.8, 0, 1.0, ('bottom', 0.2, 42, 6))),
    ('하위 30%만 수행 깎임 (평균 44, 표준편차 6)', (0.8, 0, 1.0, ('bottom', 0.3, 44, 6))),
    ('하위 40%만 수행 크게 깎임 (평균 38, 표준편차 8)', (0.8, 0, 1.0, ('bottom', 0.4, 38, 8))),
]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--subject', default='2026-2mid-calc')
    ap.add_argument('--classes', type=int, default=30)
    ap.add_argument('--only', type=int, default=0, help='시나리오 번호 이 이후만 (0부터)')
    ap.add_argument('--compare-js', nargs=2, type=float, metavar=('MID', 'FINAL'))
    a = ap.parse_args()
    n, N = load_bins(a.subject)
    M = SiteModel(n, N)
    if a.compare_js:
        mid, fin = a.compare_js
        print('점수 모드(기말 %g점):' % fin, ' '.join('%.4f' % v for v in M.probs(mid + fin)[0]))
        for rr in (5, 20, 59, 100):
            print('등수 모드(기말 %d등):' % rr, ' '.join('%.4f' % v for v in M.probs_rank(mid, rr, 0)[0]))
        raise SystemExit
    rng = np.random.default_rng(7)
    for mode, label in (('score', '점수 모드(내 기말 점수를 알 때: 다른 학생 가정만 시험)'), ('rank', '등수 모드(내 기말 등수를 알 때)')):
        print(f'\n== {a.subject} N={N}, 가상의 반 {a.classes}개 × {N}명, {label}')
        print(f'{"시나리오":52s} {"1등급이내":>14s} {"2등급이내":>14s} {"3등급이내":>14s}  브라이어')
        print(f'{"":52s} {"치우침/ECE":>14s} {"치우침/ECE":>14s} {"치우침/ECE":>14s}')
        for name, truth in SCEN[a.only:]:
            res, br = evaluate(M, N, rng, a.classes, truth, mode)
            print(f'{name:52s} ' + ' '.join(f'{b:+6.3f}/{e:5.3f}'.rjust(14) for b, e in res) + f'  {br:.4f}', flush=True)
