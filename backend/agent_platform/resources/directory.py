"""店铺目录：业务只提交店铺 sid，由这里解析成紫鸟账号。

数据来自两张表：
- store_mapping：紫鸟账号 ↔ 领星店铺（sid、店铺名、站点），由 ERP 映射表导入；
- amazon_store：智易飞亚马逊店铺目录（负数 sid、店铺名、站点、商户、市场）。
正数 sid 直接查映射；负数 sid 先经亚马逊目录拿到店铺名，再回映射表找账号。
业务模块不读部署文件，也不直接查这两张表。
"""
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _mapping_rows(store, sid):
    rows = store.all("SELECT browser_id, account_name, site_region_code FROM store_mapping "
                     "WHERE sid=?", (str(sid),))
    if not rows:
        rows = store.all("SELECT browser_id, account_name, site_region_code FROM store_mapping "
                         "WHERE store_id=?", (str(sid),))
    return rows


def _by_positive(store, sid):
    return {str(row["browser_id"]) for row in _mapping_rows(store, sid) if row.get("browser_id")}


def _in_account(store, browser_id):
    return bool(store.one("SELECT 1 FROM store_info WHERE shop_id=?", (str(browser_id),)))


REGION_SUFFIX = {"CA": "-us", "US": "-us", "MX": "-us", "UK": "-uk", "DE": "-de",
                 "FR": "-fr", "IT": "-it", "ES": "-es", "NL": "-nl", "SE": "-se"}


def _by_prefix(store, name, region=""):
    """映射账号名的字母前缀匹配紫鸟店铺名：'YIHANG主账号' 对上 'yihang子账号-US'。

    多个店铺共用同一前缀时，按映射里的站点区域优先选同名区域的账号（北美→-US）。
    """
    text = str(name or "").strip()
    match = re.match(r"[A-Za-z0-9]+", text)
    prefix = (match.group(0) if match else "").lower()
    if not prefix:
        return set()
    rows = store.all("SELECT shop_id, name FROM store_info WHERE lower(name) LIKE ?",
                     (prefix + "%",))
    shops = {str(row["shop_id"]): str(row["name"] or "").lower() for row in rows}
    if len(shops) > 1 and region:
        want = REGION_SUFFIX.get(str(region).upper(), "")
        preferred = {sid for sid, name_text in shops.items() if want and name_text.endswith(want)}
        if preferred:
            return preferred
    return set(shops)


def _by_negative(store, sid):
    row = store.one("SELECT seller_name, marketplace FROM amazon_store WHERE sid=?", (str(sid),))
    if not row or not row["seller_name"]:
        return set()
    rows = store.all(
        "SELECT browser_id FROM store_mapping WHERE lingxing_store_name=? AND site_region_name=?",
        (row["seller_name"], row["marketplace"] or ""))
    if not rows:
        rows = store.all("SELECT browser_id FROM store_mapping WHERE lingxing_store_name=?",
                         (row["seller_name"],))
    return {str(item["browser_id"]) for item in rows if item.get("browser_id")}


def account_for(store, sid):
    """sid → 紫鸟账号；正数查映射表，负数经亚马逊店铺名回映射表。

    映射里的紫鸟账号已不在当前店铺列表（店铺重建或换了账号）时，
    按映射账号名的前缀匹配现有紫鸟店铺，避免过期映射把任务卡死。
    """
    text = str(sid).strip()
    rows = _mapping_rows(store, text)
    accounts = {str(row["browser_id"]) for row in rows if row.get("browser_id")}
    if not accounts and text.startswith("-"):
        accounts = _by_negative(store, text)
        rows = []
    if accounts and not any(_in_account(store, account) for account in accounts):
        matched = set()
        for row in rows:
            matched |= _by_prefix(store, row.get("account_name"),
                                  row.get("site_region_code") or "")
        if len(matched) == 1:
            return matched.pop()
        if len(matched) > 1:
            raise ValueError(f"店铺 sid={sid} 的账号前缀匹配到多个紫鸟店铺：{sorted(matched)}")
    if len(accounts) == 1:
        return accounts.pop()
    if len(accounts) > 1:
        raise ValueError(f"店铺 sid={sid} 对应多个紫鸟账号，需先核对映射表")
    raise ValueError(f"店铺 sid={sid} 没有绑定紫鸟账号")


def refresh_amazon_stores(store, erp):
    """从智易飞刷新亚马逊店铺目录；结构异常时保留旧数据并抛错。"""
    body = erp.api("GET", "/api/open/amazon/erp-ads/store/auth/enabled-stores").get("body")
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("智易飞店铺授权目录为空或结构异常")
    now = time.time()
    with store.transaction():
        for row in rows:
            if row.get("sid") is None or not row.get("id"):
                continue
            store.execute(
                "INSERT INTO amazon_store (store_id,sid,account_id,seller_name,amazon_seller_id,"
                "marketplace_id,marketplace,currency_code,region,platform,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET "
                "sid=excluded.sid,account_id=excluded.account_id,seller_name=excluded.seller_name,"
                "amazon_seller_id=excluded.amazon_seller_id,marketplace_id=excluded.marketplace_id,"
                "marketplace=excluded.marketplace,currency_code=excluded.currency_code,"
                "region=excluded.region,platform=excluded.platform,updated_at=excluded.updated_at",
                (str(row["id"]), str(row["sid"]), str(row.get("accountId") or ""),
                 str(row.get("sellerName") or ""), str(row.get("amazonSellerId") or ""),
                 str(row.get("marketplaceId") or ""), str(row.get("marketplace") or ""),
                 str(row.get("currencyCode") or ""), str(row.get("region") or ""),
                 str(row.get("platform") or ""), now))
    return len(rows)
