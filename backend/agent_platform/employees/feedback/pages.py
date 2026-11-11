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

# 操作菜单是 kat-dropdown-button：展开开关在 shadow root 里，只认真实鼠标点击；
# 菜单项带稳定的 data-action（request_removal 等），比按语言匹配文字可靠。
MENU_READ = r"""(()=>{const order=__ORDER__;
const rows=[...document.querySelectorAll('kat-table-row')].filter(r=>
 [...r.querySelectorAll('kat-link')].some(a=>a.getAttribute('label')===order));
const row=rows[0];
const dd=row&&row.querySelector('kat-dropdown-button');
const vis=e=>{const b=e.getBoundingClientRect();const s=getComputedStyle(e);
 return b.width>0&&b.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
const options=dd&&dd.shadowRoot?[...dd.shadowRoot.querySelectorAll('button.option')]:[];
const toggle=dd&&dd.shadowRoot?dd.shadowRoot.querySelector('button.indicator'):null;
return {url:location.href,title:document.title,
 expanded:toggle?toggle.getAttribute('aria-expanded'):null,
 items:options.map(e=>({action:e.getAttribute('data-action'),text:(e.innerText||'').trim(),
  visible:vis(e),disabled:!!(e.disabled||e.hasAttribute('disabled'))})),
 text:(document.body?document.body.innerText:'').slice(0,4000)};})()"""

MENU_TOGGLE_JS = r"""(()=>{const order=__ORDER__;
const rows=[...document.querySelectorAll('kat-table-row')].filter(r=>
 [...r.querySelectorAll('kat-link')].some(a=>a.getAttribute('label')===order));
const row=rows[0];
if(!row)return {error:'ROW_NOT_FOUND'};
const dd=row.querySelector('kat-dropdown-button');
if(!dd||!dd.shadowRoot)return {error:'DROPDOWN_NOT_FOUND'};
const toggle=dd.shadowRoot.querySelector('button.indicator');
if(!toggle)return {error:'TOGGLE_NOT_FOUND'};
dd.scrollIntoView({block:'center'});
const r=toggle.getBoundingClientRect();
return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
 onScreen:r.top>=0&&r.bottom<=innerHeight};})()"""

MENU_ACTION_JS = r"""(()=>{const order=__ORDER__,want=__ACTION__;
const rows=[...document.querySelectorAll('kat-table-row')].filter(r=>
 [...r.querySelectorAll('kat-link')].some(a=>a.getAttribute('label')===order));
const row=rows[0];
if(!row)return {error:'ROW_NOT_FOUND'};
const dd=row.querySelector('kat-dropdown-button');
if(!dd||!dd.shadowRoot)return {error:'DROPDOWN_NOT_FOUND'};
const opt=dd.shadowRoot.querySelector('button.option[data-action="'+want+'"]');
if(!opt)return {error:'OPTION_NOT_FOUND'};
const r=opt.getBoundingClientRect();
if(!r.width||!r.height)return {error:'OPTION_NOT_VISIBLE'};
return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
 text:(opt.innerText||'').trim()};})()"""

# 审核入口会请求 /fbmapi/v1/feedbacks/<id>/removal；被拒绝时页面不会打开表单，
# 只有从 Performance 记录里能读到真实 HTTP 状态。
REMOVAL_ENTRY_JS = r"""(()=>{const start=__START__;
const r=performance.getEntriesByType('resource').filter(e=>e.startTime>=start)
 .filter(e=>/\/fbmapi\/v1\/feedbacks\/[^/]+\/removal/.test(new URL(e.name).pathname)).at(-1);
return r?{status:r.responseStatus||0,path:new URL(r.name).pathname}:null;})()"""

# 按可见文字找可点控件并返回坐标：紫鸟窗口里的组件多数只认真实鼠标事件。
CLICKABLE_JS = r"""(()=>{const labels=__LABELS__.map(l=>l.toLowerCase());
const n=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
const out=[];const walk=root=>{for(const e of root.querySelectorAll('*')){
 const tag=e.tagName,role=e.getAttribute&&e.getAttribute('role');
 const label=((e.getAttribute&&(e.getAttribute('label')||e.getAttribute('aria-label')))||'');
 const text=(e.innerText||'').trim();
 const clickable=/^(BUTTON|A|KAT-BUTTON|INPUT)$/.test(tag)
  ||['button','menuitem','radio','option','link'].includes(role);
 if(!clickable||e.disabled||e.hasAttribute('disabled'))continue;
 const hay=n(label+' '+text);
 if(!labels.some(l=>hay===l||hay.startsWith(l)))continue;
 const r=e.getBoundingClientRect();
 if(r.width&&r.height)out.push({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
  text:text.slice(0,40),tag});
 if(e.shadowRoot)walk(e.shadowRoot);}};walk(document);return out.slice(0,5);})()"""


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


def requests_review(menu):
    """菜单里是否有可点的“请求审核”（按稳定的 data-action 判断，不看语言）。"""
    return any(item.get("action") == "request_removal" and item.get("visible")
               for item in (menu or {}).get("items", []))


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
    """展开订单行的操作菜单；展开开关只认真实鼠标点击，没展开就再点一次。"""
    for _ in range(3):
        point = await ctx.tool("browser.evaluate", shop=shop,
                               expression=MENU_TOGGLE_JS.replace("__ORDER__", json.dumps(order_id)))
        if not isinstance(point, dict) or point.get("x") is None:
            raise RuntimeError(f"订单 {order_id} 的操作菜单没有找到："
                               f"{(point or {}).get('error', '未知原因')}")
        if not point.get("onScreen"):
            raise RuntimeError(f"订单 {order_id} 的操作菜单不在可视区域内")
        await ctx.tool("browser.click_point", shop=shop, x=point["x"], y=point["y"])
        for _ in range(6):
            await ctx.sleep(0.5)
            menu = await ctx.tool("browser.evaluate", shop=shop,
                                  expression=MENU_READ.replace("__ORDER__", json.dumps(order_id)))
            if (menu or {}).get("expanded") == "true" or any(
                    item.get("visible") for item in (menu or {}).get("items", [])):
                return menu
    raise RuntimeError(f"订单 {order_id} 的操作菜单点开后没有展开")


async def menu_action_point(ctx, shop, order_id, action):
    """操作菜单里某个 data-action 选项的点击坐标；菜单必须先展开。"""
    point = await ctx.tool("browser.evaluate", shop=shop,
                           expression=MENU_ACTION_JS.replace("__ORDER__", json.dumps(order_id))
                           .replace("__ACTION__", json.dumps(action)))
    return point if isinstance(point, dict) else {}


async def removal_entry(ctx, shop, started, attempts=10):
    """审核入口请求的真实 HTTP 状态；没观察到请求时返回 None。"""
    for _ in range(attempts):
        entry = await ctx.tool("browser.evaluate", shop=shop,
                               expression=REMOVAL_ENTRY_JS.replace("__START__", json.dumps(started)))
        if entry:
            return entry
        await ctx.sleep(0.5)
    return None


async def click_text(ctx, shop, labels):
    """按可见文字找可点控件并真实点击；返回 {clicked, text} 或 {clicked: False}。"""
    points = await ctx.tool("browser.evaluate", shop=shop,
                            expression=CLICKABLE_JS.replace(
                                "__LABELS__", json.dumps([label.lower() for label in labels],
                                                         ensure_ascii=False)))
    if not isinstance(points, list) or not points:
        return {"clicked": False}
    point = points[0]
    await ctx.tool("browser.click_point", shop=shop, x=point["x"], y=point["y"])
    return {"clicked": True, "text": point.get("text", ""), "tag": point.get("tag", "")}


async def screenshot(ctx, shop, label):
    return await ctx.tool("browser.screenshot", shop=shop, label=label)
