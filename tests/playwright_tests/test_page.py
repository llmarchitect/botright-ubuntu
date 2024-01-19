# Copyright (c) Microsoft Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import os
import re

import pytest

from playwright.async_api import Error, Route, TimeoutError
from botright.extended_typing import BrowserContext, Page


@pytest.mark.asyncio
async def test_close_should_reject_all_promises(browser):
    new_page = await browser.new_page()
    with pytest.raises(Error) as exc_info:
        await asyncio.gather(
            new_page.evaluate("() => new Promise(r => {})"), new_page.close()
        )
    assert " closed" in exc_info.value.message


@pytest.mark.asyncio
async def test_closed_should_not_visible_in_context_pages(browser):
    page = await browser.new_page()
    assert page in browser.pages
    await page.close()
    assert page not in browser.pages


async def close_should_run_beforeunload_if_asked_for(browser, server):
    page = await browser.new_page()
    await page.goto(server.PREFIX + "/beforeunload.html")
    # We have to interact with a page so that 'beforeunload' handlers
    # fire.
    await page.click("body")

    async with page.expect_event("dialog") as dialog_info:
        await page.close(run_before_unload=True)
    dialog = await dialog_info.value

    assert dialog.type == "beforeunload"
    assert dialog.default_value == ""
    assert dialog.message == ""
    async with page.expect_event("close"):
        await dialog.accept()


@pytest.mark.asyncio
async def test_close_should_not_run_beforeunload_by_default(browser, server):
    page = await browser.new_page()
    await page.goto(server.PREFIX + "/beforeunload.html")
    # We have to interact with a page so that 'beforeunload' handlers
    # fire.
    await page.click("body")
    await page.close()


@pytest.mark.asyncio
async def test_should_be_able_to_navigate_away_from_page_with_before_unload(page: Page, server):
    await page.goto(server.PREFIX + "/beforeunload.html")
    # We have to interact with a page so that 'beforeunload' handlers
    # fire.
    await page.click("body")
    await page.goto(server.EMPTY_PAGE)


@pytest.mark.asyncio
async def test_close_should_set_the_page_close_state(browser):
    page = await browser.new_page()
    assert page.is_closed() is False
    await page.close()
    assert page.is_closed()


@pytest.mark.asyncio
async def test_close_should_terminate_network_waiters(browser, server):
    page = await browser.new_page()

    async def wait_for_request():
        with pytest.raises(Error) as exc_info:
            async with page.expect_request(server.EMPTY_PAGE):
                pass
        return exc_info.value

    async def wait_for_response():
        with pytest.raises(Error) as exc_info:
            async with page.expect_response(server.EMPTY_PAGE):
                pass
        return exc_info.value

    results = await asyncio.gather(
        wait_for_request(), wait_for_response(), page.close()
    )
    for i in range(2):
        error = results[i]
        assert "Target page, context or browser has been closed" in error.message
        assert "Timeout" not in error.message


@pytest.mark.asyncio
async def test_close_should_be_callable_twice(browser):
    page = await browser.new_page()
    await asyncio.gather(
        page.close(),
        page.close(),
    )
    await page.close()


@pytest.mark.asyncio
async def test_load_should_fire_when_expected(page):
    async with page.expect_event("load"):
        await page.goto("about:blank")


@pytest.mark.asyncio
async def test_async_stacks_should_work(page, server):
    await page.route(
        "**/empty.html", lambda route, response: asyncio.create_task(route.abort())
    )
    with pytest.raises(Error) as exc_info:
        await page.goto(server.EMPTY_PAGE)
    assert __file__ in exc_info.value.stack


@pytest.mark.asyncio
async def test_opener_should_provide_access_to_the_opener_page(page: Page):
    async with page.expect_popup() as popup_info:
        await page.evaluate("window.open('about:blank')")
    popup = Page(await popup_info.value, page.browser, page.faker)
    opener = await popup.opener()
    assert opener == page


@pytest.mark.asyncio
async def test_opener_should_return_null_if_parent_page_has_been_closed(page: Page):
    async with page.expect_popup() as popup_info:
        await page.evaluate("window.open('about:blank')")
    popup = Page(await popup_info.value, page.browser, page.faker)
    await page.close()
    opener = await popup.opener()
    assert opener is None


@pytest.mark.asyncio
async def test_domcontentloaded_should_fire_when_expected(page):
    future = asyncio.create_task(page.goto("about:blank"))
    async with page.expect_event("domcontentloaded"):
        pass
    await future


@pytest.mark.asyncio
async def test_wait_for_request(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request(server.PREFIX + "/digits/2.png") as request_info:
        await page.evaluate(
            """() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }"""
        )
    request = await request_info.value
    assert request.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_request_should_work_with_predicate(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request(
            lambda request: request.url == server.PREFIX + "/digits/2.png"
    ) as request_info:
        await page.evaluate(
            """() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }"""
        )
    request = await request_info.value
    assert request.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_request_should_timeout(page):
    with pytest.raises(Error) as exc_info:
        async with page.expect_event("request", timeout=1):
            pass
    assert exc_info.type is TimeoutError


@pytest.mark.asyncio
async def test_wait_for_request_should_respect_default_timeout(page):
    page.set_default_timeout(1)
    with pytest.raises(Error) as exc_info:
        async with page.expect_event("request", lambda _: False):
            pass
    assert exc_info.type is TimeoutError


@pytest.mark.asyncio
async def test_wait_for_request_should_work_with_no_timeout(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request(
            server.PREFIX + "/digits/2.png", timeout=0
    ) as request_info:
        await page.evaluate(
            """() => setTimeout(() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }, 50)"""
        )
    request = await request_info.value
    assert request.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_request_should_work_with_url_match(page: Page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request(re.compile(r"digits\/\d\.png")) as request_info:
        await page.evaluate("fetch('/digits/1.png')")
    request = await request_info.value
    assert request.url == server.PREFIX + "/digits/1.png"


@pytest.mark.asyncio
async def test_wait_for_event_should_fail_with_error_upon_disconnect(page):
    with pytest.raises(Error) as exc_info:
        async with page.expect_download():
            await page.close()
    assert "Target page, context or browser has been closed" in exc_info.value.message


@pytest.mark.asyncio
async def test_wait_for_response_should_work(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_response(server.PREFIX + "/digits/2.png") as response_info:
        await page.evaluate(
            """() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }"""
        )
    response = await response_info.value
    assert response.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_response_should_respect_timeout(page):
    with pytest.raises(Error) as exc_info:
        async with page.expect_response("**/*", timeout=1):
            pass
    assert exc_info.type is TimeoutError


@pytest.mark.asyncio
async def test_wait_for_response_should_respect_default_timeout(page):
    page.set_default_timeout(1)
    with pytest.raises(Error) as exc_info:
        async with page.expect_response(lambda _: False):
            pass
    assert exc_info.type is TimeoutError


@pytest.mark.asyncio
async def test_wait_for_response_should_work_with_predicate(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_response(
            lambda response: response.url == server.PREFIX + "/digits/2.png"
    ) as response_info:
        await page.evaluate(
            """() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }"""
        )
    response = await response_info.value
    assert response.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_response_should_work_with_no_timeout(page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_response(server.PREFIX + "/digits/2.png") as response_info:
        await page.evaluate(
            """() => {
                fetch('/digits/1.png')
                fetch('/digits/2.png')
                fetch('/digits/3.png')
            }"""
        )
    response = await response_info.value
    assert response.url == server.PREFIX + "/digits/2.png"


@pytest.mark.asyncio
async def test_wait_for_response_should_use_context_timeout(
        page: Page, browser: BrowserContext, server
) -> None:
    await page.goto(server.EMPTY_PAGE)

    browser.set_default_timeout(1000)
    with pytest.raises(Error) as exc_info:
        async with page.expect_response("https://playwright.dev"):
            pass
    assert exc_info.type is TimeoutError
    assert "Timeout 1000ms exceeded" in exc_info.value.message


@pytest.mark.asyncio
async def test_expect_response_should_not_hang_when_predicate_throws(
        page: Page,
) -> None:
    with pytest.raises(Exception, match="Oops!"):
        async with page.expect_response("**/*"):
            raise Exception("Oops!")


@pytest.mark.asyncio
async def test_expose_binding(page):
    binding_source = []

    def binding(source, a, b):
        binding_source.append(source)
        return a + b

    await page.expose_binding("add", lambda source, a, b: binding(source, a, b))

    result = await page.evaluate("add(5, 6)")

    assert binding_source[0]["context"] == page.context
    assert binding_source[0]["page"] == page
    assert binding_source[0]["frame"] == page.main_frame
    assert result == 11


@pytest.mark.asyncio
async def test_expose_function(page):
    await page.expose_function("compute", lambda a, b: a * b)
    result = await page.evaluate("compute(9, 4)")
    assert result == 36


@pytest.mark.asyncio
async def test_expose_function_should_throw_exception_in_page_context(page):
    def throw():
        raise Exception("WOOF WOOF")

    await page.expose_function("woof", lambda: throw())
    result = await page.evaluate(
        """async() => {
            try {
                await woof()
            } catch (e) {
                return {message: e.message, stack: e.stack}
            }
        }"""
    )
    assert result["message"] == "WOOF WOOF"
    assert __file__ in result["stack"]


@pytest.mark.asyncio
async def test_expose_function_should_be_callable_from_inside_add_init_script(page):
    called = []
    await page.expose_function("woof", lambda: called.append(True))
    await page.add_init_script("woof()")
    await page.reload()
    assert called == [True]


@pytest.mark.asyncio
async def test_expose_function_should_survive_navigation(page, server):
    await page.expose_function("compute", lambda a, b: a * b)
    await page.goto(server.EMPTY_PAGE)
    result = await page.evaluate("compute(9, 4)")
    assert result == 36


@pytest.mark.asyncio
async def test_expose_function_should_await_returned_promise(page):
    async def mul(a, b):
        return a * b

    await page.expose_function("compute", mul)
    assert await page.evaluate("compute(3, 5)") == 15


@pytest.mark.asyncio
async def test_expose_function_should_work_on_frames(page, server):
    await page.expose_function("compute", lambda a, b: a * b)
    await page.goto(server.PREFIX + "/frames/nested-frames.html")
    frame = page.frames[1]
    assert await frame.evaluate("compute(3, 5)") == 15


@pytest.mark.asyncio
async def test_expose_function_should_work_on_frames_before_navigation(page, server):
    await page.goto(server.PREFIX + "/frames/nested-frames.html")
    await page.expose_function("compute", lambda a, b: a * b)
    frame = page.frames[1]
    assert await frame.evaluate("compute(3, 5)") == 15


@pytest.mark.asyncio
async def test_expose_function_should_work_after_cross_origin_navigation(page, server):
    await page.goto(server.EMPTY_PAGE)
    await page.expose_function("compute", lambda a, b: a * b)
    await page.goto(server.CROSS_PROCESS_PREFIX + "/empty.html")
    assert await page.evaluate("compute(9, 4)") == 36


@pytest.mark.asyncio
async def test_expose_function_should_work_with_complex_objects(page):
    await page.expose_function("complexObject", lambda a, b: dict(x=a["x"] + b["x"]))
    result = await page.evaluate("complexObject({x: 5}, {x: 2})")
    assert result["x"] == 7


@pytest.mark.asyncio
async def test_expose_bindinghandle_should_work(page):
    targets = []

    def logme(t):
        targets.append(t)
        return 17

    await page.expose_binding("logme", lambda source, t: logme(t), handle=True)
    result = await page.evaluate("logme({ foo: 42 })")
    assert (await targets[0].evaluate("x => x.foo")) == 42
    assert result == 17


@pytest.mark.asyncio
async def test_page_error_should_fire(page, server):
    url = server.PREFIX + "/error.html"
    async with page.expect_event("pageerror") as error_info:
        await page.goto(url)
    error = await error_info.value
    assert error.name == "Error"
    assert error.message == "Fancy error!"
    # Note that WebKit reports the stack of the 'throw' statement instead of the Error constructor call.
    assert (
            error.stack
            == """Error: Fancy error!\n    at c (myscript.js:14:11)\n    at b (myscript.js:10:5)\n    at a (myscript.js:6:5)\n    at myscript.js:3:1"""
    )


@pytest.mark.asyncio
async def test_page_error_should_handle_odd_values(page):
    cases = [["null", "null"], ["undefined", "undefined"], ["0", "0"], ['""', ""]]
    for [value, message] in cases:
        async with page.expect_event("pageerror") as error_info:
            await page.evaluate(f"() => setTimeout(() => {{ throw {value}; }}, 0)")
        error = await error_info.value
        assert error.message == message


@pytest.mark.asyncio
async def test_page_error_should_handle_object(page):
    async with page.expect_event("pageerror") as error_info:
        await page.evaluate("() => setTimeout(() => { throw {}; }, 0)")
    error = await error_info.value
    assert error.message == "Object"


@pytest.mark.asyncio
async def test_page_error_should_handle_window(page):
    async with page.expect_event("pageerror") as error_info:
        await page.evaluate("() => setTimeout(() => { throw window; }, 0)")
    error = await error_info.value
    assert error.message == "Window"


@pytest.mark.asyncio
async def test_page_error_should_pass_error_name_property(page):
    async with page.expect_event("pageerror") as error_info:
        await page.evaluate(
            """() => setTimeout(() => {
            const error = new Error("my-message");
            error.name = "my-name";
            throw error;
        }, 0)
        """
        )
    error = await error_info.value
    assert error.message == "my-message"
    assert error.name == "my-name"


expected_output = "<html><head></head><body><div>hello</div></body></html>"


@pytest.mark.asyncio
async def test_set_content_should_work(page):
    await page.set_content("<div>hello</div>")
    result = await page.content()
    assert result == expected_output


@pytest.mark.asyncio
async def test_set_content_should_work_with_domcontentloaded(page):
    await page.set_content("<div>hello</div>", wait_until="domcontentloaded")
    result = await page.content()
    assert result == expected_output


@pytest.mark.asyncio
async def test_set_content_should_work_with_doctype(page):
    doctype = "<!DOCTYPE html>"
    await page.set_content(f"{doctype}<div>hello</div>")
    result = await page.content()
    assert result == f"{doctype}{expected_output}"


@pytest.mark.asyncio
async def test_set_content_should_work_with_HTML_4_doctype(page):
    doctype = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">'
    await page.set_content(f"{doctype}<div>hello</div>")
    result = await page.content()
    assert result == f"{doctype}{expected_output}"


@pytest.mark.asyncio
async def test_set_content_should_respect_default_navigation_timeout(page):
    page.set_default_navigation_timeout(1)
    img_path = "/img.png"
    # stall for image
    await page.route(img_path, lambda route, request: None)

    with pytest.raises(Error) as exc_info:
        await page.set_content('<img src=server.PREFIX + "/img.png"></img>')
    assert "Timeout 1ms exceeded" in exc_info.value.message
    assert exc_info.type is TimeoutError


@pytest.mark.asyncio
async def test_set_content_should_await_resources_to_load(page):
    img_route = asyncio.Future()
    await page.route("**/img.png", lambda route, request: img_route.set_result(route))
    loaded = []

    async def load():
        await page.set_content('<img src=server.PREFIX + "/img.png"></img>')
        loaded.append(True)

    content_promise = asyncio.create_task(load())
    await asyncio.sleep(0)  # execute scheduled tasks, but don't await them
    route = await img_route
    assert loaded == []
    asyncio.create_task(route.continue_())
    await content_promise


@pytest.mark.asyncio
async def test_set_content_should_work_with_tricky_content(page):
    await page.set_content("<div>hello world</div>" + "\x7F")
    assert await page.eval_on_selector("div", "div => div.textContent") == "hello world"


@pytest.mark.asyncio
async def test_set_content_should_work_with_accents(page):
    await page.set_content("<div>aberración</div>")
    assert await page.eval_on_selector("div", "div => div.textContent") == "aberración"


@pytest.mark.asyncio
async def test_set_content_should_work_with_emojis(page):
    await page.set_content("<div>🐥</div>")
    assert await page.eval_on_selector("div", "div => div.textContent") == "🐥"


@pytest.mark.asyncio
async def test_set_content_should_work_with_newline(page):
    await page.set_content("<div>\n</div>")
    assert await page.eval_on_selector("div", "div => div.textContent") == "\n"


@pytest.mark.asyncio
async def test_add_script_tag_should_work_with_a_url(page, server):
    await page.goto(server.EMPTY_PAGE)
    script_handle = await page.add_script_tag(url=server.PREFIX + "/injectedfile.js")
    assert script_handle.as_element()
    assert await page.evaluate("__injected") == 42


@pytest.mark.asyncio
async def test_add_script_tag_should_work_with_a_url_and_type_module(page, server):
    await page.goto(server.EMPTY_PAGE)
    await page.add_script_tag(url=server.PREFIX + "/es6/es6import.js", type="module")
    assert await page.evaluate("__es6injected") == 42


@pytest.mark.asyncio
async def test_add_script_tag_should_work_with_a_path_and_type_module(
        page, assetdir, server
):
    await page.goto(server.EMPTY_PAGE)
    await page.add_script_tag(path=assetdir / "es6" / "es6pathimport.js", type="module")
    await page.wait_for_function("window.__es6injected")
    assert await page.evaluate("__es6injected") == 42


@pytest.mark.asyncio
async def test_add_script_tag_should_throw_an_error_if_loading_from_url_fail(
        page, server
):
    await page.goto(server.EMPTY_PAGE)
    with pytest.raises(Error) as exc_info:
        await page.add_script_tag(url=server.PREFIX + "/nonexistfile.js")
    assert exc_info.value


@pytest.mark.asyncio
async def test_add_script_tag_should_work_with_a_path(page, assetdir, server):
    await page.goto(server.EMPTY_PAGE)
    script_handle = await page.add_script_tag(path=assetdir / "injectedfile.js")
    assert script_handle.as_element()
    assert await page.evaluate("__injected") == 42


@pytest.mark.asyncio
async def test_add_script_tag_should_include_source_url_when_path_is_provided(
        page, assetdir, server
):
    # Lacking sourceURL support in WebKit
    await page.goto(server.EMPTY_PAGE)
    await page.add_script_tag(path=assetdir / "injectedfile.js")
    result = await page.evaluate("__injectedError.stack")
    assert os.path.join("assets", "injectedfile.js") in result


@pytest.mark.asyncio
async def test_add_script_tag_should_work_with_content(page, server):
    await page.goto(server.EMPTY_PAGE)
    script_handle = await page.add_script_tag(content="window.__injected = 35;")
    assert script_handle.as_element()
    assert await page.evaluate("__injected") == 35


@pytest.mark.asyncio
async def test_add_script_tag_should_throw_when_added_with_content_to_the_csp_page(
        page, server
):
    # Firefox fires onload for blocked script before it issues the CSP console error.
    await page.goto(server.PREFIX + "/csp.html")
    with pytest.raises(Error) as exc_info:
        await page.add_script_tag(content="window.__injected = 35;")
    assert exc_info.value


@pytest.mark.asyncio
async def test_add_script_tag_should_throw_a_nice_error_when_the_request_fails(
        page, server
):
    await page.goto(server.EMPTY_PAGE)
    url = server.PREFIX + "/this_does_not_exist.js"
    with pytest.raises(Error) as exc_info:
        await page.add_script_tag(url=url)
    assert url in exc_info.value.message


@pytest.mark.asyncio
async def test_add_style_tag_should_work_with_a_url(page, server):
    await page.goto(server.EMPTY_PAGE)
    style_handle = await page.add_style_tag(url=server.PREFIX + "/injectedstyle.css")
    assert style_handle.as_element()
    assert (
            await page.evaluate(
                "window.getComputedStyle(document.querySelector('body')).getPropertyValue('background-color')"
            )
            == "rgb(255, 0, 0)"
    )


@pytest.mark.asyncio
async def test_add_style_tag_should_throw_an_error_if_loading_from_url_fail(
        page, server
):
    await page.goto(server.EMPTY_PAGE)
    with pytest.raises(Error) as exc_info:
        await page.add_style_tag(url=server.PREFIX + "/nonexistfile.js")
    assert exc_info.value


@pytest.mark.asyncio
async def test_add_style_tag_should_work_with_a_path(page, assetdir, server):
    await page.goto(server.EMPTY_PAGE)
    style_handle = await page.add_style_tag(path=assetdir / "injectedstyle.css")
    assert style_handle.as_element()
    assert (
            await page.evaluate(
                "window.getComputedStyle(document.querySelector('body')).getPropertyValue('background-color')"
            )
            == "rgb(255, 0, 0)"
    )


@pytest.mark.asyncio
async def test_add_style_tag_should_include_source_url_when_path_is_provided(
        page, assetdir, server
):
    await page.goto(server.EMPTY_PAGE)
    await page.add_style_tag(path=assetdir / "injectedstyle.css")
    style_handle = await page.query_selector("style")
    style_content = await page.evaluate("style => style.innerHTML", style_handle)
    assert os.path.join("assets", "injectedstyle.css") in style_content


@pytest.mark.asyncio
async def test_add_style_tag_should_work_with_content(page, server):
    await page.goto(server.EMPTY_PAGE)
    style_handle = await page.add_style_tag(content="body { background-color: green; }")
    assert style_handle.as_element()
    assert (
            await page.evaluate(
                "window.getComputedStyle(document.querySelector('body')).getPropertyValue('background-color')"
            )
            == "rgb(0, 128, 0)"
    )


@pytest.mark.asyncio
async def test_add_style_tag_should_throw_when_added_with_content_to_the_CSP_page(
        page, server
):
    await page.goto(server.PREFIX + "/csp.html")
    with pytest.raises(Error) as exc_info:
        await page.add_style_tag(content="body { background-color: green; }")
    assert exc_info.value


@pytest.mark.asyncio
async def test_url_should_work(page, server):
    assert page.url == "about:blank"
    await page.goto(server.EMPTY_PAGE)
    assert page.url == server.EMPTY_PAGE


@pytest.mark.asyncio
async def test_url_should_include_hashes(page, server):
    await page.goto(server.EMPTY_PAGE + "#hash")
    assert page.url == server.EMPTY_PAGE + "#hash"
    await page.evaluate("window.location.hash = 'dynamic'")
    assert page.url == server.EMPTY_PAGE + "#dynamic"


@pytest.mark.asyncio
async def test_title_should_return_the_page_title(page, server):
    await page.goto(server.PREFIX + "/title.html")
    assert await page.title() == "Woof-Woof"


async def give_it_a_chance_to_fill(page):
    for i in range(5):
        await page.evaluate(
            "() => new Promise(f => requestAnimationFrame(() => requestAnimationFrame(f)))"
        )


@pytest.mark.asyncio
async def test_fill_should_fill_textarea(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.fill("textarea", "some value")
    assert await page.evaluate("result") == "some value"


@pytest.mark.asyncio
async def test_fill_should_fill_input(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.fill("input", "some value")
    assert await page.evaluate("result") == "some value"


@pytest.mark.asyncio
async def test_fill_should_throw_on_unsupported_inputs(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    for type in [
        "button",
        "checkbox",
        "file",
        "image",
        "radio",
        "reset",
        "submit",
    ]:
        await page.eval_on_selector(
            "input", "(input, type) => input.setAttribute('type', type)", type
        )
        with pytest.raises(Error) as exc_info:
            await page.fill("input", "")
        assert f'Input of type "{type}" cannot be filled' in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_fill_different_input_types(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    for type in ["password", "search", "tel", "text", "url"]:
        await page.eval_on_selector(
            "input", "(input, type) => input.setAttribute('type', type)", type
        )
        await page.fill("input", "text " + type)
        assert await page.evaluate("result") == "text " + type


@pytest.mark.asyncio
async def test_fill_should_fill_date_input_after_clicking(page):
    await page.set_content("<input type=date>")
    await page.click("input")
    await page.fill("input", "2020-03-02")
    assert await page.eval_on_selector("input", "input => input.value") == "2020-03-02"


@pytest.mark.asyncio
async def test_fill_should_throw_on_incorrect_date(page):
    # Disabled as in upstream, we should validate time in the Playwright lib
    await page.set_content("<input type=date>")
    with pytest.raises(Error) as exc_info:
        await page.fill("input", "2020-13-05")
    assert "Malformed value" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_fill_time_input(page):
    await page.set_content("<input type=time>")
    await page.fill("input", "13:15")
    assert await page.eval_on_selector("input", "input => input.value") == "13:15"


@pytest.mark.asyncio
async def test_fill_should_throw_on_incorrect_time(page):
    # Disabled as in upstream, we should validate time in the Playwright lib
    await page.set_content("<input type=time>")
    with pytest.raises(Error) as exc_info:
        await page.fill("input", "25:05")
    assert "Malformed value" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_fill_datetime_local_input(page):
    await page.set_content("<input type=datetime-local>")
    await page.fill("input", "2020-03-02T05:15")
    assert (
            await page.eval_on_selector("input", "input => input.value")
            == "2020-03-02T05:15"
    )


@pytest.mark.asyncio
async def test_fill_should_throw_on_incorrect_datetime_local(page):
    await page.set_content("<input type=datetime-local>")
    with pytest.raises(Error) as exc_info:
        await page.fill("input", "abc")
    assert "Malformed value" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_fill_contenteditable(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.fill("div[contenteditable]", "some value")
    assert (
            await page.eval_on_selector("div[contenteditable]", "div => div.textContent")
            == "some value"
    )


@pytest.mark.asyncio
async def test_fill_should_fill_elements_with_existing_value_and_selection(
        page, server
):
    await page.goto(server.PREFIX + "/input/textarea.html")

    await page.eval_on_selector("input", "input => input.value = 'value one'")
    await page.fill("input", "another value")
    assert await page.evaluate("result") == "another value"

    await page.eval_on_selector(
        "input",
        """input => {
        input.selectionStart = 1
        input.selectionEnd = 2
    }""",
    )

    await page.fill("input", "maybe this one")
    assert await page.evaluate("result") == "maybe this one"

    await page.eval_on_selector(
        "div[contenteditable]",
        """div => {
        div.innerHTML = 'some text <span>some more text<span> and even more text'
        range = document.createRange()
        range.selectNodeContents(div.querySelector('span'))
        selection = window.getSelection()
        selection.removeAllRanges()
        selection.addRange(range)
    }""",
    )

    await page.fill("div[contenteditable]", "replace with this")
    assert (
            await page.eval_on_selector("div[contenteditable]", "div => div.textContent")
            == "replace with this"
    )


@pytest.mark.asyncio
async def test_fill_should_throw_when_element_is_not_an_input_textarea_or_contenteditable(
        page, server
):
    await page.goto(server.PREFIX + "/input/textarea.html")
    with pytest.raises(Error) as exc_info:
        await page.fill("body", "")
    assert "Element is not an <input>" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_throw_if_passed_a_non_string_value(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    with pytest.raises(Error) as exc_info:
        await page.fill("textarea", 123)
    assert "expected string, got number" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_retry_on_disabled_element(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.eval_on_selector("input", "i => i.disabled = true")
    done = []

    async def fill():
        await page.fill("input", "some value")
        done.append(True)

    promise = asyncio.create_task(fill())
    await give_it_a_chance_to_fill(page)
    assert done == []
    assert await page.evaluate("result") == ""

    await page.eval_on_selector("input", "i => i.disabled = false")
    await promise
    assert await page.evaluate("result") == "some value"


@pytest.mark.asyncio
async def test_fill_should_retry_on_readonly_element(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.eval_on_selector("textarea", "i => i.readOnly = true")
    done = []

    async def fill():
        await page.fill("textarea", "some value")
        done.append(True)

    promise = asyncio.create_task(fill())
    await give_it_a_chance_to_fill(page)
    assert done == []
    assert await page.evaluate("result") == ""

    await page.eval_on_selector("textarea", "i => i.readOnly = false")
    await promise
    assert await page.evaluate("result") == "some value"


@pytest.mark.asyncio
async def test_fill_should_retry_on_invisible_element(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.eval_on_selector("input", "i => i.style.display = 'none'")
    done = []

    async def fill():
        await page.fill("input", "some value")
        done.append(True)

    promise = asyncio.create_task(fill())
    await give_it_a_chance_to_fill(page)
    assert done == []
    assert await page.evaluate("result") == ""

    await page.eval_on_selector("input", "i => i.style.display = 'inline'")
    await promise
    assert await page.evaluate("result") == "some value"


@pytest.mark.asyncio
async def test_fill_should_be_able_to_fill_the_body(page):
    await page.set_content('<body contentEditable="true"></body>')
    await page.fill("body", "some value")
    assert await page.evaluate("document.body.textContent") == "some value"


@pytest.mark.asyncio
async def test_fill_should_fill_fixed_position_input(page):
    await page.set_content('<input style="position: fixed;" />')
    await page.fill("input", "some value")
    assert await page.evaluate("document.querySelector('input').value") == "some value"


@pytest.mark.asyncio
async def test_fill_should_be_able_to_fill_when_focus_is_in_the_wrong_frame(page):
    await page.set_content(
        """
      <div contentEditable="true"></div>
      <iframe></iframe>
    """
    )
    await page.focus("iframe")
    await page.fill("div", "some value")
    assert await page.eval_on_selector("div", "d => d.textContent") == "some value"


@pytest.mark.asyncio
async def test_fill_should_be_able_to_fill_the_input_type_number_(page):
    await page.set_content('<input id="input" type="number"></input>')
    await page.fill("input", "42")
    assert await page.evaluate("input.value") == "42"


@pytest.mark.asyncio
async def test_fill_should_be_able_to_fill_exponent_into_the_input_type_number_(page):
    await page.set_content('<input id="input" type="number"></input>')
    await page.fill("input", "-10e5")
    assert await page.evaluate("input.value") == "-10e5"


@pytest.mark.asyncio
async def test_fill_should_be_able_to_fill_input_type_number__with_empty_string(page):
    await page.set_content('<input id="input" type="number" value="123"></input>')
    await page.fill("input", "")
    assert await page.evaluate("input.value") == ""


@pytest.mark.asyncio
async def test_fill_should_not_be_able_to_fill_text_into_the_input_type_number_(page):
    await page.set_content('<input id="input" type="number"></input>')
    with pytest.raises(Error) as exc_info:
        await page.fill("input", "abc")
    assert "Cannot type text into input[type=number]" in exc_info.value.message


@pytest.mark.asyncio
async def test_fill_should_be_able_to_clear_using_fill(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.fill("input", "some value")
    assert await page.evaluate("result") == "some value"
    await page.fill("input", "")
    assert await page.evaluate("result") == ""


@pytest.mark.asyncio
async def test_close_event_should_work_with_window_close(page):
    async with page.expect_popup() as popup_info:
        await page.evaluate("window['newPage'] = window.open('about:blank')")
    popup = await popup_info.value

    async with popup.expect_event("close"):
        await page.evaluate("window['newPage'].close()")


@pytest.mark.asyncio
async def test_close_event_should_work_with_page_close(browser):
    page = await browser.new_page()
    async with page.expect_event("close"):
        await page.close()


@pytest.mark.asyncio
async def test_page_context_should_return_the_correct_browser_instance(page, browser):
    assert page.context == browser


@pytest.mark.asyncio
async def test_frame_should_respect_name(page):
    await page.set_content("<iframe name=target></iframe>")
    assert page.frame(name="bogus") is None
    frame = page.frame(name="target")
    assert frame
    assert frame == page.main_frame.child_frames[0]


@pytest.mark.asyncio
async def test_frame_should_respect_url(page, server):
    await page.set_content(f'<iframe src="{server.EMPTY_PAGE}"></iframe>')
    assert page.frame(url=re.compile(r"bogus")) is None
    assert page.frame(url=re.compile(r"empty")).url == server.EMPTY_PAGE


@pytest.mark.asyncio
async def test_press_should_work(page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")
    await page.press("textarea", "a")
    assert await page.evaluate("document.querySelector('textarea').value") == "a"


@pytest.mark.asyncio
async def test_frame_press_should_work(page):
    await page.set_content(
        '<iframe name=inner src=server.PREFIX + "/input/textarea.html"></iframe>'
    )
    frame = page.frame("inner")
    await frame.press("textarea", "a")
    assert await frame.evaluate("document.querySelector('textarea').value") == "a"


@pytest.mark.asyncio
async def test_should_emulate_reduced_motion(page):
    assert await page.evaluate(
        "matchMedia('(prefers-reduced-motion: no-preference)').matches"
    )
    await page.emulate_media(reduced_motion="reduce")
    assert await page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    assert not await page.evaluate(
        "matchMedia('(prefers-reduced-motion: no-preference)').matches"
    )
    await page.emulate_media(reduced_motion="no-preference")
    assert not await page.evaluate(
        "matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    assert await page.evaluate(
        "matchMedia('(prefers-reduced-motion: no-preference)').matches"
    )


@pytest.mark.asyncio
async def test_input_value(page: Page, server):
    await page.goto(server.PREFIX + "/input/textarea.html")

    await page.fill("input", "my-text-content")
    assert await page.input_value("input") == "my-text-content"

    await page.fill("input", "")
    assert await page.input_value("input") == ""


@pytest.mark.asyncio
async def test_drag_and_drop_helper_method(page: Page, server):
    await page.goto(server.PREFIX + "/drag-n-drop.html")
    await page.drag_and_drop("#source", "#target")
    assert (
            await page.eval_on_selector(
                "#target", "target => target.contains(document.querySelector('#source'))"
            )
            is True
    )


@pytest.mark.asyncio
async def test_drag_and_drop_with_position(page: Page, server):
    await page.goto(server.EMPTY_PAGE)
    await page.set_content(
        """
      <div style="width:100px;height:100px;background:red;" id="red">
      </div>
      <div style="width:100px;height:100px;background:blue;" id="blue">
      </div>
    """
    )
    events_handle = await page.evaluate_handle(
        """
        () => {
        const events = [];
        document.getElementById('red').addEventListener('mousedown', event => {
            events.push({
            type: 'mousedown',
            x: event.offsetX,
            y: event.offsetY,
            });
        });
        document.getElementById('blue').addEventListener('mouseup', event => {
            events.push({
            type: 'mouseup',
            x: event.offsetX,
            y: event.offsetY,
            });
        });
        return events;
        }
    """
    )
    await page.drag_and_drop(
        "#red",
        "#blue",
        source_position={"x": 34, "y": 7},
        target_position={"x": 10, "y": 20},
    )
    assert await events_handle.json_value() == [
        {"type": "mousedown", "x": 34, "y": 7},
        {"type": "mouseup", "x": 10, "y": 20},
    ]


@pytest.mark.asyncio
async def test_should_check_box_using_set_checked(page: Page):
    await page.set_content("`<input id='checkbox' type='checkbox'></input>`")
    await page.set_checked("input", True)
    assert await page.evaluate("checkbox.checked") is True
    await page.set_checked("input", False)
    assert await page.evaluate("checkbox.checked") is False


@pytest.mark.asyncio
async def test_should_set_bodysize_and_headersize(page: Page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request("*/**") as request_info:
        await page.evaluate(
            "() => fetch('./get', { method: 'POST', body: '12345'}).then(r => r.text())"
        )
    request = await request_info.value
    sizes = await request.sizes()
    assert sizes["requestBodySize"] == 5
    assert sizes["requestHeadersSize"] >= 300


@pytest.mark.asyncio
async def test_should_set_bodysize_to_0(page: Page, server):
    await page.goto(server.EMPTY_PAGE)
    async with page.expect_request("*/**") as request_info:
        await page.evaluate("() => fetch('./get').then(r => r.text())")
    request = await request_info.value
    sizes = await request.sizes()
    assert sizes["requestBodySize"] == 0
    assert sizes["requestHeadersSize"] >= 200


@pytest.mark.asyncio
async def test_should_emulate_forced_colors(page):
    assert await page.evaluate("matchMedia('(forced-colors: none)').matches")
    await page.emulate_media(forced_colors="none")
    assert await page.evaluate("matchMedia('(forced-colors: none)').matches")
    assert not await page.evaluate("matchMedia('(forced-colors: active)').matches")
    await page.emulate_media(forced_colors="active")
    assert await page.evaluate("matchMedia('(forced-colors: active)').matches")
    assert not await page.evaluate("matchMedia('(forced-colors: none)').matches")


@pytest.mark.asyncio
async def test_should_not_throw_when_continuing_while_page_is_closing(
        page: Page, server
):
    done = None

    def handle_route(route: Route) -> None:
        nonlocal done
        done = asyncio.gather(route.continue_(), page.close())

    await page.route("**/*", handle_route)
    with pytest.raises(Error):
        await page.goto(server.EMPTY_PAGE)
    await done


@pytest.mark.asyncio
async def test_should_not_throw_when_continuing_after_page_is_closed(
        page: Page, server
):
    done = asyncio.Future()

    async def handle_route(route: Route) -> None:
        await page.close()
        await route.continue_()
        nonlocal done
        done.set_result(True)

    await page.route("**/*", handle_route)
    with pytest.raises(Error):
        await page.goto(server.EMPTY_PAGE)
    await done


@pytest.mark.asyncio
async def test_expose_binding_should_serialize_cycles(page: Page):
    binding_values = []

    def binding(source, o):
        binding_values.append(o)

    await page.expose_binding("log", lambda source, o: binding(source, o))
    await page.evaluate("const a = {}; a.b = a; window.log(a)")
    assert binding_values[0]["b"] == binding_values[0]
