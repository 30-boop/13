"""気象庁の防災情報から、東京・神奈川・千葉の大雨・土砂災害の警報を取得する。

2026年5月28日から気象庁の防災情報は「警戒レベル」の新体系になりました。
  レベル3 大雨警報 / レベル4 大雨危険警報 / レベル5 大雨特別警報
  レベル3 土砂災害警報 / レベル4 土砂災害危険警報 / レベル5 土砂災害特別警報
このモジュールは新体系のJSONを読み、MIN_LEVEL 以上のものだけを取り出します。

使うデータ(いずれも無料・APIキー不要)
- 警報の発表状況  : 気象庁 防災情報 警報JSON(令和8年体系, 府県予報区ごと)
- 市町村コードと名前: 気象庁 area.json
- 市町村の位置    : 国土地理院 住所検索API
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# 何レベル以上を表示するか。3にするとレベル3(大雨警報・土砂災害警報)も表示する。
MIN_LEVEL = 4

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

WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/r8/{}.json"
AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q={}"

# 対象にする警報コード → (名前, 警戒レベル)
# 高潮(38, 48)や暴風などを加えたいときは、ここに足す。
RAIN_WARNINGS = {
    "03": ("レベル3大雨警報", 3),
    "43": ("レベル4大雨危険警報", 4),
    "33": ("レベル5大雨特別警報", 5),
    "09": ("レベル3土砂災害警報", 3),
    "49": ("レベル4土砂災害危険警報", 4),
    "39": ("レベル5土砂災害特別警報", 5),
}
# 発表中でない状態。
# 「特別警報から危険警報」のような切り替えは、切り替え後のレベルで発表中として扱う。
INACTIVE_STATUSES = {"解除", "発表警報・注意報はなし"}

JST = timezone(timedelta(hours=9))

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


def _parse_time(text):
    """ISO形式の時刻を日本時間の datetime にする。読めなければ None。"""
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=JST)
    return moment.astimezone(JST)


def _class20_items(entry):
    """1件の発表データから、市町村等ごとの警報一覧(class20Items)を返す。

    形式が想定と違う(warning が無い)ときは None。
    """
    warning = entry.get("warning") if isinstance(entry, dict) else None
    if not isinstance(warning, dict):
        return None
    return warning.get("class20Items") or []


def _fetch_report(office):
    """府県の警報JSONを取得する。想定外の形式なら例外にする(=取得失敗として扱う)。

    「警報なし」と「形式が変わって読めていない」を取り違えないための確認。
    """
    report = _get_json(WARNING_URL.format(office))
    if not isinstance(report, list):
        raise ValueError("unexpected warning JSON format")
    if report and all(_class20_items(entry) is None for entry in report):
        raise ValueError("unexpected warning JSON format")
    return report


def parse_alerts(report, names, prefecture):
    """警報JSONから、MIN_LEVEL 以上の警報が発表中の市町村を取り出す。

    新体系のJSONは、現象ごと(大雨・土砂災害など)の発表データが並んだリスト。
      [ {"reportDatetime": ..., "warning": {"class20Items": [
            {"areaCode": "1210100", "kinds": [{"code": "43", "status": "発表"}]} ]}}, ... ]
    同じ市町村・同じ警報コードが複数の発表データに出てきたら、新しい発表時刻のものを採用する。
    """
    states = {}  # (市町村コード, 警報コード) -> (発表時刻, 状態)
    for entry in report:
        items = _class20_items(entry)
        if items is None:
            continue
        when = _parse_time(entry.get("reportDatetime"))
        stamp = when.timestamp() if when else 0.0
        for item in items:
            for kind in item.get("kinds") or []:
                code = kind.get("code")
                if code not in RAIN_WARNINGS:
                    continue
                key = (item.get("areaCode", ""), code)
                if key not in states or stamp >= states[key][0]:
                    states[key] = (stamp, kind.get("status"))

    by_area = {}
    for (area_code, code), (_, status) in states.items():
        name, level = RAIN_WARNINGS[code]
        if level >= MIN_LEVEL and status not in INACTIVE_STATUSES:
            by_area.setdefault(area_code, []).append((level, code, name))

    alerts = []
    for area_code, kinds in by_area.items():
        kinds.sort(key=lambda k: (-k[0], k[1]))  # レベルの高い順
        alerts.append(
            {
                "code": area_code,
                "name": names.get(area_code, area_code),
                "prefecture": prefecture,
                "warnings": [name for _, _, name in kinds],
                "level": kinds[0][0],
            }
        )
    return alerts


def _format_time(moment):
    return f"{moment.year}年{moment.month}月{moment.day}日 {moment.hour:02d}:{moment.minute:02d}"


def get_alerts():
    """画面に必要な情報をまとめて返す。

    status: level5 / level4 / level3(発表中の最高レベル)
            clear(該当なし) / unknown(取得失敗で判断不能)
    """
    try:
        names = _area_names()
    except Exception:
        names = {}  # 名前が取れなくても、警報自体は市町村コードで表示する

    alerts, failed, times = [], [], []
    for office, prefecture in OFFICES.items():
        try:
            report = _cached("warn:" + office, WARNING_TTL, lambda o=office: _fetch_report(o))
        except Exception:
            failed.append(prefecture)
            continue

        for entry in report:
            moment = _parse_time(entry.get("reportDatetime")) if isinstance(entry, dict) else None
            if moment:
                times.append(moment)

        for alert in parse_alerts(report, names, prefecture):
            alert["lat"], alert["lon"] = locate(prefecture, alert["name"])
            alerts.append(alert)

    order = {prefecture: i for i, prefecture in enumerate(OFFICES.values())}
    alerts.sort(key=lambda a: (-a["level"], order[a["prefecture"]], a["code"]))

    if alerts:
        status = f"level{alerts[0]['level']}"
    elif failed:
        status = "unknown"  # 取得に失敗した状態で「警報なし」とは表示しない
    else:
        status = "clear"

    return {
        "status": status,
        "alerts": alerts,
        "failed": failed,
        "updated": _format_time(max(times)) if times else None,
        "min_level": MIN_LEVEL,
    }
