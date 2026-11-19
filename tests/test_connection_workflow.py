"""Exercise connection-first entry and recovery against the rendered React surface."""

import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def workflow_source():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    source = subprocess.run(
        ["node", "-e", """
        const ts = require('typescript'), fs = require('node:fs');
        process.stdout.write(ts.transpileModule(fs.readFileSync(process.argv[1], 'utf8'), {
            compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}
        }).outputText);
        """, str(frontend / "components/connection-workflow.tsx")],
        cwd=frontend, capture_output=True, text=True, check=True,
    ).stdout
    return frontend, source


@pytest.fixture
def flow(workflow_source):
    frontend, compiled = workflow_source
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.context.route("https://connection.test/**", lambda route: route.fulfill(
            content_type="text/html", body='<!doctype html><div id="root"></div>',
        ))
        page.goto("https://connection.test/submit")
        for package, filename in (("react", "react.development.js"), ("react-dom", "react-dom.development.js")):
            page.add_script_tag(content=(frontend / "node_modules" / package / "umd" / filename).read_text())
        page.add_script_tag(content="""(() => {
            window.result = {ok: false, message: 'This account’s portal session has expired.'};
            window.scope = {account: 'tcl_promo', channel: 'whatsapp'};
            window.checks = []; window.submissions = 0; window.checkError = null;
            const exports = {};
            const require = name => {
                if (name === 'react') return React;
                if (name === 'react/jsx-runtime') return {
                    jsx: (type, props, key) => React.createElement(type, {...props, key}),
                    jsxs: (type, props, key) => React.createElement(type, {...props, key})
                };
                if (name === '@/lib/context') return {useApp: () => ({...window.scope,
                    currentUser: {id: 'operator', tenant_id: 'tata'}, getAccountLabel: value => value})};
                if (name === '@/lib/destination') return {destinationLabel: (account, channel) => `${account} · ${channel}`};
                if (name === '@/lib/api') return {
                    canAccessAccount: (_user, account) => account.startsWith('tcl_'),
                    testCredentials: async (account, channel) => {
                        window.checks.push({account, channel});
                        if (window.defer) return new Promise(resolve => { window.resolveCheck = resolve; });
                        if (window.checkError) throw new Error(window.checkError);
                        return window.result;
                    }
                };
                if (name === '@/components/KarixAuthSync') return {default: props =>
                    React.createElement('button', {onClick: props.onSessionChanged}, 'Capture renewed session')};
                throw new Error('Unexpected import: ' + name);
            };
        """ + compiled + """
            window.workflow = exports;
            function Draft() {
                const connection = exports.useWhitelistingConnection();
                const [body, setBody] = React.useState('Original copy');
                const [selected, setSelected] = React.useState(false);
                return React.createElement('section', {},
                    React.createElement('label', {}, 'Template copy', React.createElement('input', {
                        value: body, onChange: event => setBody(event.target.value)})),
                    React.createElement('label', {}, 'Select template', React.createElement('input', {
                        type: 'checkbox', checked: selected, onChange: event => setSelected(event.target.checked)})),
                    React.createElement('label', {}, 'Source spreadsheet', React.createElement('input', {type: 'file'})),
                    React.createElement('button', {onClick: async () => {
                        if (await connection.ensureConnected()) window.submissions++;
                    }}, 'Confirm whitelist')
                );
            }
            const root = ReactDOM.createRoot(document.getElementById('root'));
            window.renderWorkflow = (focused = false) => root.render(focused
                ? React.createElement(exports.FocusedConnectionSetup, {...window.scope, key: window.scope.account})
                : React.createElement(exports.default, {enabled: true, key: `${window.scope.account}:${window.scope.channel}`},
                    React.createElement(Draft)));
            window.renderWorkflow();
        })();""")
        try:
            yield page
        finally:
            browser.close()


def connect(page):
    expect(page.get_by_role("heading", name="Connect before whitelisting")).to_be_visible()
    page.evaluate("window.result = {ok: true, message: 'Verified the exact provider inventory.'}")
    page.get_by_role("button", name="Retry connection check", exact=True).click()
    expect(page.get_by_label("Template copy")).to_be_visible()


def test_initial_gate_requires_fresh_provider_verification(flow):
    expect(flow.get_by_role("heading", name="Connect before whitelisting")).to_be_visible()
    expect(flow.get_by_label("Source spreadsheet")).not_to_be_visible()
    assert flow.evaluate("window.checks") == [{"account": "tcl_promo", "channel": "whatsapp"}]
    flow.evaluate("window.result = {ok: 'true', message: 'Paired but malformed'}")
    flow.get_by_role("button", name="Retry connection check", exact=True).click()
    expect(flow.get_by_role("alert")).to_contain_text("unexpected response")
    expect(flow.get_by_label("Source spreadsheet")).not_to_be_visible()
    assert flow.evaluate("window.submissions") == 0


def test_expiry_preserves_file_edits_and_selection_without_replay(flow):
    connect(flow)
    flow.get_by_label("Template copy").fill("Reviewed exact customer copy")
    flow.get_by_label("Select template").check()
    flow.get_by_label("Source spreadsheet").set_input_files({
        "name": "client-brief.csv", "mimeType": "text/csv", "buffer": b"name,body\natt_offer,exact copy\n",
    })
    flow.evaluate("window.result = {ok: false, message: 'Portal session expired during review.'}")
    flow.get_by_role("button", name="Confirm whitelist", exact=True).click()
    expect(flow.get_by_role("dialog")).to_be_visible()
    assert flow.evaluate("window.submissions") == 0
    flow.evaluate("window.result = {ok: true, message: 'Renewed session verified.'}")
    flow.get_by_role("button", name="Retry connection check", exact=True).click()
    expect(flow.get_by_role("dialog")).not_to_be_visible()
    expect(flow.get_by_label("Template copy")).to_have_value("Reviewed exact customer copy")
    expect(flow.get_by_label("Select template")).to_be_checked()
    assert flow.get_by_label("Source spreadsheet").evaluate("async input => [input.files[0].name, await input.files[0].text()]") == [
        "client-brief.csv", "name,body\natt_offer,exact copy\n",
    ]
    assert flow.evaluate("window.submissions") == 0
    flow.get_by_role("button", name="Confirm whitelist", exact=True).click()
    flow.wait_for_function("window.submissions === 1")
    assert len(flow.evaluate("window.checks")) == 5


def test_network_failure_is_not_reported_as_disconnected(flow):
    connect(flow)
    flow.evaluate("window.checkError = 'Network unavailable. Retry connection check.'")
    flow.get_by_role("button", name="Confirm whitelist", exact=True).click()
    expect(flow.get_by_role("dialog")).to_contain_text("Network unavailable")
    expect(flow.get_by_role("dialog")).not_to_contain_text("You are disconnected")
    assert flow.evaluate("window.submissions") == 0
    flow.get_by_role("button", name="Back to draft").click()
    expect(flow.get_by_label("Template copy")).to_have_value("Original copy")


def test_late_old_scope_check_cannot_unlock_new_destination(flow):
    connect(flow)
    flow.evaluate("window.defer = true")
    flow.get_by_role("button", name="Confirm whitelist", exact=True).click()
    flow.wait_for_function("typeof window.resolveCheck === 'function'")
    flow.evaluate("""() => {
        window.oldResolve = window.resolveCheck;
        window.defer = false;
        window.result = {ok: false, message: 'Wealth needs its own connection.'};
        window.scope = {account: 'tcl_wealth', channel: 'rcs'};
        window.renderWorkflow();
    }""")
    expect(flow.get_by_role("heading", name="Connect before whitelisting")).to_be_visible()
    flow.evaluate("window.oldResolve({ok: true, message: 'Old account was valid'})")
    expect(flow.get_by_label("Template copy")).not_to_be_visible()
    assert flow.evaluate("window.submissions") == 0
    assert flow.evaluate("window.checks.at(-1)") == {"account": "tcl_wealth", "channel": "rcs"}


def test_setup_window_keeps_draft_and_messages_require_fresh_scoped_check(flow):
    connect(flow)
    flow.get_by_label("Template copy").fill("Do not discard")
    flow.get_by_role("button", name="Manage connection").click()
    with flow.expect_popup() as opened:
        flow.get_by_role("button", name="Connect this account", exact=True).click()
    popup = opened.value
    popup.wait_for_url("**/settings?connect=1&account=tcl_promo&channel=whatsapp")
    assert flow.url == "https://connection.test/submit"
    flow.evaluate("window.result = {ok: false, message: 'Provider still rejects this saved session.'}")
    flow.wait_for_function("document.querySelector('dialog').open")
    before = len(flow.evaluate("window.checks"))
    popup.evaluate("opener.postMessage({type:'KARIX_CONNECTION_UPDATED', account:'bajaj', channel:'whatsapp'}, location.origin)")
    flow.wait_for_timeout(100)
    assert len(flow.evaluate("window.checks")) == before
    popup.evaluate("opener.postMessage({type:'KARIX_CONNECTION_UPDATED', account:'tcl_promo', channel:'whatsapp'}, location.origin)")
    expect(flow.get_by_role("dialog")).to_contain_text("Provider still rejects")
    assert flow.evaluate("window.submissions") == 0
    flow.evaluate("window.result = {ok: true, message: 'Scoped live check passed'}")
    popup.evaluate("opener.postMessage({type:'KARIX_CONNECTION_UPDATED', account:'tcl_promo', channel:'whatsapp'}, location.origin)")
    expect(flow.get_by_role("dialog")).not_to_be_visible()
    expect(flow.get_by_label("Template copy")).to_have_value("Do not discard")
    assert flow.evaluate("window.submissions") == 0


def test_focused_setup_never_changes_workspace_destination(flow):
    flow.evaluate("window.scope = {account: 'tcl_promo', channel: 'rcs'}; window.renderWorkflow(true)")
    expect(flow.get_by_role("heading", name="Connect tcl_promo · rcs")).to_be_visible()
    flow.get_by_role("button", name="Capture renewed session").click()
    flow.wait_for_function("window.checks.at(-1).channel === 'rcs'")
    assert flow.evaluate("window.scope") == {"account": "tcl_promo", "channel": "rcs"}
    assert flow.evaluate("window.submissions") == 0
