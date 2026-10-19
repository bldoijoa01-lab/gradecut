"""
등급컷 아카이브 - 석차/추정 컷 계산기 (불확실성 포함)

방법
1) 과목마다 '알려진 사실'(실제 컷, 점수대 인원, 평균, 응시 인원 등)을 정리한다.
2) 여러 모양의 점수 분포(치우친 정규, 베타, 정규 2개 혼합)에 대해 MCMC로
   그 사실들과 맞는 분포를 수백 개씩 뽑는다 (베이즈 사후분포).
   - 데이터와 크게 안 맞는 모양(최대 로그우도가 최고보다 3 이상 낮음)은 버린다.
3) 뽑힌 분포마다 '가상의 반'을 여러 번 만든다. 알려진 인원 수는 그대로 지키고,
   모르는 부분만 무작위로 채운다.
4) 각 점수에 대해 가상의 반들에서 나온 등수 분포 → 5%/50%/95% 지점 = 90% 범위.
   등수 → 등급(누적 10/34/66/90%, 반올림) 확률도 함께 계산.
5) 컷이 확정되지 않은 등급은 그 등수 자리의 점수 분포로 추정 컷 범위를 낸다.

python3 estimate.py            -> cuts.json에 결과 기록
python3 estimate.py --validate -> 확정 컷을 하나씩 숨기고 맞혀 보는 검증
"""
import json, sys, math
import numpy as np
from scipy import special, optimize

RNG = np.random.default_rng(20261019)
Q = [0.10, 0.34, 0.66, 0.90]
FINE = np.linspace(0, 100, 2001)          # CDF 계산용 촘촘한 격자
GRID = np.arange(0, 100.01, 0.5)          # 사이트에 저장하는 점수 격자 (201개)

# ------------------------------------------------------------ 분포 모양들
FAMILIES = {
    # 치우친 정규: xi(위치), omega(폭), alpha(치우침)
    "skewnorm": dict(lo=[0, 5, -12], hi=[130, 70, 12]),
    # 베타: a, b, 하한 lo (상한 100)
    "beta": dict(lo=[0.3, 0.3, 0], hi=[25, 25, 60]),
    # 정규 2개 혼합: w, m1, s1, m2, s2 (m1 > m2)
    "mix2": dict(lo=[0.05, 20, 3, -20, 3], hi=[0.95, 110, 35, 90, 35]),
    # 객관식 전용: '틀린 개수'가 베타이항분포, 점수 = 100 - 틀린 문항 배점 합
    "mcq": dict(lo=[0.1, 0.1], hi=[80, 80]),
    # 객관식 + 두 무리(혼합): w, a1, b1, a2, b2
    "mcq2": dict(lo=[0.05, 0.1, 0.1, 0.1, 0.1], hi=[0.95, 80, 80, 80, 80]),
}
CTX = {}   # 객관식 과목 정보 (문항 수, 배점 표준편차)


def _bb_pmf(n, a, b):
    k = np.arange(n + 1)
    lp = (special.gammaln(n + 1) - special.gammaln(k + 1) - special.gammaln(n - k + 1)
          + special.betaln(k + a, n - k + b) - special.betaln(a, b))
    p = np.exp(lp - lp.max())
    return p / p.sum()


def _mcq_cdf(pk, x):
    n, sd = CTX["n"], CTX["sd"]
    k = np.arange(n + 1)
    mu = np.clip(100 - k * 100.0 / n, 0.1, 99.9)
    s = np.maximum(sd * np.sqrt(k * (n - k) / max(n - 1, 1)), 0.05)
    return (pk[None, :] * special.ndtr((np.asarray(x, float)[:, None] - mu[None, :]) / s[None, :])).sum(axis=1)


def raw_cdf(fam, th, x):
    x = np.asarray(x, float)
    if fam == "skewnorm":
        xi, om, al = th
        z = (x - xi) / om
        return special.ndtr(z) - 2 * special.owens_t(z, al)
    if fam == "beta":
        a, b, lo = th
        u = np.clip((x - lo) / (100 - lo), 0, 1)
        return special.betainc(a, b, u)
    if fam == "mix2":
        w, m1, s1, m2, s2 = th
        return w * special.ndtr((x - m1) / s1) + (1 - w) * special.ndtr((x - m2) / s2)
    if fam == "mcq":
        return _mcq_cdf(_bb_pmf(CTX["n"], th[0], th[1]), x)
    if fam == "mcq2":
        w, a1, b1, a2, b2 = th
        return _mcq_cdf(w * _bb_pmf(CTX["n"], a1, b1) + (1 - w) * _bb_pmf(CTX["n"], a2, b2), x)
    raise ValueError(fam)


class Model:
    """0~100점으로 잘린(truncated) 분포. top(x) = x점 이상 비율."""

    def __init__(self, fam, th):
        self.fam, self.th = fam, np.asarray(th, float)
        F = raw_cdf(fam, th, FINE)
        F = np.maximum.accumulate(np.nan_to_num(F, nan=0.0))
        z = F[-1] - F[0]
        self.ok = bool(z > 1e-6)
        self.cdf = (F - F[0]) / z if self.ok else F
        if self.ok:
            pdf = np.diff(self.cdf)
            mids = (FINE[1:] + FINE[:-1]) / 2
            self.mean = float(np.sum(pdf * mids))
            self.sd = float(math.sqrt(max(np.sum(pdf * mids ** 2) - self.mean ** 2, 1e-9)))
            self.dens = pdf / (FINE[1] - FINE[0])
            self.mids = mids

    def F(self, x):                       # 잘린 분포의 누적확률 P(S < x)
        return np.interp(x, FINE, self.cdf)

    def mass(self, lo, hi):
        return np.maximum(self.F(hi) - self.F(lo), 0.0)

    def inv(self, p):                     # 누적확률 → 점수
        return np.interp(p, self.cdf, FINE)

    def top_quantile(self, q):            # 위에서 q 비율 지점의 점수
        return float(self.inv(1 - q))

    def bimodal(self):
        d = np.convolve(self.dens, np.ones(9) / 9, mode="same")
        idx = np.where((d[1:-1] >= d[:-2]) & (d[1:-1] > d[2:]) & (d[1:-1] > 1e-4))[0] + 1
        peaks = list(idx)
        if len(peaks) < 2:
            return False
        best = None
        for a in range(len(peaks)):
            for b in range(a + 1, len(peaks)):
                i, j = peaks[a], peaks[b]
                if abs(self.mids[j] - self.mids[i]) < 15:
                    continue
                valley = d[i:j + 1].min()
                ratio = valley / min(d[i], d[j])
                best = ratio if best is None else min(best, ratio)
        return best is not None and best <= 0.75


# ------------------------------------------------------------ 사실 → 구간(piece)
def rk(q, N):
    return int(math.floor(q * N + 0.5))


def realize_spec(spec, rng, fixed=False):
    """한 '가상 세계'에서 쓸 사실값 확정 (응시 인원, 애매한 컷 점수/인원 등)."""
    N = spec["N"] if isinstance(spec["N"], int) else (spec["N"][2] if fixed else int(rng.integers(spec["N"][0], spec["N"][1] + 1)))
    anchors = []
    for a in spec.get("cuts", []):          # 실제 컷: (점수 또는 [lo,hi], q)
        s = a[0]
        if isinstance(s, list):
            s = (s[0] + s[1]) / 2 if fixed else float(rng.uniform(s[0], s[1]))
        anchors.append((float(s), rk(a[1], N)))
    for a in spec.get("counts", []):        # 인원: (점수, 그 점수 이상 인원 또는 [lo,hi])
        c = a[1]
        if isinstance(c, list):
            c = int(round((c[0] + c[1]) / 2)) if fixed else int(rng.integers(c[0], c[1] + 1))
        if c == "N":
            c = N
        anchors.append((float(a[0]), int(c)))
    return N, sorted(anchors, key=lambda t: -t[0])


def build_pieces(spec, N, anchors):
    """점수축을 구간으로 나눔. 각 구간은 인원 고정(fixed) 또는 그룹(합계만 앎)."""
    bounds = [100.0001] + [s for s, _ in anchors] + [0.0]
    counts = [0] + [c for _, c in anchors] + [N]
    pieces, groups = [], []
    for j in range(len(bounds) - 1):
        hi, lo = bounds[j], bounds[j + 1]
        if hi <= lo:
            continue
        seg_n = counts[j + 1] - counts[j]
        if seg_n < 0:
            raise ValueError(f"inconsistent anchors {anchors}")
        bands = [b for b in spec.get("bands", []) if b[0] >= lo - 1e-9 and b[1] <= hi + 1e-9]
        cuts = sorted({lo, hi} | {b[0] for b in bands} | {b[1] for b in bands} |
                      {s for s in spec.get("splits", []) if lo < s < hi}, reverse=True)
        sub = [(cuts[i + 1], cuts[i]) for i in range(len(cuts) - 1) if cuts[i] - cuts[i + 1] > 1e-9]
        band_n = sum(b[2] for b in bands)
        left = [p for p in sub if not any(abs(p[0] - b[0]) < 1e-9 and abs(p[1] - b[1]) < 1e-9 for b in bands)]
        if len(sub) == 1 and not bands:
            pieces.append(dict(lo=lo, hi=hi, n=seg_n, g=None))
            continue
        gid = None
        if left:
            if seg_n - band_n < 0:
                raise ValueError("bands exceed segment")
            if len(left) == 1:
                pass
            else:
                gid = len(groups)
                groups.append(dict(total=seg_n - band_n, idx=[]))
        for p in sub:
            b = next((b for b in bands if abs(p[0] - b[0]) < 1e-9 and abs(p[1] - b[1]) < 1e-9), None)
            if b is not None:
                pieces.append(dict(lo=p[0], hi=p[1], n=b[2], g=None))
            elif gid is None:
                pieces.append(dict(lo=p[0], hi=p[1], n=seg_n - band_n, g=None))
            else:
                groups[gid]["idx"].append(len(pieces))
                pieces.append(dict(lo=p[0], hi=p[1], n=None, g=gid))
    return pieces, groups


# ------------------------------------------------------------ 우도
def loglik(spec, fam, th, N, anchors, pieces, groups):
    lo, hi = FAMILIES[fam]["lo"], FAMILIES[fam]["hi"]
    if any(t < a or t > b for t, a, b in zip(th, lo, hi)):
        return -np.inf
    if fam == "mix2" and th[1] <= th[3]:
        return -np.inf
    if fam == "mcq2" and th[1] / (th[1] + th[2]) >= th[3] / (th[3] + th[4]):
        return -np.inf
    m = Model(fam, th)
    if not m.ok:
        return -np.inf
    if spec.get("bimodal") and not m.bimodal():
        return -np.inf
    L = 0.0
    for p in pieces:                                      # 고정 인원 구간
        if p["g"] is None and p["n"]:
            L += p["n"] * math.log(max(float(m.mass(p["lo"], p["hi"])), 1e-300))
    for g in groups:                                      # 합계만 아는 그룹
        if g["total"]:
            pm = sum(float(m.mass(pieces[i]["lo"], pieces[i]["hi"])) for i in g["idx"])
            L += g["total"] * math.log(max(pm, 1e-300))
    if "mean" in spec:                                    # 평균
        se = m.sd / math.sqrt(N)
        L += -0.5 * ((m.mean - spec["mean"]) / se) ** 2 - math.log(se)
    for q, v, sd in spec.get("soft", []):                 # 애매한 컷 (예: '48?')
        L += -0.5 * ((m.top_quantile(q) - v) / sd) ** 2
    for c in spec.get("cond_min", []):                    # 예: 80점대 11명 중 85점 이상 ≥ 6
        a, b, tot, k = c
        p_in = float(m.mass(a, b)) / max(float(m.mass(c_lo(spec, a), b)), 1e-300)
        L += math.log(max(1 - _binom_cdf(k - 1, tot, p_in), 1e-300))
    for a, b, slo, shi, q, above in spec.get("cond_max", []):   # 예: 2컷 ≤ 60점
        k = rk(q, N) - 1 - above
        n_seg = next(g["total"] for g in groups if any(abs(pieces[i]["lo"] - a) < 1e-9 for i in g["idx"]))
        p_in = float(m.mass(a, b)) / max(float(m.mass(slo, shi)), 1e-300)
        L += math.log(max(_binom_cdf(k, n_seg, p_in), 1e-300))
    return L


def c_lo(spec, a):
    return spec["cond_seg_lo"]


def _binom_cdf(k, n, p):
    if k < 0:
        return 0.0
    return float(special.bdtr(k, n, min(max(p, 0.0), 1.0)))


# ------------------------------------------------------------ MCMC
def run_family(spec, fam, n_keep=300, iters=6000, chains=6, quiet=False):
    N, anchors = realize_spec(spec, RNG, fixed=True)
    pieces, groups = build_pieces(spec, N, anchors)
    lo, hi = np.array(FAMILIES[fam]["lo"], float), np.array(FAMILIES[fam]["hi"], float)
    f = lambda th: loglik(spec, fam, th, N, anchors, pieces, groups)
    # 시작점: 사전분포에서 무작위로 뽑아 국소 최적화
    starts = []
    for _ in range(60):
        th = lo + RNG.random(len(lo)) * (hi - lo)
        if fam == "mix2" and th[1] <= th[3]:
            th[1], th[3] = th[3] + 1, th[1]
        if fam == "mcq2" and th[1] / (th[1] + th[2]) >= th[3] / (th[3] + th[4]):
            th[1:3], th[3:5] = th[3:5].copy(), th[1:3].copy()
        v = f(th)
        if np.isfinite(v):
            starts.append((v, th))
    if not starts:
        return None
    starts.sort(key=lambda t: -t[0])
    opts = []
    for v, th in starts[:12]:
        def negf(t):
            v = f(t)
            return -v if np.isfinite(v) else 1e12
        r = optimize.minimize(negf, th, method="Nelder-Mead",
                              options=dict(maxiter=3000, xatol=1e-4, fatol=1e-6))
        if np.isfinite(-r.fun) and r.fun < 1e11:
            opts.append((-r.fun, r.x))
    if not opts:
        return None
    opts.sort(key=lambda t: -t[0])
    best = opts[0][0]
    samples, lls = [], []
    d = len(lo)
    for c in range(chains):
        th = opts[c % len(opts)][1].copy()
        cur = f(th)
        cov = np.diag(((hi - lo) * 0.01) ** 2)
        hist = []
        acc = 0
        for it in range(iters):
            if it >= 300 and it % 200 == 0 and it <= iters // 2:
                H = np.array(hist[-1500:])
                cov = (2.38 ** 2 / d) * np.cov(H.T) + np.diag(((hi - lo) * 1e-4) ** 2)
            prop = RNG.multivariate_normal(th, cov)
            v = f(prop)
            if np.isfinite(v) and math.log(RNG.random()) < v - cur:
                th, cur = prop, v
                acc += 1
            hist.append(th.copy())
            if it >= iters // 2 and (it - iters // 2) % 20 == 0:
                samples.append(th.copy()); lls.append(cur)
        best = max(best, max(lls) if lls else best)
    samples = np.array(samples); lls = np.array(lls)
    pick = RNG.choice(len(samples), size=min(n_keep, len(samples)), replace=False)
    if not quiet:
        print(f"    {fam:9s} maxLL={best:9.2f}  accept~{acc/iters:.2f}  kept={len(pick)}")
    return dict(fam=fam, best=best, th=samples[pick], ll=lls[pick])


def posterior(spec, quiet=False, iters=6000):
    CTX.clear(); CTX.update(spec.get("mcq", {}))
    fams = spec.get("families", ["skewnorm", "beta", "mix2"])
    res = [r for r in (run_family(spec, f, iters=iters, quiet=quiet) for f in fams) if r is not None]
    top = max(r["best"] for r in res)
    kept = [r for r in res if r["best"] >= top - 3.0]
    if not quiet:
        print("    kept families:", [r["fam"] for r in kept])
    members = [(r["fam"], th) for r in kept for th in r["th"]]
    return members, [r["fam"] for r in kept]


# ------------------------------------------------------------ 가상의 반 시뮬레이션
def allocate(rng, total, probs, D, cond=None, plus=None):
    """total명을 확률 probs로 나눔 (D번). plus=j면 그 구간에 본인 1명 추가."""
    probs = np.asarray(probs, float)
    probs = probs / probs.sum() if probs.sum() > 0 else np.ones_like(probs) / len(probs)
    out = rng.multinomial(total, probs, size=D)
    if plus is not None:
        out[:, plus] += 1
    if cond:
        for _ in range(200):
            bad = ~cond(out)
            if not bad.any():
                break
            redo = rng.multinomial(total, probs, size=int(bad.sum()))
            if plus is not None:
                redo[:, plus] += 1
            out[bad] = redo
    return out


def xgrid(spec):
    N, anchors = realize_spec(spec, RNG, fixed=True)
    pts = set(np.round(GRID, 2).tolist())
    edges = [a[0] for a in anchors] + [b[0] for b in spec.get("bands", [])] + [b[1] for b in spec.get("bands", [])]
    for c in spec.get("cuts", []):
        if isinstance(c[0], list):
            edges += [c[0][0], c[0][1]]
    for e in edges:
        if 0 < e < 100:
            pts.add(round(e, 2)); pts.add(round(e - 0.05, 2))
    return np.array(sorted(pts))


def simulate(spec, members, D=40, want_cuts=(), seed=7):
    CTX.clear(); CTX.update(spec.get("mcq", {}))
    rng = np.random.default_rng(seed)
    X = xgrid(spec)
    ranks, grades, Ns = [], [], []
    cut_samples = {k: [] for k in want_cuts}
    for fam, th in members:
        m = Model(fam, th)
        N, anchors = realize_spec(spec, rng)
        pieces, groups = build_pieces(spec, N, anchors)
        P = len(pieces)
        mass = np.array([float(m.mass(p["lo"], p["hi"])) for p in pieces])
        R = [rk(q, N) for q in Q]
        # 조건 (예: 물리 85점 이상이 80점대에서 6명 이상)
        conds = {}
        rules = [(c[0], c[1], ">=", c[3]) for c in spec.get("cond_min", [])] + \
                [(c[0], c[1], "<=", rk(c[4], N) - 1 - c[5]) for c in spec.get("cond_max", [])]
        for a, b, op, k in rules:
            for gi, g in enumerate(groups):
                for jj, pi in enumerate(g["idx"]):
                    if abs(pieces[pi]["lo"] - a) < 1e-9 and abs(pieces[pi]["hi"] - b) < 1e-9:
                        f = (lambda jj, k: (lambda out: out[:, jj] >= k))(jj, k) if op == ">=" else \
                            (lambda jj, k: (lambda out: out[:, jj] <= k))(jj, k)
                        conds.setdefault(gi, []).append(f)
        cond_by_group = {gi: (lambda fs: (lambda out: np.logical_and.reduce([f(out) for f in fs])))(fs)
                         for gi, fs in conds.items()}
        # 본인 없이 채운 기본 배정
        base = np.zeros((D, P), int)
        for p_i, p in enumerate(pieces):
            if p["g"] is None:
                base[:, p_i] = p["n"]
        for gi, g in enumerate(groups):
            al = allocate(rng, g["total"], mass[g["idx"]], D, cond_by_group.get(gi))
            base[:, g["idx"]] = al
        above0 = np.cumsum(base, axis=1) - base     # 각 구간 위쪽 인원
        # 점수 x별 등수
        rx = np.zeros((D, len(X)), np.int32)
        for p_i, p in enumerate(pieces):
            sel = (X >= p["lo"] - 1e-9) & (X < p["hi"] - 1e-9) if p["hi"] < 100 else (X >= p["lo"] - 1e-9)
            if not sel.any():
                continue
            xs = X[sel]
            pm = mass[p_i]
            t = (m.F(min(p["hi"], 100)) - m.F(xs)) / pm if pm > 0 else np.full(len(xs), 0.5)
            t = np.clip(t, 0, 1)
            if p["g"] is None:
                others = np.full(D, max(p["n"] - 1, 0))
                above = above0[:, p_i]
            else:
                g = groups[p["g"]]
                jj = g["idx"].index(p_i)
                if g["total"] < 1:
                    others = np.zeros(D, int); above = above0[:, p_i]
                else:
                    al = allocate(rng, g["total"] - 1, mass[g["idx"]], D, cond_by_group.get(p["g"]), plus=jj)
                    cnt = base.copy()
                    cnt[:, g["idx"]] = al
                    above = (np.cumsum(cnt, axis=1) - cnt)[:, p_i]
                    others = al[:, jj] - 1
            within = rng.binomial(others[:, None], t[None, :])
            rx[:, sel] = np.minimum(above[:, None] + within + 1, N)
        ranks.append(rx)
        gr = 1 + sum((rx > r).astype(np.int8) for r in R)
        grades.append(gr)
        # 추정 컷: R_k 번째 사람의 점수
        for k in want_cuts:
            Rk = R[k]
            cum = np.cumsum(base, axis=1)
            pidx = np.argmax(cum >= Rk, axis=1)
            for dd in range(D):
                pi = pidx[dd]
                n = base[dd, pi]
                j = Rk - (cum[dd, pi] - n)
                if n <= 0:
                    continue
                u = rng.beta(n - j + 1, j)
                plo, phi = pieces[pi]["lo"], min(pieces[pi]["hi"], 100)
                Flo, Fhi = m.F(plo), m.F(phi)
                cut_samples[k].append(float(m.inv(Flo + u * (Fhi - Flo))))
        Ns.append(N)
    ranks = np.concatenate(ranks, axis=0)
    grades = np.concatenate(grades, axis=0)
    return ranks, grades, cut_samples, Ns, X


# ------------------------------------------------------------ 과목별 사실
SPECS = {
    "2026-2mid-english": dict(
        N=227,
        cuts=[(91.9, .10), (76.2, .34), (53, .66), (29.8, .90)],
        counts=[(95.5, [16, 20]), (10.2, "N")],   # 1개 틀림 16~17명 + 만점 0~3명, 최저점 10.2
        mcq=dict(n=26, sd=0.304), families=["mcq", "mcq2"],   # 선택형 26문항, 배점 3.3~4.3
        why="4컷 모두 확정 + 1개 틀린 인원 + 최저점, 객관식 26문항 점수 구조 반영"),
    "2026-2mid-calc": dict(
        N=227, cuts=[(88.4, .10), (68.5, .34), (51, .66)],
        why="1~3컷 확정", est=[3]),
    "2026-2mid-geometry": dict(
        N=120, cuts=[([88.0, 89.0], .10), (67, .34)],
        soft=[(.66, 48, 5), (.90, 26, 6)],
        why="1·2컷 확정, 3·4컷은 친구 추정값(48·26)을 약하게 반영", est=[2, 3]),
    "2026-2mid-chem": dict(
        N=[116, 119, 117], cuts=[(96, .10), (79, .34)],
        why="1·2컷만 확정, 평균 모름", est=[2, 3]),
    "2026-2mid-bio": dict(
        N=[116, 119, 117], cuts=[(94.8, .10), (81.6, .34), (64.3, .66)],
        counts=[(99.5, 1)], mean=69.7,
        why="1~3컷 확정 + 평균 + 만점자 수", est=[3]),
    "2026-2mid-physics": dict(
        N=[116, 119, 117], counts=[(90, 6), (80, 17)], mean=50.9,
        splits=[85, 60], cond_min=[(85, 90, 11, 6)], cond_seg_lo=80,
        cond_max=[(60, 80, 0, 80, 0.34, 17)],      # '1·2컷 갭이 크다' → 2컷 60점 이하
        bimodal=True, families=["mix2"],
        why="90점 이상 6명·80점대 11명·평균 확정, 1컷 80 중후반·쌍봉·1·2컷 갭 큼(2컷 60 이하, 선생님 말씀 해석)", est=[0, 1, 2, 3]),
    "2026-2mid-hwaeon": dict(
        N=227, cuts=[(75, .10)], counts=[(95, 1), (90, 3)],
        bands=[(70, 75, 8), (65, 70, 24), (45, 50, 38), (40, 45, 30)],
        mcq=dict(n=26, sd=0.25), families=["mcq", "mcq2"],     # 26문항, 배점 3.4~4.2
        why="1컷 확정 + 점수대 인원 6구간, 객관식 26문항 점수 구조 반영", est=[1, 2, 3]),
}


def summarize(ranks, grades, Ns):
    r05 = np.percentile(ranks, 5, axis=0, method="lower").astype(int)
    r50 = np.percentile(ranks, 50, axis=0, method="nearest").astype(int)
    r95 = np.percentile(ranks, 95, axis=0, method="higher").astype(int)
    gp = np.stack([(grades == g).mean(axis=0) for g in range(1, 6)], axis=1)
    return r05, r50, r95, np.round(gp * 100).astype(int)


def fmt(v):
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def main():
    path = sys.argv[sys.argv.index("--cuts") + 1] if "--cuts" in sys.argv else "cuts.json"
    data = json.load(open(path, encoding="utf-8"))
    report = {}
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    for sid, spec in SPECS.items():
        if only and sid not in only:
            continue
        print("==", sid)
        members, fams = posterior(spec)
        ranks, grades, cs, Ns, X = simulate(spec, members, want_cuts=spec.get("est", []))
        r05, r50, r95, gp = summarize(ranks, grades, Ns)
        est = {}
        for k, v in cs.items():
            a = np.array(v)
            est[k] = (float(np.percentile(a, 50)), float(np.percentile(a, 5)), float(np.percentile(a, 95)))
            print(f"   {k+1}컷 추정 {est[k][0]:.1f} (90%: {est[k][1]:.1f}~{est[k][2]:.1f})")
        report[sid] = dict(est=est, fams=fams, models=len(members))
        for d in data["subjects"]:
            if d["id"] != sid:
                continue
            for key in ("tab", "tab_min", "rk_conf", "rk_low_below"):
                d.pop(key, None)
            d["rx"] = [round(float(x), 2) for x in X]
            d["r05"], d["r50"], d["r95"] = r05.tolist(), r50.tolist(), r95.tolist()
            d["gp"] = gp.tolist()
            d["rk_why"] = spec["why"]
            d["rk_models"] = len(members)
            d["rk_sims"] = 40
            d["rk_widths"] = [round(float(w), 3) for w in np.percentile((r95 - r05) / np.mean(Ns), [10, 50, 90])]
            d["rk_fams"] = fams
            if est:
                c = list(d.get("c", ["", "", "", ""]))
                ranges = []
                for k, (med, lo5, hi95) in sorted(est.items()):
                    c[k] = fmt(med) + "?"
                    ranges.append(f"{k+1}컷 {fmt(lo5)}~{fmt(hi95)}")
                d["c"] = c
                d["cut_ranges"] = {str(k + 1): [round(v[1], 1), round(v[0], 1), round(v[2], 1)] for k, v in est.items()}
                d["note"] = "추정 컷은 알려진 사실과 맞는 분포를 여러 개 뽑아 계산한 값이에요 · 90% 범위: " + " · ".join(ranges)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(report, open("estimate_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def validate():
    """확정 컷을 하나씩 숨기고 나머지 사실로 맞혀 보기."""
    tests = [("2026-2mid-english", k) for k in range(4)] + [("2026-2mid-calc", k) for k in range(3)] + \
            [("2026-2mid-bio", k) for k in range(3)]
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")
        tests = [t for t in tests if t[0] in only]
    rows = []
    for sid, k in tests:
        spec = json.loads(json.dumps(SPECS[sid]))
        spec["cuts"] = [tuple(c) for c in spec["cuts"]]
        actual = spec["cuts"][k][0]
        spec["cuts"] = [c for i, c in enumerate(spec["cuts"]) if i != k]
        spec["counts"] = [tuple(c) for c in spec.get("counts", [])]
        members, fams = posterior(spec, quiet=True, iters=4000)
        _, _, cs, _, _ = simulate(spec, members, D=30, want_cuts=[k])
        a = np.array(cs[k])
        med, lo5, hi95 = np.percentile(a, 50), np.percentile(a, 5), np.percentile(a, 95)
        inside = lo5 <= actual <= hi95
        rows.append(dict(subject=sid, cut=k + 1, actual=actual, pred=round(float(med), 1),
                         lo=round(float(lo5), 1), hi=round(float(hi95), 1), inside=bool(inside),
                         err=round(float(med - actual), 1)))
        print(f"{sid:20s} {k+1}컷 실제 {actual:5.1f} | 예측 {med:5.1f} (90%: {lo5:5.1f}~{hi95:5.1f}) {'O' if inside else 'X'}  오차 {med-actual:+.1f}")
    cov = sum(r["inside"] for r in rows)
    mae = float(np.mean([abs(r["err"]) for r in rows]))
    print(f"범위 적중 {cov}/{len(rows)}, 평균 오차 {mae:.1f}점")
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "validation.json"
    json.dump(dict(rows=rows, coverage=cov, total=len(rows), mae=round(mae, 1)),
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    validate() if "--validate" in sys.argv else main()
