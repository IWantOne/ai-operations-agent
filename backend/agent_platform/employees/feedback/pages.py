"""Feedback Manager 页面动作：打开、按订单找行、打开操作菜单、截图。

只通过 ctx.tool("browser.*") 操作页面，不判断业务状态，不写数据库。
"""
import json

from .bindings import url_for

ROW_SCRIPT = r"""(()=>{
const order=__ORDER__;
const rows=Array.from(document.querySelectorAll('kat-table-row')).filter(r=>
 Array.from(r.querySelectorAll('kat-link')).some(a=>a.getAttribute('label')===order));
const deep=root=>{const out=[];const walk=r=>{for(const e of r.querySelectorAll('*')){out.push(e);if(e.shadowRoot)walk(e.shadowRoot);}};walk(root);return out;};
return {url:location.href,title:document.title,ready:document.readyState,
 rowCount:document.querySelectorAll('kat-table-row').length,
 rows:rows.map(r=>({text:(r.innerText||'').slice(0,3000),
  ratings:Array.from(r.querySelectorAll('kat-star-rating')).map(e=>e.getAttribute('value')),
  comments:Array.from(r.querySelectorAll('p')).filter(e=>(e.innerText||'').trim()).map(e=>({
   text:(e.innerText||'').slice(0,1000),
   struck:!!e.closest('s,del')||getComputedStyle(e).textDecorationLine.includes('line-through')})),
  caseLinks:Array.from(r.querySelectorAll('a[href],kat-link[href]')).map(e=>({
   text:(e.innerText||e.getAttribute('label')||'').slice(0,200),href:e.getAttribute('href')})),
  actions:deep(r).filter(e=>/BUTTON|DROPDOWN|MENU|OPTION/.test(e.tagName)||['button','menuitem','combobox','option'].includes(e.getAttribute('role'))).map(e=>({
   tag:e.tagName,text:(e.innerText||'').slice(0,200),label:e.getAttribute('label'),
   disabled:!!(e.disabled||e.hasAttribute('disabled'))}))}))};
})()"""

MENU_READ = r"""(()=>{const out=[];const walk=root=>{
for(const e of root.querySelectorAll('*')){
 const text=(e.innerText||'').trim();
 const role=e.getAttribute&&e.getAttribute('role');
 const tag=e.tagName;
 if((tag==='KAT-DROPDOWN-MENU-ITEM'||tag==='KAT-ACTION-MENU-ITEM'||role==='menuitem'||tag==='KAT-OPTION')&&text&&text.length<80){
   out.push({tag,text,role:role||'',disabled:!!(e.disabled||e.hasAttribute('disabled'))});
 }
 if(e.shadowRoot)walk(e.shadowRoot);
}};walk(document);return {url:location.href,title:document.title,text:(document.body?document.body.innerText:'').slice(0,4000),items:out.slice(0,20)};})()"""

NEXT_PAGE = r"""(()=>{
const labels=['next page','next','下一页','下一頁','次へ'];
const walk=root=>{const out=[];const visit=r=>{for(const e of r.querySelectorAll('*')){
 const role=e.getAttribute&&e.getAttribute('role');
 const aria=(e.getAttribute&&(e.getAttribute('aria-label')||''))+' '+(e.getAttribute&&(e.getAttribute('title')||''));
 const text=(e.innerText||'').trim();
 const button=/^(BUTTON|A)$/.test(e.tagName)||role==='button'||role==='link';
 if(button&&((aria&&labels.some(l=>aria.toLowerCase().includes(l)))||(text&&labels.some(l=>text.toLowerCase()===l)))) out.push(e);
 if(e.shadowRoot)visit(e.shadowRoot);
}};visit(root);return out;};
const buttons=walk(document).filter(e=>!(e.disabled||e.hasAttribute('disabled')));
if(!buttons.length)return JSON.stringify({clicked:false,found:walk(document).length});
const button=buttons[buttons.length-1];
for(const type of ['pointerover','pointerdown','mousedown','pointerup','mouseup','click']){
 button.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,composed:true,view:window}));
}
return JSON.stringify({clicked:true});})()"""


def page_kind(state):
    """页面类型：login / feedback / other。"""
    url = str(state.get("url") or "").lower()
    if "/ap/signin" in url or "signin" in url or "/ap/register" in url:
        return "login"
    if "feedback-manager" in url:
        return "feedback"
    return "other"


async def open(ctx, shop, marketplace_id):
    """打开反馈管理器；没有对应站点时抛出可读原因。"""
    url = url_for(marketplace_id)
    if not url:
        raise ValueError(f"站点 {marketplace_id} 没有对应的 Seller Central 地址")
    await ctx.tool("browser.goto", shop=shop, url=url)


async def read_row(ctx, shop, order_id):
    return await ctx.tool("browser.evaluate", shop=shop,
                          expression=ROW_SCRIPT.replace("__ORDER__", json.dumps(order_id)))


async def find_order(ctx, shop, order_id, max_pages=5):
    """按订单找行；当前页没有就翻页，返回 (最后一次页面状态, 翻过的页)。"""
    state = await read_row(ctx, shop, order_id)
    trail = []
    for _ in range(max_pages):
        trail.append({"url": state.get("url"), "rows": state.get("rowCount"),
                      "kind": page_kind(state)})
        if state.get("rows") or page_kind(state) != "feedback":
            return state, trail
        moved = await ctx.tool("browser.evaluate", shop=shop, expression=NEXT_PAGE)
        try:
            clicked = json.loads(moved).get("clicked") if isinstance(moved, str) else False
        except ValueError:
            clicked = False
        if not clicked:
            return state, trail
        await ctx.sleep(2)
        state = await read_row(ctx, shop, order_id)
    return state, trail


async def open_menu(ctx, shop, order_id):
    selector = f"kat-table-row:has(kat-link[label='{order_id}']) kat-dropdown-button"
    await ctx.tool("browser.click", shop=shop, selector=selector)
    await ctx.sleep(1)
    return await ctx.tool("browser.evaluate", shop=shop, expression=MENU_READ)


async def screenshot(ctx, shop, label):
    return await ctx.tool("browser.screenshot", shop=shop, label=label)
