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


def load_bindings():
    if not BINDINGS.is_file():
        return {}
    return {str(row["sid"]): row for row in json.loads(BINDINGS.read_text(encoding="utf-8"))}


def url_for(marketplace_id):
    host = MARKETS.get(str(marketplace_id))
    return f"https://{host}/feedback-manager/index.html#/" if host else None
