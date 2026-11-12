"""紫鸟窗口里的 Seller Central：读页面状态、等自动登录、切到目标站点。

属于资源池能力：窗口打开后由这里把店铺带到目标站点，业务层只负责调用。
移植自旧项目 scripts/ziniao_marketplace.py 的核心，只保留平台用得到的三块：
- 读页面：登录墙 / 验证码 / 反爬、头部可见国家
- 等登录：紫鸟自动填账号密码时点掉提交；保存账号卡片可点时点它；验证码由紫鸟填
- 切站点：在店铺当前域名上打开账号切换器，展开账号卡片，点目标国家行，再回读头部国家确认
"""
import asyncio
import json

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

MARKET_CODES = {
    "ATVPDKIKX0DER": "US", "A2EUQ1WTGCTBG2": "CA", "A1AM78C64UM0Y8": "MX",
    "A1F83G8C2ARO7P": "UK", "A1PA6795UKMFR9": "DE", "A13V1IB3VIYZZH": "FR",
    "APJ6JRA9NG5V4": "IT", "A1RKKUPIHCS9HS": "ES", "A1805IZSGTT6HS": "NL",
    "A2NODRKZP88ZB9": "SE", "A1C3SOZRARQ6R3": "PL", "AMEN7PMS3EDWL": "BE",
    "A33AVAJ2PDY3EV": "TR", "A2Q3Y263D00KWC": "BR", "A1VC38T7YXB528": "JP",
    "A28R8C7NBKEWEA": "IE", "A17E79C6D8DWNP": "SA", "A2VIGQ35RCS4UG": "AE",
}
CODE_HOSTS = {code: MARKETS[mid] for mid, code in MARKET_CODES.items()}
CODE_IDS = {code: mid for mid, code in MARKET_CODES.items()}

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


def host_for(marketplace_id):
    return MARKETS.get(str(marketplace_id))

STATE_JS = r"""(()=>{
const q=s=>document.querySelector(s);
const href=location.href;
const country=q('.dropdown-account-switcher-header-label-regional');
const visible=country&&country.getClientRects().length>0&&getComputedStyle(country).visibility!=='hidden';
const header=q('.dropdown-account-switcher-header');
const mail=q('#ap_email')||q('#ap_email_login');
const secret=q('#ap_password');
const otp=q('#auth-mfa-otpcode');
const pick=id=>{
 if(q('input#'+id+'[type="submit"]'))return 'input#'+id+'[type="submit"]';
 if(q('#'+id+' input[type="submit"]'))return '#'+id+' input[type="submit"]';
 return q('#'+id)?'#'+id:null;};
const form={email:!!mail,password:!!secret,otp:!!otp,mfa:!!q('#auth-mfa-form'),
 device:!!q('#auth-select-device-form'),captcha:!!q('#captchacharacters, img[src*="captcha"]')};
const title=document.title||'';
const blocked=/Robot Check/i.test(title)?'ROBOT_CHECK':(/Server Busy/i.test(title)?'SERVER_BUSY':null);
let gate='UNKNOWN';
if(blocked)gate='BLOCKED';
else if(form.captcha)gate='CAPTCHA';
else if(form.otp||form.mfa)gate='MFA_REQUIRED';
else if(form.device)gate='MFA_DEVICE_REQUIRED';
else if(form.email)gate='SIGNIN_REQUIRED';
else if(form.password)gate='PASSWORD_REQUIRED';
else if(href.indexOf('/ap/signin')>=0)gate='LOGIN_URL_WITHOUT_FORM';
else if(header)gate='LOGGED_IN';
const groups=Array.from(document.querySelectorAll('div[class*="cvf-account-switcher-account-group-"]'))
 .filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
const rowsEls=Array.from(document.querySelectorAll('button.full-page-account-switcher-account-details')).filter(r=>r.getClientRects().length);
const cards=rowsEls.filter(r=>r.querySelector('.full-page-account-switcher-account-expander-icon'));
if(cards.length===1&&!cards[0].id)cards[0].id='platform-account-card';
if(rowsEls.length===1&&!rowsEls[0].id)rowsEls[0].id='platform-account-row';
const accountCard=cards.length===1?'#platform-account-card':null;
const accountRow=rowsEls.length===1?'#platform-account-row':null;
const links=Array.from(document.querySelectorAll('a[href]'));
const signin=links.find(e=>{try{const u=new URL(e.href);return e.getClientRects().length&&u.pathname==='/signin';}catch(x){return false;}})
 || links.find(e=>/^(log\s*in|sign\s*in|登入|登录|登錄|ログイン|anmelden)$/i.test((e.textContent||'').trim())&&e.getClientRects().length);
const cookie=Array.from(document.querySelectorAll('button, a, input[type="button"]'))
 .find(e=>e.getClientRects().length&&/continue without accepting|accept all cookies|拒绝|接受全部/i.test((e.innerText||e.value||'').trim()));
return {gate,blockedBy:blocked,ready:document.readyState,host:location.host,
 countryText:visible?country.innerText.trim():'',loginHref:href,
 signinUrl:signin?signin.href:null,cookieText:cookie?(cookie.innerText||cookie.value||'').trim().slice(0,40):null,
 accountCard,accountRow,accountRows:rowsEls.length,
 emailFilled:!!(mail&&mail.value),passwordFilled:!!(secret&&secret.value),otpFilled:!!(otp&&otp.value),
 nextButton:pick('continue')||pick('signInSubmit'),
 deviceButton:form.device?'#auth-select-device-form input[type="submit"], #auth-select-device-form button':null,
 savedAccount:groups.length===1&&groups[0]&&(groups[0].id='platform-saved-login-account')?'#platform-saved-login-account':null};
})()"""

ENGLISH = {"US": "United States", "CA": "Canada", "MX": "Mexico", "UK": "United Kingdom",           "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
           "SE": "Sweden", "PL": "Poland", "BE": "Belgium", "TR": "Turkey", "BR": "Brazil",
           "JP": "Japan", "IE": "Ireland", "SA": "Saudi Arabia", "AE": "United Arab Emirates"}
CHINESE = {"US": "美国", "CA": "加拿大", "MX": "墨西哥", "UK": "英国", "DE": "德国", "FR": "法国",
           "IT": "意大利", "ES": "西班牙", "NL": "荷兰", "SE": "瑞典", "PL": "波兰", "BE": "比利时",
           "TR": "土耳其", "BR": "巴西", "JP": "日本", "IE": "爱尔兰", "SA": "沙特阿拉伯",
           "AE": "阿拉伯联合酋长国"}


async def read(ctx, shop):
    return await ctx.tool("browser.evaluate", shop=shop, expression=STATE_JS)


async def _click(ctx, shop, selector):
    return await ctx.tool("browser.click", shop=shop, selector=selector)


CLICK_TEXT_JS = r"""(()=>{const labels=__LABELS__.map(l=>l.toLowerCase());
const walk=root=>{const out=[];const visit=r=>{for(const e of r.querySelectorAll('*')){
 const tag=e.tagName,role=e.getAttribute&&e.getAttribute('role');
 const text=(e.innerText||e.value||'').trim().toLowerCase();
 if((/^(BUTTON|A|INPUT)$/.test(tag)||role==='button'||role==='link')&&labels.some(l=>text===l||text.startsWith(l)))out.push(e);
 if(e.shadowRoot)visit(e.shadowRoot);}};visit(root);return out;};
const hit=walk(document).find(e=>e.getClientRects().length);
if(!hit)return JSON.stringify({clicked:false});
for(const type of ['pointerover','pointerdown','mousedown','pointerup','mouseup','click']){
 hit.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,composed:true,view:window}));}
return JSON.stringify({clicked:true,text:(hit.innerText||hit.value||'').trim().slice(0,40)});})()"""


async def _click_text(ctx, shop, labels):
    expression = CLICK_TEXT_JS.replace("__LABELS__", json.dumps(labels, ensure_ascii=False))
    value = await ctx.tool("browser.evaluate", shop=shop, expression=expression)
    try:
        return json.loads(value) if isinstance(value, str) else {"clicked": False}
    except ValueError:
        return {"clicked": False}


async def wait_login(ctx, shop, timeout):
    """等紫鸟自动登录；字段填好后才点提交，保存账号卡片可点时点它，先处理 cookie 弹窗与登录入口。"""
    deadline = asyncio.get_running_loop().time() + timeout
    state = await read(ctx, shop)
    submits = 0
    device_clicks = 0
    entries = 0
    cookies = 0
    cards = 0
    rows_clicked = 0
    while asyncio.get_running_loop().time() < deadline:
        gate = state.get("gate")
        if gate == "LOGGED_IN":
            return state
        if gate in {"BLOCKED", "CAPTCHA"}:
            return state
        if gate == "SIGNIN_REQUIRED" and state.get("emailFilled") and submits < 2:
            submits += 1
            await _click(ctx, shop, state["nextButton"])
        elif gate == "PASSWORD_REQUIRED" and state.get("passwordFilled") and submits < 3:
            submits += 1
            await _click(ctx, shop, state["nextButton"])
        elif gate == "MFA_REQUIRED" and state.get("otpFilled") and submits < 4:
            submits += 1
            await _click(ctx, shop, state["nextButton"])
        elif gate == "MFA_DEVICE_REQUIRED" and device_clicks < 1:
            device_clicks += 1
            if state.get("deviceButton"):
                await _click(ctx, shop, state["deviceButton"])
        elif gate in {"UNKNOWN", "LOGIN_URL_WITHOUT_FORM"}:
            if state.get("cookieText") and cookies < 1:
                cookies += 1
                await _click_text(ctx, shop, [state["cookieText"]])
            elif state.get("savedAccount"):
                await _click(ctx, shop, state["savedAccount"])
            elif state.get("signinUrl") and entries < 2:
                entries += 1
                await ctx.tool("browser.goto", shop=shop, url=state["signinUrl"])
            elif "/account-switcher" in str(state.get("loginHref") or ""):
                return state
        await ctx.sleep(3)
        state = await read(ctx, shop)
    return state


SWITCHER_PATH = "/account-switcher/default/merchantMarketplace?returnTo=%2Famazonsell%2Fbusiness"


ROW_RECT_JS = r"""(()=>{const code=__CODE__,labels=__LABELS__;const n=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
const names=new Set(labels.map(l=>l.toLowerCase()));
try{for(const loc of [document.documentElement.lang,...(navigator.languages||[]),'zh-CN','zh-TW','en','ja','de']){
 if(!loc)continue;const d=new Intl.DisplayNames([loc],{type:'region'});const v=d.of(code);if(v)names.add(v.trim().toLowerCase());}}catch(e){}
const rows=[...document.querySelectorAll('button.full-page-account-switcher-account-details')];
const hits=rows.filter(r=>{const t=n(r.innerText);
 return t&&[...names].some(x=>t===x||t.startsWith(x+' '));});
if(hits.length!==1)return JSON.stringify({found:false,hits:hits.length,
 rows:rows.slice(0,40).map(r=>n(r.innerText).slice(0,24))});
const b=hits[0];b.scrollIntoView({block:'center'});
const r=b.getBoundingClientRect();
const x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2);
const top=document.elementFromPoint(x,y);
return JSON.stringify({found:true,selected:/account-selected/.test(String(b.className)),
 x,y,inside:!!(top&&b.contains(top))});})()"""

# 确认控件是 kat-button，真正的按钮在它的 shadow root 里：坐标点击打不中，
# 只有对 shadow 里的 button 派发 click 才会走页面的切换逻辑。
CONFIRM_BUTTON_JS = r"""(()=>{const want=/^(选择账户|選取帳戶|select account)$/i;
const all=[...document.querySelectorAll('kat-button,kat-action-button')];
const host=all.find(e=>e.getAttribute('data-test')==='confirm-selection')||all.filter(e=>{
 const label=((e.getAttribute('label')||e.getAttribute('aria-label'))||'').trim();
 return want.test(label);}).pop();
if(!host)return JSON.stringify({found:false});
const inner=host.shadowRoot?host.shadowRoot.querySelector('button'):host;
if(!inner)return JSON.stringify({found:false,reason:'NO_INNER'});
if(inner.disabled||host.hasAttribute('disabled'))return JSON.stringify({found:false,reason:'DISABLED'});
host.scrollIntoView({block:'center'});
inner.click();
return JSON.stringify({clicked:true,label:(host.getAttribute('label')||'').trim()});})()"""


# 账号卡片默认折叠：点开它才会列出站点行。展开控件只认真实鼠标点击。
ACCOUNT_CARD_JS = r"""(()=>{const rows=[...document.querySelectorAll('button.full-page-account-switcher-account-details')]
 .filter(r=>r.querySelector('.full-page-account-switcher-account-expander-icon'));
if(rows.length!==1)return JSON.stringify({found:false,count:rows.length});
const r=rows[0];r.scrollIntoView({block:'center'});
const b=r.getBoundingClientRect();
return JSON.stringify({found:true,x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});})()"""


async def switch_market(ctx, shop, code, timeout):
    """在店铺当前域名打开账号切换器，选中目标站点行，点底部确认，再回读落地站点。"""
    label = CHINESE.get(code, code)
    state = await read(ctx, shop)
    host = str(state.get("host") or "")
    if not host.startswith("sellercentral."):
        raise RuntimeError(f"当前页面不是 Seller Central（{host or '未知域名'}），无法切换站点")
    if state.get("gate") == "LOGGED_IN" and code_for_country(state.get("countryText")) == code:
        return {"ok": True, "already": True, "countryText": state.get("countryText")}
    await ctx.tool("browser.goto", shop=shop, url=f"https://{host}{SWITCHER_PATH}")
    await ctx.sleep(6)
    deadline = asyncio.get_running_loop().time() + timeout
    row = None
    expanded = 0
    while asyncio.get_running_loop().time() < deadline:
        result = await ctx.tool("browser.evaluate", shop=shop,
                                expression=ROW_RECT_JS.replace("__CODE__", json.dumps(code))
                                .replace("__LABELS__", json.dumps([CHINESE.get(code, ""), ENGLISH.get(code, "")],
                                                                  ensure_ascii=False)))
        point = json.loads(result) if isinstance(result, str) else {}
        if point.get("found"):
            row = point
            break
        if expanded < 1:
            expanded += 1
            result = await ctx.tool("browser.evaluate", shop=shop, expression=ACCOUNT_CARD_JS)
            card = json.loads(result) if isinstance(result, str) else (result if isinstance(result, dict) else {})
            if card.get("x") is not None:
                await ctx.tool("browser.click_point", shop=shop, x=card["x"], y=card["y"])
                await ctx.sleep(3)
                continue
        await ctx.sleep(2)
    if not row:
        raise RuntimeError(f"账号切换器里没有找到 {label} 的站点行（列表可能还没展开）")
    # 目标站点已经是当前站点时，再点一次行会取消选中，确认按钮就点不动了。
    if not row.get("selected"):
        if not row.get("inside"):
            raise RuntimeError(f"找到 {label} 的站点行，但点击位置被其它元素挡住")
        await ctx.tool("browser.click_point", shop=shop, x=row["x"], y=row["y"])
        await ctx.sleep(1)
    confirm = None
    for _ in range(10):
        result = await ctx.tool("browser.evaluate", shop=shop, expression=CONFIRM_BUTTON_JS)
        point = json.loads(result) if isinstance(result, str) else {}
        if point.get("clicked"):
            confirm = point
            break
        await ctx.sleep(1)
    if not confirm:
        raise RuntimeError(f"选中了 {label}，但页面上没有可点的「选择账户」按钮")
    deadline = asyncio.get_running_loop().time() + timeout
    market_id = CODE_IDS.get(code, "")
    while asyncio.get_running_loop().time() < deadline:
        await ctx.sleep(2)
        state = await read(ctx, shop)
        if market_id and market_id in str(state.get("loginHref") or ""):
            return {"ok": True, "url": state.get("loginHref")}
        if state.get("gate") == "LOGGED_IN" and code_for_country(state.get("countryText")) == code:
            return {"ok": True, "countryText": state.get("countryText")}
    raise RuntimeError(f"点了 {label} 的站点行和选择账户，但页面没有切过去")


async def _home_url(ctx, shop):
    """店铺窗口的启动页（紫鸟给店铺配置的首页）；连接方式不提供时返回 None。"""
    try:
        value = await ctx.tool("browser.home", shop=shop)
    except Exception:
        return None
    return str(value) if value else None


async def prepare(ctx, shop, marketplace_id, timeout):
    """从店铺已登录的首页进入，需要时切到目标站点；返回 (页面状态, 站点代码)。"""
    code = MARKET_CODES.get(str(marketplace_id))
    host = CODE_HOSTS.get(code)
    if not code or not host:
        raise ValueError(f"站点 {marketplace_id} 没有对应的 Seller Central 地址")
    # 直接打开目标站点时，未登录的站点只会给一张营销页；先从店铺自己的首页进，
    # 那里才有可用的登录态和账号切换器。
    start = await _home_url(ctx, shop) or f"https://{host}/"
    await ctx.tool("browser.goto", shop=shop, url=start)
    state = await wait_login(ctx, shop, timeout)
    if state.get("gate") in {"BLOCKED", "CAPTCHA"}:
        return state, code
    if state.get("gate") == "LOGGED_IN" and code_for_country(state.get("countryText")) == code:
        return state, code
    await switch_market(ctx, shop, code, timeout)
    state = await wait_login(ctx, shop, timeout)
    return state, code
