"""Daily price update for "הסל הזול".

Downloads the official price-transparency files (Israel's Food Law) for the
stores that serve Tzur Hadassah, parses them, and writes docs/catalog.json
for the calculator site. Standard library only.
"""
import gzip, io, json, re, sys, os, datetime, http.cookiejar, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs')
LOCAL = os.path.join(os.path.dirname(__file__), '..', 'data', 'local')  # copies fetched from Israel (chains that block servers abroad)
LOCAL_MAX_DAYS = 3
UA = 'Mozilla/5.0 (hasal-hazol price updater)'
NOW = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).replace(tzinfo=None)

# id, kind, params, how it is shown on the site
STORES = [
    ('SH', 'shufersal', {'store': '413'}, {'name': 'שופרסל אונליין', 'mode': 'delivery', 'fee': 35.9, 'min': 250, 'area': 'delivery'}),
    ('CO', 'carrefour', {'store': '471'}, {'name': 'קרפור אונליין', 'mode': 'delivery', 'fee': 29.9, 'min': 250, 'area': 'delivery', 'note': 'לא אומת שמשלחת לכל ישוב'}),
    ('VI', 'laib', {'code': '7290696200003001097'}, {'name': 'ויקטורי אונליין', 'mode': 'delivery', 'fee': 35.9, 'min': 250, 'area': 'delivery', 'note': 'דמי המשלוח הם הערכה'}),
    # Tzur Hadassah area
    ('CB', 'carrefour', {'store': '033'}, {'name': 'קרפור היפר בית שמש', 'mode': 'store', 'area': 'bs'}),
    ('RL', 'cerberus', {'user': 'RamiLevi', 'store': '012'}, {'name': 'רמי לוי ביתר עילית', 'mode': 'store', 'area': 'beitar'}),
    ('OA', 'cerberus', {'user': 'osherad', 'store': '018'}, {'name': 'אושר עד ביתר עילית', 'mode': 'store', 'area': 'beitar'}),
    ('YO', 'cerberus', {'user': 'yohananof', 'store': '020'}, {'name': 'יוחננוף תלפיות', 'mode': 'store', 'area': 'jlm'}),
    ('KT', 'cerberus', {'user': 'Keshet', 'store': '010'}, {'name': 'קשת טעמים גבעת רם', 'mode': 'store', 'area': 'jlm'}),
    ('MH', 'laib', {'code': '7290661400001001267'}, {'name': 'מחסני השוק צור הדסה', 'mode': 'store', 'area': 'local'}),
    # Rishon LeZion area
    ('HH', 'hazi', {'store': '103'}, {'name': 'חצי חינם אונליין', 'mode': 'delivery', 'fee': 35.9, 'min': 500, 'area': 'delivery', 'note': 'משלוח באזור המרכז'}),
    ('TO', 'cerberus', {'user': 'TivTaam', 'store': '514'}, {'name': 'טיב טעם אונליין', 'mode': 'delivery', 'fee': 29.9, 'min': 250, 'area': 'delivery', 'note': 'דמי המשלוח הם הערכה'}),
    ('SD', 'shufersal', {'store': '184'}, {'name': 'שופרסל דיל ז׳בוטינסקי ראשל״צ', 'mode': 'store', 'area': 'rishon'}),
    ('RR', 'cerberus', {'user': 'RamiLevi', 'store': '043'}, {'name': 'רמי לוי ראשון לציון', 'mode': 'store', 'area': 'rishon'}),
    ('OR', 'cerberus', {'user': 'osherad', 'store': '025'}, {'name': 'אושר עד ראשון לציון', 'mode': 'store', 'area': 'rishon'}),
    ('YR', 'cerberus', {'user': 'yohananof', 'store': '028'}, {'name': 'יוחננוף רמת אליהו', 'mode': 'store', 'area': 'rishon'}),
    ('KR', 'cerberus', {'user': 'Keshet', 'store': '024'}, {'name': 'קשת טעמים ראשל״צ מערב', 'mode': 'store', 'area': 'rishon'}),
    ('CR', 'carrefour', {'store': '063'}, {'name': 'קרפור מרקט ראשל״צ', 'mode': 'store', 'area': 'rishon'}),
]
# each region gets its own catalog file; the site picks one by the town in the address
REGIONS = {
    'tzur': {'file': 'catalog.json', 'stores': ['SH', 'CO', 'VI', 'CB', 'RL', 'OA', 'YO', 'KT', 'MH'],
             'areas': [['delivery', 'משלוח עד הבית', 'שופרסל אונליין, קרפור אונליין'],
                       ['local', 'קנייה בצור הדסה', 'מחסני השוק, כשהיא מפרסמת מחירים'],
                       ['bs', 'קנייה או איסוף בבית שמש', 'קרפור היפר'],
                       ['beitar', 'קנייה בביתר עילית', 'רמי לוי, אושר עד'],
                       ['jlm', 'קנייה בירושלים', 'יוחננוף תלפיות, קשת טעמים']]},
    'rishon': {'file': 'catalog-rishon.json', 'stores': ['SH', 'CO', 'HH', 'TO', 'SD', 'RR', 'OR', 'YR', 'KR', 'CR'],
               'areas': [['delivery', 'משלוח עד הבית', 'שופרסל, חצי חינם, טיב טעם, קרפור'],
                         ['rishon', 'קנייה בסניפים בראשון לציון', 'שופרסל דיל, רמי לוי, אושר עד, יוחננוף, קשת טעמים, קרפור']]},
}
CLUB_OK = {'SH'}  # the family is a Shufersal club member
EXC = re.compile('קופון|מתנה|ומעלה|סיבוס|סודקסו|עובד|כרטיס|ביטוח|אשראי|תן ביס|גיפט|שובר|נקודות|ארגון|הקרן|עמותת')


def opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [('User-Agent', UA)]
    return op


def get(op, url, data=None, timeout=45):
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
    html = get(op, 'https://prices.carrefour.co.il/', timeout=20).decode('utf-8', 'replace')
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
    for back in range(4):
        d = (NOW - datetime.timedelta(days=back)).strftime('%d/%m/%Y')
        for kind, ft in (('price', 'pricefull'), ('promo', 'promofull')):
            if kind in out:
                continue
            html = get(op, f'https://laibcatalog.co.il/NBCompetitionRegulations.aspx?code={p["code"]}&fileType={ft}&date={urllib.parse.quote(d)}', timeout=20).decode('utf-8', 'replace')
            links = re.findall(r'href="([^"]+\.gz)"', html)
            if links:
                out[kind] = get(op, 'https://laibcatalog.co.il/' + links[0].replace('\\', '/'))
        if 'price' in out:
            break
    return out


def fetch_hazi(p):
    op = opener(); out = {}; links = []
    for back in range(2):
        d = (NOW - datetime.timedelta(days=back)).strftime('%Y-%m-%d')
        for t in ('1', '2'):
            for page in range(1, 6):
                html = get(op, f'https://shop.hazi-hinam.co.il/Prices?p={page}&s=&f=&t={t}&d={d}', timeout=30).decode('utf-8', 'replace')
                found = re.findall(r'href="(https://[^"]+\.gz)"', html)
                links += found
                if not found or any(re.search(r'(PriceFull|PromoFull)\d+-\d+-' + p['store'] + '-', x) for x in found):
                    break
        if any('PriceFull' in x and '-' + p['store'] + '-' in x for x in links):
            break
    names = {x.rsplit('/', 1)[1]: x for x in links}
    for kind, pre in (('price', 'pricefull'), ('promo', 'promofull')):
        n = latest(list(names), pre, p['store'])
        if n:
            out[kind] = get(op, names[n])
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


def usable(sid, promos):
    """Keep only promos the family can actually use (see the rule in main)."""
    out = {}
    for code, lst in promos.items():
        keep = [[mq, dp, False, ''] for mq, dp, club, desc in lst
                if dp > 0 and not (club and (sid not in CLUB_OK or EXC.search(desc)))]
        if keep:
            out[code] = keep
    return out


def save_local(sid, price_file, promo_file=None):
    """Run on a computer in Israel: parse downloaded files into data/local/<sid>.json."""
    with open(price_file, 'rb') as f:
        P = parse_prices(f.read())
    R = {}
    if promo_file:
        with open(promo_file, 'rb') as f:
            R = usable(sid, parse_promos(f.read()))
    os.makedirs(LOCAL, exist_ok=True)
    with open(os.path.join(LOCAL, sid + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'date': NOW.strftime('%Y-%m-%d %H:%M'), 'P': P, 'R': R}, f, ensure_ascii=False, separators=(',', ':'))
    print(sid, len(P), 'items', len(R), 'promos')


def load_local(sid):
    fn = os.path.join(LOCAL, sid + '.json')
    if not os.path.exists(fn):
        return None
    with open(fn, encoding='utf-8') as f:
        d = json.load(f)
    age = NOW - datetime.datetime.strptime(d['date'], '%Y-%m-%d %H:%M')
    if age > datetime.timedelta(days=LOCAL_MAX_DAYS):
        return None
    return d


def build(P, R, ok):
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
                    best = (round(mq or 1, 2), round(u, 3), 1 if club else 0)  # 1 = club-only (the site can switch it off)
            prices.append(round(price, 2)); promos.append(list(best) if best else 0)
        items.append([c, re.sub(r'\s+', ' ', max(names, key=len)).strip(), (src['mfr'] or '').strip()[:20], w, prices, promos])
    return items


def main():
    P, R, report = {}, {}, {}
    for sid, kind, p, meta in STORES:
        print('fetching', sid, '...', flush=True)
        try:
            try:
                files = globals()['fetch_' + kind](p)
            except Exception as e:  # one retry for chains that usually work from abroad
                if kind in ('carrefour', 'laib', 'hazi'):
                    raise
                print('  retrying', sid, 'after', type(e).__name__, flush=True)
                files = globals()['fetch_' + kind](p)
            if 'price' not in files:
                raise RuntimeError('no price file')
            P[sid] = parse_prices(files['price'])
            R[sid] = parse_promos(files['promo']) if 'promo' in files else {}
            report[sid] = f'{len(P[sid])} items'
            print(' ', sid, report[sid], flush=True)
        except Exception as e:  # keep going with the other chains
            report[sid] = f'error: {type(e).__name__}: {e}'[:200]
            print(' ', sid, report[sid], flush=True)
        if sid not in P:
            d = load_local(sid)
            if d:
                P[sid] = d['P']; R[sid] = {c: [tuple(x) for x in v] for c, v in d['R'].items()}
                report[sid] += f' -> local copy from {d["date"]} ({len(P[sid])} items)'
                print(' ', sid, 'using local copy from', d['date'], flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    meta_of = {sid: dict(meta, id=sid) for sid, kind, p, meta in STORES}
    written = 0
    os.makedirs(OUT, exist_ok=True)
    for region, cfg in REGIONS.items():
        ok = [s for s in cfg['stores'] if s in P]
        if len(ok) < 3:
            print(region, ': too few stores fetched; keeping the previous catalog.')
            continue
        items = build(P, R, ok)
        data = {'region': region, 'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'stores': ok,
                'meta': [meta_of[s] for s in ok], 'areas': cfg['areas'],
                'report': {s: report.get(s, '') for s in cfg['stores']}, 'items': items}
        with open(os.path.join(OUT, cfg['file']), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        written += 1
        print(region, 'items', len(items), 'stores', ok)
    if not written:
        sys.exit(1)


if __name__ == '__main__':
    # python update_prices.py --local CO PriceFull.gz PromoFull.gz
    if len(sys.argv) >= 4 and sys.argv[1] == '--local':
        save_local(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        main()
