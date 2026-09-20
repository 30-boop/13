from unittest import mock

from django.test import SimpleTestCase

WARNING = {
    "status": "warning",
    "alerts": [
        {
            "code": "1310100",
            "name": "千代田区",
            "prefecture": "東京都",
            "warnings": ["大雨警報"],
            "level": "warning",
            "lat": 35.69,
            "lon": 139.75,
        }
    ],
    "failed": [],
    "updated": "2026年9月20日 10:05",
}
CLEAR = {"status": "clear", "alerts": [], "failed": [], "updated": "2026年9月20日 10:05"}


class IndexViewTest(SimpleTestCase):
    def get(self, data):
        with mock.patch("alert.jma.get_alerts", return_value=dict(data)):
            return self.client.get("/")

    def test_warning_shows_banner_area_and_evacuation(self):
        res = self.get(WARNING)
        self.assertContains(res, "大雨警報が発表されています")
        self.assertContains(res, "東京都千代田区")
        self.assertContains(res, "ブレーカー")
        self.assertContains(res, "高台")

    def test_clear_shows_no_evacuation(self):
        res = self.get(CLEAR)
        self.assertContains(res, "大雨警報は発表されていません")
        self.assertNotContains(res, "避難のために")

    def test_unknown_is_not_shown_as_clear(self):
        res = self.get({"status": "unknown", "alerts": [], "failed": ["千葉県"], "updated": None})
        self.assertContains(res, "警報情報を取得できませんでした")
        self.assertNotContains(res, "大雨警報は発表されていません")
