"""Daily price update for "הסל הזול".

Downloads the official price-transparency files (Israel's Food Law) for the
stores that serve Tzur Hadassah, parses them, and writes docs/catalog.json
for the calculator site. Standard library only.
"""
import gzip, io, json, re, sys, os, datetime, http.cookiejar, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs')
UA = 'Mozilla/5.0 (hasal-hazol price updater)'
NOW = datetime.datetime.utcnow() + datetime.timedelta(hours=2)

# id, kind, params
STORES = [
    ('SH', 'shufersal', {'store': '413'}),
    ('CO', 'carrefour', {'store': '471'}),
    ('CB', 'carrefour', {'store': '033'}),
    ('RL', 'cerberus', {'user': 'RamiLevi', 'store': '012'}),
    ('OA', 'cerberus', {'user': 'osherad', 'store': '018'}),
    ('YO', 'cerberus', {'user': 'yohananof', 'store': '020'}),
    ('KT', 'cerberus', {'user': 'Keshet', 'store': '010'}),
    ('MH', 'laib', {'code': '7290661400001001267'}),
    ('VI', 'laib', {'code': '7290696200003001097'}),
]
CLUB_OK = {'SH'}  # the family is a Shufersal club member
EXC = re.compile('קופון|מתנה|ומעלה|סיבוס|סודקסו|עובד|כרטיס|ביטוח|אשראי|תן ביס|גיפט|שובר|נקודות|ארגון|הקרן|עמותת')


def opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [('User-Agent', UA)]
    return op


def get(op, url, data=None, timeout=120):
    if data is not None:
        data = urllib.parse.urlencode(data).encode()
    with op.open(url, data=data, timeout=timeout) as r:
        return r.read()


def latest(names, kind, store):
    c = [n for n in names if n.lower().startswith(kind) and re.search(r'-' + store + r'-', n)]
    return sorted(c)[-1] if c else None


def fetch_shufersal(p):
    op = opener(); out = {}
    for kind, cat in (('price', 2), ('promo', 4)):
        html = get(op, f'https://prices.shufersal.co.il/FileObject/UpdateCategory?catID={cat}&storeId={p["store"]}').decode('utf-8', 'replace')
        links = re.findall(r'href="(https://[^"]+\.gz[^"]*)"', html)
        if links:
            out[kind] = get(op, links[0].replace('&amp;', '&'))
    return out


def fetch_carrefour(p):
    op = opener(); out = {}
    html = get(op, 'https://prices.carrefour.co.il/').decode('utf-8', 'replace')
    path = (re.search(r'path\s*=\s*["\'](\d{8})', html) or [None, NOW.strftime('%Y%m%d')])[1]
    names = re.findall(r'"name"\s*:\s*"((?:PriceFull|PromoFull)[^"]+\.gz)"', html)
    for kind, pre in (('price', 'pricefull'), ('promo', 'promofull')):
        n = latest(names, pre, p['store'])
        if n:
            out[kind] = get(op, f'https://prices.carrefour.co.il/{path}/{n}')
    return out


def fetch_cerberus(p):
    op = opener(); base = 'https://url.publishedprices.co.il'
    h = get(op, base + '/login').decode('utf-8', 'replace')
    tok = re.search(r'name="csrftoken" content="([^"]+)"', h).group(1)
    get(op, base + '/login/user', {'r': '', 'username': p['user'], 'password': '', 'Submit': 'Sign in', 'csrftoken': tok})
    h = get(op, base + '/file').decode('utf-8', 'replace')
    tok = re.search(r'name="csrftoken" content="([^"]+)"', h).group(1)
    j = json.loads(get(op, base + '/file/json/dir', {'sEcho': '1', 'iColumns': '5', 'iDisplayStart': '0', 'iDisplayLength': '100000', 'sSearch': '', 'cd': '/', 'csrftoken': tok}))
    names = [x['name'] for x in j['aaData']]
    out = {}
    for kind, pre in (('price', 'pricefull'), ('promo', 'promofull')):
        n = latest(names, pre, p['store'])
        if n:
            out[kind] = get(op, base + '/file/d/' + n)
    return out


def fetch_laib(p):
    op = opener(); out = {}
    for back in range(14):
        d = (NOW - datetime.timedelta(days=back)).strftime('%d/%m/%Y')
        for kind, ft in (('price', 'pricefull'), ('promo', 'promofull')):
            if kind in out:
                continue
            html = get(op, f'https://laibcatalog.co.il/NBCompetitionRegulations.aspx?code={p["code"]}&fileType={ft}&date={urllib.parse.quote(d)}').decode('utf-8', 'replace')
            links = re.findall(r'href="([^"]+\.gz)"', html)
            if links:
                out[kind] = get(op, 'https://laibcatalog.co.il/' + links[0].replace('\\', '/'))
        if 'price' in out:
            break
    return out


def xml_root(raw):
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        raw = raw.decode('utf-16').encode('utf-8')
    raw = raw.lstrip(b'\xef\xbb\xbf')
    raw = re.sub(rb'<\?xml[^>]*\?>', b'', raw, count=1)
    return ET.fromstring(raw)


def txt(e, tag):
    t = tag.lower()
    for c in e.iter():
        if c.tag.lower() == t:
            return (c.text or '').strip()
    return ''


def parse_prices(raw):
    out = {}
    for it in xml_root(raw).iter():
        if it.tag.lower() != 'item':
            continue
        try:
            p = float(txt(it, 'ItemPrice'))
        except ValueError:
            continue
        out[txt(it, 'ItemCode')] = {'name': txt(it, 'ItemName'), 'mfr': txt(it, 'ManufactureName'), 'w': txt(it, 'bIsWeighted'), 'price': p}
    return out


def pdate(s):
    s = s.strip().replace('T', ' ')
    for f in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s[:26], f)
        except ValueError:
            pass
    return None


def parse_promos(raw):
    out = {}
    for pr in xml_root(raw).iter():
        if pr.tag.lower() != 'promotion':
            continue
        sd = pdate(txt(pr, 'PromotionStartDateTime') or (txt(pr, 'PromotionStartDate') + ' ' + txt(pr, 'PromotionStartHour')))
        ed = pdate(txt(pr, 'PromotionEndDateTime') or (txt(pr, 'PromotionEndDate') + ' ' + txt(pr, 'PromotionEndHour')))
        if (sd and sd > NOW) or (ed and ed < NOW):
            continue
        clubs = [(c.text or '').strip() for c in pr.iter() if c.tag.lower() == 'clubid']
        club = any(c not in ('', '0') for c in clubs) and '0' not in clubs
        desc = txt(pr, 'PromotionDescription')
        mq0, dp0 = txt(pr, 'MinQty'), txt(pr, 'DiscountedPrice')
        for pi in pr.iter():
            if pi.tag.lower() not in ('promotionitem', 'item'):
                continue
            code = txt(pi, 'ItemCode')
            if not code:
                continue
            try:
                mq = float(txt(pi, 'MinQty') or mq0 or 1); dp = float(txt(pi, 'DiscountedPrice') or dp0 or 0)
            except ValueError:
                continue
            out.setdefault(code, []).append((mq, dp, club, desc))
    return out


def main():
    P, R, ok, report = {}, {}, [], {}
    for sid, kind, p in STORES:
        try:
            files = globals()['fetch_' + kind](p)
            if 'price' not in files:
                report[sid] = 'no price file'; continue
            P[sid] = parse_prices(files['price'])
            R[sid] = parse_promos(files['promo']) if 'promo' in files else {}
            ok.append(sid); report[sid] = f'{len(P[sid])} items'
        except Exception as e:  # keep going with the other chains
            report[sid] = f'error: {type(e).__name__}: {e}'[:200]
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if len(ok) < 3:
        print('Too few stores fetched; keeping the previous catalog.')
        sys.exit(1)
    cnt = Counter(c for s in ok for c in P[s])
    keep = [c for c, n in cnt.items() if n >= 2 or any(P[s].get(c, {}).get('w') == '1' for s in ok)]
    items = []
    for c in keep:
        names = [P[s][c]['name'] for s in ok if c in P[s]]
        src = next(P[s][c] for s in ok if c in P[s])
        w = 1 if any(P[s].get(c, {}).get('w') == '1' for s in ok) else 0
        prices, promos = [], []
        for s in ok:
            if c not in P[s]:
                prices.append(0); promos.append(0); continue
            price = P[s][c]['price']; best = None
            for mq, dp, club, desc in R[s].get(c, []):
                if dp <= 0 or (club and (s not in CLUB_OK or EXC.search(desc))):
                    continue
                u = dp / (mq or 1)
                if price * 0.3 < u < price * 0.98 and (best is None or u < best[1]):
                    best = (round(mq or 1, 2), round(u, 3))
            prices.append(round(price, 2)); promos.append(list(best) if best else 0)
        items.append([c, re.sub(r'\s+', ' ', max(names, key=len)).strip(), (src['mfr'] or '').strip()[:20], w, prices, promos])
    os.makedirs(OUT, exist_ok=True)
    data = {'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'stores': ok, 'report': report, 'items': items}
    with open(os.path.join(OUT, 'catalog.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print('items', len(items), 'stores', ok)


if __name__ == '__main__':
    main()
