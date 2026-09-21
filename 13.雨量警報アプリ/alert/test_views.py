from unittest import mock

from django.test import SimpleTestCase

LEVEL4 = {
    "status": "level4",
    "alerts": [
        {
            "code": "1210100",
            "name": "千葉市",
            "prefecture": "千葉県",
            "warnings": ["レベル4大雨危険警報", "レベル4土砂災害危険警報"],
            "level": 4,
            "lat": 35.61,
            "lon": 140.12,
        }
    ],
    "failed": [],
    "updated": "2026年9月21日 06:16",
    "min_level": 4,
}
CLEAR = {"status": "clear", "alerts": [], "failed": [], "updated": "2026年9月21日 06:16", "min_level": 4}


class IndexViewTest(SimpleTestCase):
    def get(self, data):
        with mock.patch("alert.jma.get_alerts", return_value=dict(data)):
            return self.client.get("/")

    def test_level4_shows_banner_area_and_evacuation(self):
        res = self.get(LEVEL4)
        self.assertContains(res, "レベル4 危険警報が発表されています")
        self.assertContains(res, "千葉県千葉市")
        self.assertContains(res, "レベル4土砂災害危険警報")
        self.assertContains(res, "ブレーカー")
        self.assertContains(res, "高台")

    def test_level5_banner(self):
        res = self.get(dict(LEVEL4, status="level5"))
        self.assertContains(res, "レベル5 特別警報が発表されています")
        self.assertContains(res, "命の危険")

    def test_clear_shows_no_evacuation(self):
        res = self.get(CLEAR)
        self.assertContains(res, "レベル4以上の警報は発表されていません")
        self.assertNotContains(res, "避難のために")

    def test_unknown_is_not_shown_as_clear(self):
        res = self.get(
            {"status": "unknown", "alerts": [], "failed": ["千葉県"], "updated": None, "min_level": 4}
        )
        self.assertContains(res, "警報情報を取得できませんでした")
        self.assertNotContains(res, "警報は発表されていません")
