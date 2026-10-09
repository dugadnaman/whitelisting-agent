"""Real behavior-table reader against synthetic, offline Chromium DOM fixtures.

Run: python -m pytest tests/test_apparel_attribution_behavior_grid.py -q
Requires Playwright and its bundled Chromium. Alternatively, explicitly set
APPAREL_TEST_CHROMIUM_EXECUTABLE to a local Chromium/Chrome binary, for example
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome on macOS.
No persistent profile, CDP connection, credentials, or external requests are used.
"""
import asyncio
from contextlib import asynccontextmanager
import importlib
import os
from pathlib import Path
import socket
import sys

import pytest


@pytest.fixture
def behavior_reader(monkeypatch):
    pytest.importorskip("playwright.async_api", reason="These offline browser regressions require Playwright")
    worker = Path(__file__).resolve().parents[1] / "agents" / "apparel-attribution" / "Backend"
    monkeypatch.syspath_prepend(str(worker))
    # The worker's absolute app imports must not replace another suite's app.
    previous = {name: module for name, module in sys.modules.items()
                if name == "app" or name.startswith("app.")}
    for name in previous:
        del sys.modules[name]
    try:
        yield importlib.import_module("app.services.moengage_browser_service")
    finally:
        for name in tuple(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(previous)


@pytest.fixture
def chromium_page():
    @asynccontextmanager
    async def open_page(*, args=None):
        from playwright.async_api import Error, async_playwright

        async with async_playwright() as playwright:
            executable = os.environ.get("APPAREL_TEST_CHROMIUM_EXECUTABLE")
            try:
                browser = await playwright.chromium.launch(
                    headless=True, executable_path=executable, args=args,
                )
            except Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Install Playwright Chromium or set APPAREL_TEST_CHROMIUM_EXECUTABLE to a local binary")
                raise
            try:
                context = await browser.new_context(offline=True, service_workers="block")
                yield await context.new_page()
            finally:
                await browser.close()

    return open_page


def _grid_html(label_layout, summary_label="Average"):
    # Deliberately synthetic numbers: neither 20 (average) nor 40 (summary)
    # may be added to the daily values 11 + 29.
    event_cell = '<div role="gridcell" col-id="event">Order Completed</div>'
    pinned = (f'<div class="ag-pinned-left-cols-container"><div role="row" row-index="0">'
              f'{event_cell}</div></div>') if label_layout == "pinned" else ""
    inline = event_cell if label_layout == "inline" else ""
    summary_value = 20 if summary_label == "Average" else 40
    return f"""
        <div class="ag-root">
          <div class="ag-header">
            <div class="ag-header-cell" col-id="event">Event</div>
            <div class="ag-header-cell" col-id="summary">{summary_label}</div>
            <div class="ag-header-cell" col-id="day-1">01 Oct 2026</div>
            <div class="ag-header-cell" col-id="day-2">02 Oct 2026</div>
          </div>
          {pinned}
          <div class="ag-center-cols-container">
            <div role="row" row-index="0">
              {inline}
              <div role="gridcell" col-id="summary">{summary_value}</div>
              <div role="gridcell" col-id="day-1">11</div>
              <div role="gridcell" col-id="day-2">29</div>
            </div>
          </div>
        </div>
    """


@pytest.mark.parametrize("label_layout", ["inline", "pinned"])
@pytest.mark.parametrize("summary_label", ["Average", "Total"])
def test_two_day_total_excludes_summary_for_inline_and_pinned_labels(
    behavior_reader, chromium_page, label_layout, summary_label,
):
    async def check():
        async with chromium_page() as page:
            await page.set_content(_grid_html(label_layout, summary_label))
            total = await behavior_reader.MoEngageBrowserService._read_behavior_total(
                page, "Order Completed", expected_days=2,
            )
            assert total == 40

    asyncio.run(check())


@pytest.mark.parametrize("missing_part", ["header", "cell"])
def test_incomplete_daily_columns_raise_instead_of_returning_partial_total(
    behavior_reader, chromium_page, missing_part,
):
    async def check():
        async with chromium_page() as page:
            await page.set_content(_grid_html("inline"))
            selector = ".ag-header-cell" if missing_part == "header" else "[role='gridcell']"
            await page.locator(f"{selector}[col-id='day-2']").evaluate("el => el.remove()")
            with pytest.raises(behavior_reader.BrowserAutomationError):
                await behavior_reader.MoEngageBrowserService._read_behavior_total(
                    page, "Order Completed", expected_days=2,
                )

    asyncio.run(check())


def test_horizontal_virtualization_counts_each_date_column_once(behavior_reader, chromium_page):
    async def check():
        async with chromium_page() as page:
            await page.set_content(_grid_html("pinned"))
            await page.evaluate("""() => {
                const grid = document.querySelector('.ag-root');
                const viewport = document.createElement('div');
                viewport.className = 'ag-body-horizontal-scroll-viewport';
                viewport.style.cssText = 'width:200px;height:12px;overflow-x:scroll';
                viewport.innerHTML = '<div style="width:600px;height:1px"></div>';
                grid.append(viewport);
                const headers = grid.querySelector('.ag-header');
                const row = grid.querySelector('.ag-center-cols-container [role="row"]');
                const days = [
                    ['day-1', '01 Oct 2026', 11],
                    ['day-2', '02 Oct 2026', 29],
                ];
                window.renderedColumns = [];
                function render() {
                    const visible = viewport.scrollLeft < 160 ? days.slice(0, 1)
                        : viewport.scrollLeft < 320 ? days : days.slice(1);
                    headers.innerHTML = '<div class="ag-header-cell" col-id="summary">Average</div>'
                        + visible.map(([id, label]) =>
                            `<div class="ag-header-cell" col-id="${id}">${label}</div>`).join('');
                    row.innerHTML = '<div role="gridcell" col-id="summary">20</div>'
                        + visible.map(([id, , value]) =>
                            `<div role="gridcell" col-id="${id}">${value}</div>`).join('');
                    window.renderedColumns.push(visible.map(([id]) => id));
                }
                viewport.addEventListener('scroll', render);
                render();
            }""")
            total = await behavior_reader.MoEngageBrowserService._read_behavior_total(
                page, "Order Completed", expected_days=2,
            )
            assert total == 40
            # Prove this fixture actually recycled overlapping column windows.
            windows = await page.evaluate("window.renderedColumns")
            assert windows[0] == ["day-1"]
            assert ["day-1", "day-2"] in windows
            assert windows[-1] == ["day-2"]

    asyncio.run(check())


def test_transaction_operator_switches_both_directions_without_touching_other_events(
    behavior_reader, chromium_page,
):
    async def check():
        async with chromium_page() as page:
            await page.set_content("""
                <div class="mds-event" id="other">
                  <div class="mds-event__event-name">
                    <span class="mds-dropdown__trigger__inner__single--value">Order Completed</span>
                  </div>
                  <span>does not exist</span>
                </div>
                <div class="mds-event" id="sale">
                  <div class="mds-event__event-name">
                    <span class="mds-dropdown__trigger__inner__single--value">Sale_Array</span><i>arrow_drop_down</i>
                  </div>
                  <div class="mds-attr">
                    <div class="mds-attr__name"><div class="mds-dropdown">
                      <span class="mds-dropdown__trigger__inner__single--value">Txn_Channel</span>
                    </div></div>
                    <div class="mds-dropdown"><button class="mds-dropdown__trigger"
                      onclick="document.querySelector('#options').hidden=false">
                      <span id="condition" class="mds-dropdown__trigger__inner__single--value">does not exist</span>
                    </button></div>
                  </div>
                </div>
                <div id="options" hidden>
                  <button class="mds-dropdown__popup__list__item" title="exists"
                    onclick="document.querySelector('#condition').textContent=this.title;this.parentElement.hidden=true">exists</button>
                  <button class="mds-dropdown__popup__list__item" title="does not exist"
                    onclick="document.querySelector('#condition').textContent=this.title;this.parentElement.hidden=true">does not exist</button>
                </div>
            """)
            service = object.__new__(behavior_reader.MoEngageBrowserService)
            for condition in ["exists", "does not exist"]:
                await service._set_transaction_channel(page, condition)
                assert await page.locator("#condition").inner_text() == condition
                assert await page.locator("#other > span").inner_text() == "does not exist"

    asyncio.run(check())


def test_missing_catalog_attribute_does_not_create_an_invented_value(
    behavior_reader, chromium_page,
):
    async def check():
        async with chromium_page() as page:
            await page.set_content("""
                <div class="mds-dropdown__popup">
                  <input placeholder="Search to select"
                    onkeydown="if(event.key==='Enter')document.querySelector('#invented').textContent=this.value">
                  <span>Your search did not match anything.</span>
                </div>
                <output id="invented"></output>
            """)
            with pytest.raises(behavior_reader.BrowserAutomationError):
                await behavior_reader.MoEngageBrowserService._select_open_option(
                    page, "Txn_Channel", allow_create=False,
                )
            assert await page.locator("#invented").inner_text() == ""

    asyncio.run(check())


def test_browser_recovery_preserves_chromium_and_unrelated_tabs(
    behavior_reader, chromium_page, tmp_path,
):
    async def check():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        async with chromium_page(args=[f"--remote-debugging-port={port}"]) as retained_page:
            await retained_page.set_content("<output>Retained browser state</output>")
            service = behavior_reader.MoEngageBrowserService(
                tmp_path, "https://dashboard.moengage.com/", {},
                remote_cdp_url=f"http://127.0.0.1:{port}",
            )
            try:
                await service._ensure_browser()
                endpoint = await service._remote_websocket_url()
                stopped_driver = service.playwright
                await stopped_driver.stop()
                await service._ensure_browser()
                assert service.playwright is not stopped_driver
                assert await service.page.evaluate("6 * 7") == 42
                assert await service._remote_websocket_url() == endpoint
                assert await retained_page.locator("output").inner_text() == "Retained browser state"
                unrelated_tab = service.page
                await unrelated_tab.goto("data:text/html,<title>Unrelated portal</title>")
                await service._ensure_browser()
                await service.page.set_content("<title>Automation report</title>")
                assert await unrelated_tab.title() == "Unrelated portal"
                assert await service.page.title() == "Automation report"
            finally:
                await service.close()

    asyncio.run(check())


def test_report_navigation_waits_for_dashboard_load(
    behavior_reader, chromium_page, tmp_path,
):
    async def check():
        async with chromium_page() as page:
            origin = "https://dashboard.moengage.com"
            query_url = f"{origin}/v4/analytics/v2/behavior?did=vs-report&chartId=customers"

            async def serve(route):
                if route.request.url.endswith("/workspace-ready.js"):
                    await asyncio.sleep(0.5)
                    await route.fulfill(
                        content_type="application/javascript",
                        body='sessionStorage.setItem("workspaceReady", "yes");',
                    )
                    return
                if "/behavior" in route.request.url:
                    html = """
                        <main id="report">Loading report</main>
                        <script>
                          if (sessionStorage.getItem("workspaceReady") === "yes")
                            document.getElementById("report").textContent =
                              "Number of Purchased Customers";
                        </script>
                    """
                else:
                    html = """
                        <button>Create New</button>
                        <span hidden>VS_IN</span>
                        <span>VS_IN</span>
                        <script>sessionStorage.removeItem("workspaceReady");</script>
                        <script async src="/workspace-ready.js"></script>
                    """
                await route.fulfill(content_type="text/html", body=html)

            await page.route("**/*", serve)
            service = behavior_reader.MoEngageBrowserService(
                tmp_path, origin,
                {"workspace_map": {"VS": "VS_IN"}, "query_url_map": {"VS": query_url}},
            )
            await page.goto(origin, wait_until="domcontentloaded")
            report_open = await service._switch_workspace(page, "VS")
            if not report_open:
                await service._goto_behavior_report(page, query_url)
            await asyncio.wait_for(service._wait_for_behavior_report(page), timeout=2)
            assert await page.get_by_text("Number of Purchased Customers", exact=True).is_visible()

    asyncio.run(check())
