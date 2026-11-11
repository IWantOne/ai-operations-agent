"""Seller Central 登录与站点切换：读页面状态、等紫鸟自动登录、切到目标站点。

移植自旧项目 scripts/ziniao_marketplace.py 的核心部分，只保留差评用得到的三块：
- 读页面：登录墙 / 验证码 / 反爬、头部可见国家
- 等登录：紫鸟自动填账号密码时点掉提交；保存账号卡片可点时点它；验证码由紫鸟填
- 切站点：在店铺当前域名上打开账号切换器，点目标国家行，再回读头部国家确认
"""
import asyncio
import json

from .bindings import CODE_HOSTS, MARKET_CODES, code_for_country

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

SELECT_JS = r"""(()=>{const code=__CODE__,labels=__LABELS__,names=new Set(labels.map(l=>l.toLowerCase()));
try{for(const loc of [document.documentElement.lang,...(navigator.languages||[]),'zh-CN','zh-TW','en','ja','de','fr','it','es']){
 if(!loc)continue;const d=new Intl.DisplayNames([loc],{type:'region'});const v=d.of(code);if(v)names.add(v.trim().toLowerCase());}}catch(e){}
const rows=Array.from(document.querySelectorAll('button.full-page-account-switcher-account-details')).filter(r=>r.getClientRects().length);
const hit=rows.find(r=>{const t=(r.innerText||'').replace(/\s+/g,' ').trim().toLowerCase();
 return Array.from(names).some(n=>t===n||t.startsWith(n+' '));});
if(!hit)return JSON.stringify({clicked:false,rows:rows.map(r=>(r.innerText||'').replace(/\s+/g,' ').trim().slice(0,40))});
for(const type of ['pointerover','pointerdown','mousedown','pointerup','mouseup','click']){
 hit.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,composed:true,view:window}));}
return JSON.stringify({clicked:true,text:(hit.innerText||'').replace(/\s+/g,' ').trim().slice(0,80)});})()"""

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


async def switch_market(ctx, shop, code, timeout):
    """在店铺当前域名打开账号切换器，展开账号卡片，点目标站点行，再等登录后的头部国家确认。"""
    host = str((await read(ctx, shop)).get("host") or "")
    if not host.startswith("sellercentral."):
        raise RuntimeError(f"当前页面不是 Seller Central（{host or '未知域名'}），无法切换站点")
    await ctx.tool("browser.goto", shop=shop, url=f"https://{host}{SWITCHER_PATH}")
    deadline = asyncio.get_running_loop().time() + timeout
    clicked = None
    expanded = 0
    while asyncio.get_running_loop().time() < deadline:
        state = await read(ctx, shop)
        if state.get("accountCard") and expanded < 3:
            expanded += 1
            await _click(ctx, shop, state["accountCard"])
            await ctx.sleep(2)
            continue
        expression = SELECT_JS.replace("__CODE__", json.dumps(code)) \
                              .replace("__LABELS__", json.dumps([CHINESE.get(code, ""), ENGLISH.get(code, "")],
                                                                ensure_ascii=False))
        result = await ctx.tool("browser.evaluate", shop=shop, expression=expression)
        data = json.loads(result) if isinstance(result, str) else {}
        if data.get("clicked"):
            clicked = data.get("text")
            break
        await ctx.sleep(2)
    if not clicked:
        raise RuntimeError(f"账号切换器里没有找到 {CHINESE.get(code, code)} 的站点行")
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        await ctx.sleep(2)
        state = await read(ctx, shop)
        if state.get("gate") == "LOGGED_IN" and code_for_country(state.get("countryText")) == code:
            return {"ok": True, "countryText": state.get("countryText"), "clicked": clicked}
    raise RuntimeError(f"点了 {CHINESE.get(code, code)} 的站点行，但页面头部国家没有变成目标站点")
    if not clicked:
        raise RuntimeError(f"账号切换器里没有找到 {CHINESE.get(code, code)} 的站点行")
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        await ctx.sleep(2)
        state = await read(ctx, shop)
        if code_for_country(state.get("countryText")) == code:
            return {"ok": True, "countryText": state.get("countryText"), "clicked": clicked}
    raise RuntimeError(f"点了 {CHINESE.get(code, code)} 的站点行，但页面头部国家没有变成目标站点")


async def prepare(ctx, shop, marketplace_id, timeout):
    """打开目标站点首页，等登录/选取账户，确认站点；返回 (页面状态, 站点代码)。"""
    code = MARKET_CODES.get(str(marketplace_id))
    host = CODE_HOSTS.get(code)
    if not host:
        raise ValueError(f"站点 {marketplace_id} 没有对应的 Seller Central 地址")
    await ctx.tool("browser.goto", shop=shop, url=f"https://{host}/")
    state = await wait_login(ctx, shop, timeout)
    if "/account-switcher" in str(state.get("loginHref") or ""):
        try:
            await switch_market(ctx, shop, code, timeout)
        except RuntimeError:
            return state, code
        state = await wait_login(ctx, shop, timeout)
    elif state.get("gate") == "LOGGED_IN" and code_for_country(state.get("countryText")) != code:
        await switch_market(ctx, shop, code, timeout)
        state = await read(ctx, shop)
    return state, code
