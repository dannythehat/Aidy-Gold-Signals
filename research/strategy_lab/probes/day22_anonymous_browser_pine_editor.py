"""Read-only browser research: can a signed-out TradingView chart open Pine Editor?

No login, signup, order placement, site data modification, credential use,
script submission or account interaction. Logs only limited UI labels and
whether an unauthenticated script editor seems accessible.
"""
from __future__ import annotations

import asyncio
import json
from playwright.async_api import async_playwright

URL = "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD&interval=5"


async def main() -> None:
    result={"url":URL,"session":"anonymous_no_cookies","editor_clicked":False}
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":1440,"height":900},locale="en-US")
        try:
            nav=await page.goto(URL,wait_until="domcontentloaded",timeout=50000)
            await page.wait_for_timeout(14000)
            result["http_status"]=nav.status if nav else None
            result["title"]=(await page.title())[:150]
            html=await page.locator("body").inner_text(timeout=10000)
            lower=html.lower()
            result["page_text_characters"]=len(html)
            result["pine_word_found"]="pine editor" in lower or "pine script" in lower
            result["login_word_found"]="sign in" in lower or "log in" in lower
            controls=await page.locator("button, [role='button'], [data-tooltip]").all()
            names=[]
            for control in controls[:220]:
                try:
                    name=(await control.get_attribute("aria-label") or
                          await control.get_attribute("data-tooltip") or
                          await control.inner_text(timeout=600))
                    if name:
                        names.append(name.strip()[:70])
                except Exception:
                    continue
            result["pine_related_controls"]=[n for n in names if "pine" in n.lower()]
            result["auth_related_controls"]=[n for n in names if "sign" in n.lower() or "log" in n.lower()]
            result["first_buttons"]=names[:30]
            candidates=page.get_by_role("button",name="Pine",exact=False)
            result["pine_accessible_button_count"]=await candidates.count()
            if await candidates.count()>0:
                await candidates.first.click(timeout=12000)
                await page.wait_for_timeout(9000)
                result["editor_clicked"]=True
                body_original=(await page.locator("body").inner_text())[:50000]
                result["body_after_text"]=body_original[:6000]
                result["after_url"]=page.url
                result["dialog_count"]=await page.get_by_role("dialog").count()
                result["textarea_count"]=await page.locator("textarea").count()
                result["contenteditable_count"]=await page.locator("[contenteditable='true']").count()
                result["monaco_count"]=await page.locator(".monaco-editor").count()
                result["iframe_count"]=await page.locator("iframe").count()
                result["iframe_hosts"]=[(item.url.split("/")[2] if len(item.url.split("/"))>2 else "") for item in page.frames][:15]
                result["text_titles_after"]=await page.locator("[role='tab']").all_text_contents()
                body=body_original.lower()
                result["editor_after_click_visible"]="add to chart" in body or "create new" in body
                result["login_after_click_visible"]="sign in" in body or "log in" in body
                result["pine_after_click_buttons"]=[n[:60] for n in (await page.locator("button").all_text_contents()) if "chart" in n.lower() or "pine" in n.lower()][:30]
                result["editor_controls"] = await page.locator("button, [role='button'], [title], [aria-label]").evaluate_all(
                    """elements => elements.map(e => ({
                        tag:e.tagName, text:(e.innerText || '').trim().slice(0,65),
                        title:(e.getAttribute('title')||'').slice(0,90),
                        aria:(e.getAttribute('aria-label')||'').slice(0,90),
                        data:(e.getAttribute('data-name')||'').slice(0,70),
                    })).filter(o =>
                        /chart|script|pine|save|compile|publish|apply|add|run/i.test(
                            o.text + o.title + o.aria + o.data
                        )
                    ).slice(-55)"""
                )
                result["editor_textareas"] = await page.locator("textarea").evaluate_all(
                    """els => els.map(e => ({class:e.className,aria:e.getAttribute('aria-label'),
                        role:e.getAttribute('role'),value_length:e.value.length}))"""
                )
        except Exception as exc:
            result["exception"]={"type":type(exc).__name__,"message":str(exc)[:280]}
        finally:
            await browser.close()
    print("DAY22_ANONYMOUS_NATIVE_UI_PROBE",json.dumps(result,sort_keys=True))
    if result.get("editor_after_click_visible"):
        print("DAY22_NATIVE_EDITOR_UI_POSSIBLY_AVAILABLE: inspect next without claiming source parity")
    else:
        print("DAY22_NATIVE_EDITOR_NOT_PROVEN: do not call original-platform parity passed")


if __name__=="__main__":
    asyncio.run(main())
