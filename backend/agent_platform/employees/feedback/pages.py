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


async def open(ctx, shop, marketplace_id):
    """打开反馈管理器；没有对应站点时抛出可读原因。"""
    url = url_for(marketplace_id)
    if not url:
        raise ValueError(f"站点 {marketplace_id} 没有对应的 Seller Central 地址")
    await ctx.tool("browser.goto", shop=shop, url=url)


async def read_row(ctx, shop, order_id):
    return await ctx.tool("browser.evaluate", shop=shop,
                          expression=ROW_SCRIPT.replace("__ORDER__", json.dumps(order_id)))


async def open_menu(ctx, shop, order_id):
    selector = f"kat-table-row:has(kat-link[label='{order_id}']) kat-dropdown-button"
    await ctx.tool("browser.click", shop=shop, selector=selector)
    await ctx.sleep(1)
    return await ctx.tool("browser.evaluate", shop=shop, expression=MENU_READ)


async def screenshot(ctx, shop, label):
    return await ctx.tool("browser.screenshot", shop=shop, label=label)
