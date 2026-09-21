import unittest
from unittest import mock

from alert import jma

AREA = {
    "class10s": {"130010": {"name": "東京地方"}},
    "class20s": {
        "1310100": {"name": "千代田区"},
        "1310200": {"name": "中央区"},
        "1310300": {"name": "港区"},
        "1310400": {"name": "新宿区"},
        "1410100": {"name": "横浜市"},
        "1210100": {"name": "千葉市"},
        "1210200": {"name": "市川市"},
    },
}

OLD = "2026-09-21T01:00:00+09:00"
NEW = "2026-09-21T06:16:00+09:00"


def item(area_code, *kinds):
    """市町村1つ分。kinds は (警報コード, 状態) の組。"""
    return {"areaCode": area_code, "kinds": [{"code": c, "status": s} for c, s in kinds]}


def entry(*items, when=NEW):
    """現象ごとの発表データ1件(新体系JSONのリストの要素)。"""
    return {"reportDatetime": when, "warning": {"class10Items": [], "class20Items": list(items)}}


TOKYO = [
    entry(
        item("1310100", ("43", "発表")),  # レベル4大雨危険警報
        item("1310200", ("03", "継続")),  # レベル3大雨警報(既定では対象外)
        item("1310300", ("43", "解除")),  # 解除(対象外)
        item("1310400", ("10", "継続"), ("04", "発表")),  # 注意報・洪水(対象外)
    )
]
KANAGAWA = [entry(item("1410100", ("33", "継続")))]  # レベル5大雨特別警報
CHIBA = [
    entry(item("1210100", ("43", "発表")), item("1210200", ("00", "発表警報・注意報はなし"))),  # 大雨
    entry(item("1210100", ("49", "継続"))),  # 土砂災害
]
QUIET = [entry(item("1210200", ("00", "発表警報・注意報はなし")))]

NAMES = {k: v["name"] for k, v in AREA["class20s"].items()}


class ParseAlertsTest(unittest.TestCase):
    def test_only_level4_or_higher_are_picked(self):
        alerts = jma.parse_alerts(TOKYO, NAMES, "東京都")
        self.assertEqual([a["name"] for a in alerts], ["千代田区"])
        self.assertEqual(alerts[0]["level"], 4)
        self.assertEqual(alerts[0]["warnings"], ["レベル4大雨危険警報"])

    def test_min_level_can_be_lowered_to_3(self):
        with mock.patch.object(jma, "MIN_LEVEL", 3):
            alerts = jma.parse_alerts(TOKYO, NAMES, "東京都")
        self.assertEqual([a["name"] for a in alerts], ["千代田区", "中央区"])
        self.assertEqual(alerts[1]["level"], 3)

    def test_level5(self):
        alerts = jma.parse_alerts(KANAGAWA, NAMES, "神奈川県")
        self.assertEqual(alerts[0]["level"], 5)
        self.assertEqual(alerts[0]["warnings"], ["レベル5大雨特別警報"])

    def test_rain_and_landslide_entries_are_merged(self):
        alerts = jma.parse_alerts(CHIBA, NAMES, "千葉県")
        self.assertEqual([a["name"] for a in alerts], ["千葉市"])
        self.assertEqual(alerts[0]["warnings"], ["レベル4大雨危険警報", "レベル4土砂災害危険警報"])

    def test_no_warning_status_is_ignored(self):
        self.assertEqual(jma.parse_alerts(QUIET, NAMES, "千葉県"), [])

    def test_downgrade_from_special_to_danger_is_still_active(self):
        data = [entry(item("1", ("43", "特別警報から危険警報")))]
        self.assertEqual(jma.parse_alerts(data, {}, "東京都")[0]["level"], 4)

    def test_newer_entry_wins_whatever_the_list_order(self):
        issued_then_lifted = [
            entry(item("1", ("43", "発表")), when=OLD),
            entry(item("1", ("43", "解除")), when=NEW),
        ]
        self.assertEqual(jma.parse_alerts(issued_then_lifted, {}, "東京都"), [])
        self.assertEqual(jma.parse_alerts(issued_then_lifted[::-1], {}, "東京都"), [])

        lifted_then_reissued = [
            entry(item("1", ("43", "解除")), when=OLD),
            entry(item("1", ("43", "発表")), when=NEW),
        ]
        self.assertEqual(len(jma.parse_alerts(lifted_then_reissued, {}, "東京都")), 1)
        self.assertEqual(len(jma.parse_alerts(lifted_then_reissued[::-1], {}, "東京都")), 1)

    def test_highest_level_wins(self):
        data = [entry(item("1", ("43", "発表"), ("39", "発表")))]
        alerts = jma.parse_alerts(data, {}, "東京都")
        self.assertEqual(alerts[0]["level"], 5)
        self.assertEqual(alerts[0]["warnings"][0], "レベル5土砂災害特別警報")

    def test_unknown_area_code_is_not_dropped(self):
        alerts = jma.parse_alerts(KANAGAWA, {}, "神奈川県")
        self.assertEqual(alerts[0]["name"], "1410100")

    def test_empty_report(self):
        self.assertEqual(jma.parse_alerts([], {}, "東京都"), [])


class GetAlertsTest(unittest.TestCase):
    def setUp(self):
        jma._cache.clear()

    def fake(self, broken=(), reports=None):
        reports = reports or {"130000": TOKYO, "140000": KANAGAWA, "120000": CHIBA}

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

    def test_uses_r8_url(self):
        self.assertIn("/data/r8/", jma.WARNING_URL)

    def test_highest_level_sets_status_and_sorts_first(self):
        with mock.patch.object(jma, "_get_json", self.fake()):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "level5")
        self.assertEqual([a["name"] for a in data["alerts"]], ["横浜市", "千代田区", "千葉市"])
        self.assertEqual(data["failed"], [])
        self.assertEqual(data["updated"], "2026年9月21日 06:16")
        self.assertEqual(data["min_level"], 4)
        self.assertEqual((data["alerts"][0]["lat"], data["alerts"][0]["lon"]), (35.68, 139.75))

    def test_chiba_level4_only_gives_level4_status(self):
        reports = {"130000": QUIET, "140000": QUIET, "120000": CHIBA}
        with mock.patch.object(jma, "_get_json", self.fake(reports=reports)):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "level4")
        self.assertEqual([a["prefecture"] for a in data["alerts"]], ["千葉県"])

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
        self.assertEqual(data["status"], "level4")

    def test_no_alerts_and_fetch_failure_is_unknown_not_clear(self):
        quiet = {"130000": QUIET, "140000": QUIET, "120000": QUIET}
        with mock.patch.object(jma, "_get_json", self.fake(broken=("130000",), reports=quiet)):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "unknown")

    def test_unrecognized_json_format_is_unknown_not_clear(self):
        old_style = {"reportDatetime": NEW, "areaTypes": [{"areas": []}, {"areas": []}]}
        reports = {"130000": old_style, "140000": [{"foo": 1}], "120000": [{"foo": 1}]}
        with mock.patch.object(jma, "_get_json", self.fake(reports=reports)):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "unknown")
        self.assertEqual(data["failed"], ["東京都", "神奈川県", "千葉県"])

    def test_empty_list_means_no_warnings(self):
        reports = {"130000": [], "140000": [], "120000": []}
        with mock.patch.object(jma, "_get_json", self.fake(reports=reports)):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "clear")
        self.assertEqual(data["alerts"], [])

    def test_no_alerts_is_clear(self):
        quiet = {"130000": QUIET, "140000": QUIET, "120000": QUIET}
        with mock.patch.object(jma, "_get_json", self.fake(reports=quiet)):
            data = jma.get_alerts()
        self.assertEqual(data["status"], "clear")


if __name__ == "__main__":
    unittest.main()
