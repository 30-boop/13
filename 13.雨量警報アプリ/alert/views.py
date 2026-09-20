from django.shortcuts import render

from . import jma

# 警報の種類ごとの導入文(警報が出ていないときは避難メッセージを表示しない)
EVACUATION_LEAD = {
    "special": "重大な災害が起こるおそれが著しく大きい状況です。直ちに命を守る行動を取ってください。",
    "warning": "重大な災害が起こるおそれがあります。早めに避難の準備をしてください。",
}

EVACUATION_ITEMS = [
    (
        "高台や建物の上階へ避難する",
        "浸水のおそれがあるときは高台へ。屋外の移動が危険なときは、近くの頑丈な建物の2階以上へ。"
        "土砂災害のおそれがあるときは、崖や斜面から離れた場所へ。",
    ),
    (
        "避難する前にブレーカーを落とす",
        "電気による火災や感電を防ぐため、ブレーカーを切り、ガスの元栓を閉めます。",
    ),
    (
        "川・用水路・海岸・崖に近づかない",
        "様子を見に行かないでください。地下道や地下室にも入らないでください。",
    ),
    (
        "冠水した道路を歩いたり、車で通ったりしない",
        "水深が浅くても、マンホールや側溝のふたが外れていることがあります。",
    ),
    (
        "自治体の避難情報を確認する",
        "お住まいの市区町村の避難情報とハザードマップを確認し、避難先と経路を決めます。",
    ),
]


def index(request):
    context = jma.get_alerts()
    lead = EVACUATION_LEAD.get(context["status"])
    context["lead"] = lead
    context["items"] = EVACUATION_ITEMS if lead else []
    return render(request, "alert/index.html", context)
