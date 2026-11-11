"""店铺与站点映射：ERP 的 sid / marketplaceId → 紫鸟账号与 Seller Central 地址。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BINDINGS = ROOT / "deploy" / "store-bindings.json"

# 站点 → Seller Central 地址；ERP 只给 marketplaceId。
MARKETS = {
    "ATVPDKIKX0DER": "sellercentral.amazon.com",
    "A2EUQ1WTGCTBG2": "sellercentral.amazon.ca",
    "A1AM78C64UM0Y8": "sellercentral.amazon.com.mx",
    "A1F83G8C2ARO7P": "sellercentral.amazon.co.uk",
    "A1PA6795UKMFR9": "sellercentral.amazon.de",
    "A13V1IB3VIYZZH": "sellercentral.amazon.fr",
    "APJ6JRA9NG5V4": "sellercentral.amazon.it",
    "A1RKKUPIHCS9HS": "sellercentral.amazon.es",
    "A1805IZSGTT6HS": "sellercentral.amazon.nl",
    "A2NODRKZP88ZB9": "sellercentral.amazon.se",
    "A1C3SOZRARQ6R3": "sellercentral.amazon.pl",
    "AMEN7PMS3EDWL": "sellercentral.amazon.com.be",
    "A33AVAJ2PDY3EV": "sellercentral.amazon.com.tr",
    "A2Q3Y263D00KWC": "sellercentral.amazon.com",
    "A1VC38T7YXB528": "sellercentral.amazon.co.jp",
    "A28R8C7NBKEWEA": "sellercentral.amazon.ie",
    "A17E79C6D8DWNP": "sellercentral.amazon.sa",
    "A2VIGQ35RCS4UG": "sellercentral.amazon.ae",
}

REQUEST_LABELS = ("request review", "request removal", "请求审核", "要求审核",
                  "申请审核", "申請審査", "レビューの削除をリクエスト")

MARKET_CODES = {
    "ATVPDKIKX0DER": "US", "A2EUQ1WTGCTBG2": "CA", "A1AM78C64UM0Y8": "MX",
    "A1F83G8C2ARO7P": "UK", "A1PA6795UKMFR9": "DE", "A13V1IB3VIYZZH": "FR",
    "APJ6JRA9NG5V4": "IT", "A1RKKUPIHCS9HS": "ES", "A1805IZSGTT6HS": "NL",
    "A2NODRKZP88ZB9": "SE", "A1C3SOZRARQ6R3": "PL", "AMEN7PMS3EDWL": "BE",
    "A33AVAJ2PDY3EV": "TR", "A2Q3Y263D00KWC": "BR", "A1VC38T7YXB528": "JP",
    "A28R8C7NBKEWEA": "IE", "A17E79C6D8DWNP": "SA", "A2VIGQ35RCS4UG": "AE",
}
CODE_HOSTS = {code: MARKETS[mid] for mid, code in MARKET_CODES.items()}

# 页面头部国家标签 → 站点代码；中英文都认。
NAME_CODES = {
    "美国": "US", "united states": "US", "加拿大": "CA", "canada": "CA",
    "墨西哥": "MX", "mexico": "MX", "英国": "UK", "united kingdom": "UK", "great britain": "UK",
    "德国": "DE", "germany": "DE", "法国": "FR", "france": "FR", "意大利": "IT", "italy": "IT",
    "西班牙": "ES", "spain": "ES", "荷兰": "NL", "netherlands": "NL", "瑞典": "SE", "sweden": "SE",
    "波兰": "PL", "poland": "PL", "比利时": "BE", "belgium": "BE", "土耳其": "TR", "turkey": "TR",
    "巴西": "BR", "brazil": "BR", "日本": "JP", "japan": "JP", "爱尔兰": "IE", "ireland": "IE",
    "沙特阿拉伯": "SA", "saudi arabia": "SA", "阿拉伯联合酋长国": "AE", "united arab emirates": "AE",
}


def code_for_country(text):
    return NAME_CODES.get(str(text or "").strip().lower())


def load_bindings():
    if not BINDINGS.is_file():
        return {}
    return {str(row["sid"]): row for row in json.loads(BINDINGS.read_text(encoding="utf-8"))}


def url_for(marketplace_id):
    host = MARKETS.get(str(marketplace_id))
    return f"https://{host}/feedback-manager/index.html#/" if host else None
