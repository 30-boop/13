"""気象庁の防災情報から、東京・神奈川・千葉の大雨警報を取得する。

使うデータ(いずれも無料・APIキー不要)
- 警報の発表状況  : 気象庁 防災情報 警報JSON(府県予報区ごと)
- 市町村コードと名前: 気象庁 area.json
- 市町村の位置    : 国土地理院 住所検索API
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

# 府県予報区コード → 都県名(表示順もこの順)
OFFICES = {
    "130000": "東京都",
    "140000": "神奈川県",
    "120000": "千葉県",
}

# 位置を調べられなかったときに使う代替位置(都県庁付近)
FALLBACK_POINTS = {
    "東京都": (35.689, 139.692),
    "神奈川県": (35.448, 139.643),
    "千葉県": (35.605, 140.123),
}

WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{}.json"
AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q={}"

# 対象にする警報コード(洪水警報などを加えたいときはここに足す)
RAIN_WARNINGS = {
    "03": "大雨警報",
    "33": "大雨特別警報",
}
# 「解除」や「警報から注意報」に切り替わったものは含めない
ACTIVE_STATUSES = {"発表", "継続"}

WARNING_TTL = 180  # 警報JSONは3分間キャッシュ
AREA_TTL = 24 * 60 * 60
FOREVER = float("inf")

_cache = {}


def _cached(key, ttl, loader):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()  # 失敗(例外)はキャッシュしない
    _cache[key] = (now, value)
    return value


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "rainfall-alert-app/1.0"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8"))


def _area_names():
    def load():
        data = _get_json(AREA_URL)
        names = {}
        for level in ("class10s", "class15s", "class20s"):
            for code, info in data.get(level, {}).items():
                names[code] = info.get("name", code)
        return names

    return _cached("area", AREA_TTL, load)


def _geocode(query):
    results = _get_json(GEOCODE_URL.format(urllib.parse.quote(query)))
    if not results:
        return None
    lon, lat = results[0]["geometry"]["coordinates"]
    return (lat, lon)


def locate(prefecture, name):
    """市町村の位置(緯度, 経度)を返す。調べられなければ都県庁付近。"""
    query = prefecture + name
    try:
        point = _cached("geo:" + query, FOREVER, lambda: _geocode(query))
    except Exception:
        point = None
    return point or FALLBACK_POINTS[prefecture]


def parse_alerts(report, names, prefecture):
    """警報JSONから、大雨(特別)警報が発表中の市町村を取り出す。

    areaTypes の最後の要素が市町村等(最も細かい区分)。
    """
    area_types = report.get("areaTypes") or []
    if not area_types:
        return []

    alerts = []
    for area in area_types[-1].get("areas", []):
        kinds = {
            RAIN_WARNINGS[w["code"]]
            for w in area.get("warnings", [])
            if w.get("code") in RAIN_WARNINGS and w.get("status") in ACTIVE_STATUSES
        }
        if not kinds:
            continue
        code = area.get("code", "")
        alerts.append(
            {
                "code": code,
                "name": names.get(code, code),
                "prefecture": prefecture,
                "warnings": sorted(kinds),
                "level": "special" if "大雨特別警報" in kinds else "warning",
            }
        )
    return alerts


def _format_time(moment):
    return f"{moment.year}年{moment.month}月{moment.day}日 {moment.hour:02d}:{moment.minute:02d}"


def get_alerts():
    """画面に必要な情報をまとめて返す。

    status: special(特別警報) / warning(警報) / clear(なし) / unknown(取得失敗で判断不能)
    """
    try:
        names = _area_names()
    except Exception:
        names = {}  # 名前が取れなくても、警報自体は市町村コードで表示する

    alerts, failed, times = [], [], []
    for office, prefecture in OFFICES.items():
        try:
            report = _cached(
                "warn:" + office,
                WARNING_TTL,
                lambda o=office: _get_json(WARNING_URL.format(o)),
            )
        except Exception:
            failed.append(prefecture)
            continue

        try:
            times.append(datetime.fromisoformat(report["reportDatetime"]))
        except (KeyError, TypeError, ValueError):
            pass

        for alert in parse_alerts(report, names, prefecture):
            alert["lat"], alert["lon"] = locate(prefecture, alert["name"])
            alerts.append(alert)

    order = {prefecture: i for i, prefecture in enumerate(OFFICES.values())}
    alerts.sort(key=lambda a: (a["level"] != "special", order[a["prefecture"]], a["code"]))

    if any(a["level"] == "special" for a in alerts):
        status = "special"
    elif alerts:
        status = "warning"
    elif failed:
        status = "unknown"  # 取得に失敗した状態で「警報なし」とは表示しない
    else:
        status = "clear"

    return {
        "status": status,
        "alerts": alerts,
        "failed": failed,
        "updated": _format_time(max(times)) if times else None,
    }
