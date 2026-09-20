import unittest
from unittest import mock

from alert import jma

AREA = {
    "class10s": {"130010": {"name": "東京地方"}},
    "class20s": {
        "1310100": {"name": "千代田区"},
        "1310200": {"name": "中央区"},
        "1310300": {"name": "港区"},
        "1410100": {"name": "横浜市"},
        "1210100": {"name": "千葉市"},
    },
}


def report(areas, when="2026-09-20T10:05:00+09:00"):
    """警報JSONの形(一次細分区域 + 市町村等)を作る。"""
    return {
        "reportDatetime": when,
        "areaTypes": [
            {"areas": [{"code": "130010", "warnings": [{"code": "03", "status": "発表"}]}]},
            {"areas": areas},
        ],
    }


TOKYO = report(
    [
        {"code": "1310100", "warnings": [{"code": "03", "status": "発表"}]},  # 大雨警報
        {"code": "1310200", "warnings": [{"code": "10", "status": "継続"}]},  # 大雨注意報(対象外)
        {"code": "1310300", "warnings": [{"code": "03", "status": "解除"}]},  # 解除(対象外)
    ]
)
KANAGAWA = report([{"code": "1410100", "warnings": [{"code": "33", "status": "継続"}]}])  # 特別警報
CHIBA = report([{"code": "1210100", "warnings": []}])


class ParseAlertsTest(unittest.TestCase):
    def test_only_active_rain_warnings_are_picked(self):
        names = {k: v["name"] for k, v in AREA["class20s"].items()}
        alerts = jma.parse_alerts(TOKYO, names, "東京都")
        self.assertEqual([a["name"] for a in alerts], ["千代田区"])
        self.assertEqual(alerts[0]["level"], "warning")
        self.assertEqual(alerts[0]["warnings"], ["大雨警報"])

    def test_special_warning_level(self):
        alerts = jma.parse_alerts(KANAGAWA, {"1410100": "横浜市"}, "神奈川県")
        self.assertEqual(alerts[0]["level"], "special")

    def test_unknown_code_is_not_dropped(self):
        alerts = jma.parse_alerts(KANAGAWA, {}, "神奈川県")
        self.assertEqual(alerts[0]["name"], "1410100")

    def test_downgraded_and_flood_are_excluded(self):
        data = report(
            [
                {"code": "1", "warnings": [{"code": "03", "status": "警報から注意報"}]},
                {"code": "2", "warnings": [{"code": "04", "status": "発表"}]},  # 洪水警報
            ]
        )
        self.assertEqual(jma.parse_alerts(data, {}, "東京都"), [])

    def test_empty_report(self):
        self.assertEqual(jma.parse_alerts({}, {}, "東京都"), [])


class GetAlertsTest(unittest.TestCase):
    def setUp(self):
        jma._cache.clear()

    def fake(self, broken=()):
        reports = {"130000": TOKYO, "140000": KANAGAWA, "120000": CHIBA}

        def get_json(url):
            if url == jma.AREA_URL:
                return AREA
            if url.startswith("https://msearch.gsi.go.jp"):
                return [{"geometry": {"coordinates": [139.75, 35.68]}}]
            for code, data in reports.items():
                if url == jma.WARNING_URL.format(code):
                    if code in broken:
                        raise OSError("network down")
                    return data
            raise AssertionError(url)

        return get_json

    def test_special_takes_precedence_and_sorts_first(self):
        with mock.patch.object(jma, "_get_json", self.fake()):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "special")
        self.assertEqual([a["name"] for a in data["alerts"]], ["横浜市", "千代田区"])
        self.assertEqual(data["failed"], [])
        self.assertEqual(data["updated"], "2026年9月20日 10:05")
        self.assertEqual((data["alerts"][0]["lat"], data["alerts"][0]["lon"]), (35.68, 139.75))

    def test_geocode_failure_uses_fallback_point(self):
        def get_json(url):
            if url.startswith("https://msearch.gsi.go.jp"):
                raise OSError
            return self.fake()(url)

        with mock.patch.object(jma, "_get_json", get_json):
            data = jma.get_alerts()
        kanagawa = next(a for a in data["alerts"] if a["prefecture"] == "神奈川県")
        self.assertEqual((kanagawa["lat"], kanagawa["lon"]), jma.FALLBACK_POINTS["神奈川県"])

    def test_failed_prefecture_is_reported_and_alerts_still_shown(self):
        with mock.patch.object(jma, "_get_json", self.fake(broken=("140000",))):
            data = jma.get_alerts()
        self.assertEqual(data["failed"], ["神奈川県"])
        self.assertEqual(data["status"], "warning")

    def test_no_alerts_and_fetch_failure_is_unknown_not_clear(self):
        with mock.patch.object(jma, "_get_json", self.fake(broken=("130000", "140000"))):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "unknown")

    def test_no_alerts_is_clear(self):
        quiet = {"130000": CHIBA, "140000": CHIBA, "120000": CHIBA}

        def get_json(url):
            if url == jma.AREA_URL:
                return AREA
            for code, data in quiet.items():
                if url == jma.WARNING_URL.format(code):
                    return data
            raise AssertionError(url)

        with mock.patch.object(jma, "_get_json", get_json):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "clear")
        self.assertEqual(data["alerts"], [])


if __name__ == "__main__":
    unittest.main()
