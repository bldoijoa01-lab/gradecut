import json, numpy as np
from scipy import stats, optimize
from scipy.interpolate import PchipInterpolator

G = np.arange(0, 101)  # score grid

def trunc(dist):
    a, b = dist.cdf(0), dist.cdf(100)
    Z = max(b - a, 1e-9)
    global OUT; OUT = 1 - Z
    sf = lambda x: np.clip((b - dist.cdf(np.asarray(x, float))) / Z, 0, 1)
    xs = np.linspace(0, 100, 2001); pdf = dist.pdf(xs) / Z
    mean = np.trapezoid(xs * pdf, xs)
    return sf, mean

FAM = {
 'normal':   (lambda p: stats.norm(p[0], abs(p[1]) + .5), [[60, 20], [75, 15], [45, 25]]),
 'skewnorm': (lambda p: stats.skewnorm(p[0], p[1], abs(p[2]) + .5), [[-3, 85, 25], [-1, 70, 20], [2, 40, 20]]),
 'beta':     (lambda p: stats.beta(abs(p[0]) + .05, abs(p[1]) + .05, loc=0, scale=100), [[3, 1.3], [2, 2], [1.2, 2]]),
 'mix2':     (lambda p: Mix(p), [[.25, 85, 7, 42, 12], [.35, 80, 9, 40, 13], [.2, 88, 5, 45, 14]]),
}
class Mix:
    def __init__(s, p):
        w = 1 / (1 + np.exp(-(p[0] - .5) * 6)) if False else min(max(p[0], .02), .98)
        s.w = w; s.a = stats.norm(p[1], abs(p[2]) + .5); s.b = stats.norm(p[3], abs(p[4]) + .5)
    def cdf(s, x): return s.w * s.a.cdf(x) + (1 - s.w) * s.b.cdf(x)
    def pdf(s, x): return s.w * s.a.pdf(x) + (1 - s.w) * s.b.pdf(x)

def fit(spec, families):
    N = spec['n']
    def loss(p, fam):
        try: sf, mean = trunc(FAM[fam][0](p))
        except Exception: return 1e9
        L = 0
        for sc, f, w in spec['pts']: L += w * (sf(sc) - f) ** 2
        for lo, hi, cnt, w in spec.get('bands', []): L += w * ((sf(lo) - sf(hi)) - cnt / N) ** 2
        if 'mean' in spec: L += 30 * ((mean - spec['mean']) / 100) ** 2
        L += 0.5 * OUT ** 2  # 0~100 밖으로 새는 분포는 비현실적이라 약하게 벌점
        return L if np.isfinite(L) else 1e9
    best = None
    for fam in families:
        for x0 in FAM[fam][1]:
            r = optimize.minimize(loss, x0, args=(fam,), method='Nelder-Mead', options={'maxiter': 40000, 'xatol': 1e-7, 'fatol': 1e-12})
            if best is None or r.fun < best[0]: best = (r.fun, fam, r.x)
    return best

def build(spec, families):
    L, fam, p = fit(spec, families)
    sf, mean = trunc(FAM[fam][0](p))
    base = sf(G)
    # 확정 점(hard)을 정확히 지나가도록 잔차를 단조 보간으로 보정
    hard = sorted({(0.0, None), (100.0, None)} | {(float(s), f) for s, f, w in spec['pts'] if w >= 50}, key=lambda t: t[0])
    xs, rs = [], []
    for s, f in hard:
        xs.append(s); rs.append(0.0 if f is None else f - float(sf(s)))
    if spec.get('top_zero'): rs[-1] = 0.0
    corr = PchipInterpolator(xs, rs)(G) if len(xs) > 2 else np.zeros_like(G, float)
    tab = np.clip(base + corr, 0, 1)
    # monotone: tab[s] >= tab[s+1]
    for i in range(99, -1, -1): tab[i] = max(tab[i], tab[i + 1])
    tab[100] = min(tab[100], 0.0) if spec.get('top_zero') else tab[100]
    cuts = {q: float(np.interp(q, tab[::-1], G[::-1])) for q in (0.10, 0.34, 0.66, 0.90)}
    return dict(fam=fam, loss=L, mean=round(mean, 1), tab=[round(float(t), 4) for t in tab], cuts={k: round(v, 1) for k, v in cuts.items()})

H, S = 100, 5   # weights: hard / soft
specs = {
 '2026-2mid-english': dict(n=227, pts=[(95.5, 18/227, H), (91.9, .10, H), (76.2, .34, H), (53, .66, H), (29.8, .90, H)]),
 '2026-2mid-calc':    dict(n=227, pts=[(88.4, .10, H), (68.5, .34, H), (51, .66, H)]),
 '2026-2mid-geometry':dict(n=120, pts=[(88.5, .10, H), (67, .34, H), (48, .66, S), (26, .90, S)]),
 '2026-2mid-chem':    dict(n=117, pts=[(96, .10, H), (79, .34, H)]),
 '2026-2mid-bio':     dict(n=117, mean=69.7, pts=[(99.5, 1/117, H), (94.8, .10, H), (81.6, .34, H), (64.3, .66, H)]),
 '2026-2mid-physics': dict(n=117, mean=50.9, pts=[(90, 6/117, H), (80, 17/117, H), (87, .10, S), (53, .34, S), (40, .66, S), (29, .90, S)]),
 '2026-2mid-hwaeon':  dict(n=227, pts=[(95, 1/227, H), (90, 3/227, H), (75, .10, H), (70, 31/227, H), (65, 55/227, H)],
                          bands=[(45, 50, 38, 60), (40, 45, 30, 60)]),
}
fams = {k: ['normal', 'skewnorm', 'beta'] for k in specs}
fams['2026-2mid-physics'] = ['mix2']
fams['2026-2mid-hwaeon'] = ['skewnorm', 'beta', 'mix2']
fams['2026-2mid-chem'] = ['normal']
out = {}
for k, sp in specs.items():
    r = build(sp, fams[k]); out[k] = r
    print(k, r['fam'], 'loss', '%.2e' % r['loss'], 'mean', r['mean'], 'cuts', r['cuts'])
json.dump(out, open('/tmp/claude-0/-home-claude/32c4347f-4e96-552b-b16e-e689c25e5f2a/scratchpad/fit/tabs.json', 'w'))

t=np.array(out['2026-2mid-english']['tab']); N=227
for sc in (100,96,95.5,93,91.9,90,88,85,80,76.2): print('eng',sc, round(float(np.interp(sc,np.arange(101),t))*N,1))

t=np.array(out['2026-2mid-bio']['tab']); N=117
for sc in (100,99.5,98,96.8,95,94.8): print('bio',sc, round(float(np.interp(sc,np.arange(101),t))*N,1))
