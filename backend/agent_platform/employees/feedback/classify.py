"""理由分类：一次 codex 调用给一批评论选移除理由。

页面点击是脚本，语义判断交给 codex；返回的键必须是 REASON_CHOICES 之一。
"""
import json

REASON_CHOICES = {
    "product_review": "商品反馈",
    "fba_delivery": "配送相关反馈",
    "obscene": "不当反馈",
    "pii": "不当反馈",
}

PROMPT = """你是亚马逊差评移除助手。根据每条评价的内容，从下面四个理由里选一个最合适的：
- 不当反馈：评价包含淫秽语言、卖家个人识别信息等不当内容
- 商品反馈：整条评价都在讲商品本身（质量、描述不符、尺码、材质）
- 配送相关反馈：评价在讲配送、物流、客服（晚到、没收到、包装破损）
- 我的原因并未被列出：不属于以上任何一类

只输出 JSON 数组，不要输出其他内容。每条格式：
{{"case_id": <编号>, "reason": "product_review|fba_delivery|obscene|pii", "confidence": <0到1>}}
拿不准就把 confidence 写低。评价列表（编号 | 星级 | 内容）：
{lines}
"""


def _parse(text):
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return {}
    try:
        rows = json.loads(text[start:end + 1])
    except Exception:
        return {}
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            case_id = int(row.get("case_id"))
        except (TypeError, ValueError):
            continue
        reason = str(row.get("reason") or "")
        if reason in REASON_CHOICES:
            result[case_id] = {"reason": reason,
                               "confidence": float(row.get("confidence") or 0)}
    return result


async def classify(ctx, cases):
    """返回 {case_id: {"reason": 键, "confidence": 0-1}}；失败返回空。"""
    lines = "\n".join(f"{case['id']} | {case['rating']}星 | {(case.get('comment') or '')[:400]}"
                      for case in cases)
    try:
        result = await ctx.tool("codex", prompt=PROMPT.format(lines=lines))
    except Exception:
        return {}
    return _parse(str(result.get("stdout") or ""))
