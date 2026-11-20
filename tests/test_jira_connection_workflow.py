"""Mount the real Jira page and persistence helpers; exercise its connection seam.

Run with the frontend npm dependencies and Playwright Chromium installed. Provider
and extension verification belong to the shared ConnectionWorkflow browser tests.
"""

import json
from pathlib import Path
import subprocess

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def jira_modules():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    result = subprocess.run(
        ["node", "-e", r"""
        const ts = require('typescript');
        const fs = require('node:fs');
        const paths = ['app/briefs/page.tsx', 'app/page.tsx', 'components/sms-dlt.tsx',
            ...fs.readdirSync('lib').filter(p => p.endsWith('.ts')).map(p => 'lib/' + p)];
        process.stdout.write(JSON.stringify(Object.fromEntries(paths.map(path => [
            '@/' + path.replace(/\.tsx?$/, ''),
            ts.transpileModule(fs.readFileSync(path, 'utf8'), {compilerOptions: {
                module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX
            }}).outputText
        ]))));
        """], cwd=frontend, check=True, capture_output=True, text=True,
    )
    return frontend, json.loads(result.stdout)


@pytest.fixture
def jira_page(jira_modules):
    frontend, modules = jira_modules
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("Install the browser with: playwright install chromium")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("https://jira-review.test/**", lambda route: route.fulfill(
            content_type="text/html", body='<!doctype html><div id="root"></div>',
        ))
        page.goto("https://jira-review.test/briefs")
        for package, filename in (("react", "react.development.js"), ("react-dom", "react-dom.development.js")):
            page.add_script_tag(content=(frontend / "node_modules" / package / "umd" / filename).read_text())
        page.evaluate("""modules => {
            window.sources = modules;
            window.mountJira = channel => {
                const account = channel === 'sms' ? 'tata' : 'tcl_promo';
                const options = window.mountOptions || {};
                const draft = index => ({template_name: 'att_review_' + index,
                    body: 'Edited exact copy ' + index, text: 'Edited exact copy ' + index,
                    category: 'MARKETING', language: 'en', header_type: 'NONE',
                    button_type: 'NONE', card_title: 'Reviewed title ' + index,
                    action_type: 'URL', action_label: '', action_url: '',
                    variables: [], raw_source: 'Original source paragraph ' + index, template_type: 'text',
                    ...(index === 0 ? {source_file: 'campaign-copy.xlsx', source_sheet: 'Approved copy', source_cell: 'D7'} : {}),
                    media_file: '/reviewed/creative-' + index + '.png', media_filename: 'reviewed-' + index + '.png',
                    char_count: 19, variant: 'Reviewed'});
                const drafts = [draft(0), draft(1)];
                const brief = {issue_key: 'TCN-407', summary: 'Review fixture', account,
                    assignee: 'Operator', reporter: 'Reporter', status: 'Open', attachments_mapped: [],
                    comments: [], whatsapp_templates: [], rcs_templates: [], sms_templates: [],
                    channel_counts: {whatsapp: 0, rcs: 0, sms: 0, email: 0, push: 0, total: 2}};
                brief[channel + '_templates'] = drafts.map(draft => ({...draft,
                    body: 'Original Jira copy', text: 'Original Jira copy', card_title: 'Original title',
                    media_file: '/original/creative.png', media_filename: 'original.png'}));
                brief.channel_counts[channel] = 2;
                const cache = {briefs_selected_key: brief.issue_key, briefs_data: brief, briefs_active_tab: channel,
                    briefs_wa_templates: channel === 'whatsapp' ? drafts : [],
                    briefs_rcs_templates: channel === 'rcs' ? drafts : [],
                    briefs_sms_templates: channel === 'sms' ? drafts : [],
                    briefs_selected_wa: channel === 'whatsapp' ? [1] : [],
                    briefs_selected_rcs: channel === 'rcs' ? [1] : [],
                    briefs_selected_sms: channel === 'sms' ? [1] : []};
                if (options.registered) cache.briefs_registrations = [{
                    account, channel, issueKey: brief.issue_key, template_name: drafts[1].template_name,
                    draftSignature: JSON.stringify(drafts[1]), provider_ref_id: 'provider-407-1',
                    source_ref: 'TCN-407_att_review_1', status: 'submitted', approval_status: 'pending',
                }];
                Object.entries(cache).forEach(([key, value]) => sessionStorage.setItem('karix_tab:' + key, JSON.stringify(value)));
                window.calls = {loads: 0, loadKeys: [], checks: 0, posts: [], reconnects: 0, statusReads: []};
                window.statusRows = [{source_ref: 'TCN-407_att_review_1', template_name: 'att_review_1',
                    provider_ref_id: 'provider-407-1', status: 'submitted', approval_status: 'pending'}];
                window.holdStatus = Boolean(options.holdStatus);
                window.pendingStatuses = [];
                window.statusTimers = new Map();
                let timerId = 1;
                window.setInterval = callback => { const id = timerId++; window.statusTimers.set(id, callback); return id; };
                window.clearInterval = id => window.statusTimers.delete(id);
                window.tickStatuses = async () => {
                    for (const callback of [...window.statusTimers.values()]) callback();
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                };
                window.connectionResult = true;
                window.holdCheck = false;
                window.holdBrief = false;
                window.app = {account, channel, user: 'Operator', accounts: [],
                    getAccountLabel: value => value, setDestination: () => false};
                const api = {
                    fetchJiraProjects: async () => [],
                    fetchJiraIssues: async () => ['TCN-407', 'TCN-408'].map(key => ({
                        key, summary: key === brief.issue_key ? brief.summary : 'Other fixture',
                        assignee: 'Operator', status: 'Open', attachment_count: 0,
                    })),
                    fetchMoEngageDraftWorkspaces: async () => ({workspaces: []}),
                    fetchTemplates: async params => {
                        window.calls.statusReads.push(params);
                        if (window.statusError) throw new Error(window.statusError);
                        return window.holdStatus ? await new Promise(resolve => window.pendingStatuses.push(resolve))
                            : structuredClone(window.statusRows);
                    },
                    fetchJiraBrief: async key => {
                        window.calls.loads++;
                        window.calls.loadKeys.push(key);
                        const data = {...structuredClone(brief), issue_key: key,
                            summary: key === brief.issue_key ? brief.summary : 'Other fixture'};
                        return window.holdBrief
                            ? await new Promise(resolve => { window.resolveBrief = () => resolve(data); }) : data;
                    },
                    previewJiraDrafts: async payload => ({whatsapp_templates: payload.whatsapp_templates.map(() => ({})),
                        rcs_templates: payload.rcs_templates.map(() => ({}))}),
                    submitJiraBrief: async (...args) => { window.calls.posts.push(args); return {
                        account: args[5], channels: args[1],
                        whatsapp_submitted: args[3].map(draft => ({template_name: draft.template_name,
                            source_ref: 'TCN-407_' + draft.template_name, provider_ref_id: 'provider-407-1',
                            status: 'submitted', approval_status: 'pending'})),
                        rcs_submitted: args[4].map(draft => ({template_name: draft.template_name,
                            source_ref: 'TCN-407_' + draft.template_name, template_id: 'provider-407-1',
                            status: 'submitted', approval_status: 'pending'}))}; }
                };
                const hook = {useWhitelistingConnection: () => ({connected: true,
                    reconnect: () => { window.calls.reconnects++; },
                    ensureConnected: async () => {
                        window.calls.checks++;
                        const result = window.holdCheck ? await new Promise(resolve => { window.resolveCheck = resolve; }) : window.connectionResult;
                        if (!result) window.calls.reconnects++;
                        return result;
                    }})};
                const modules = {};
                function load(name, from = '') {
                    if (name === 'react') return React;
                    if (name === 'react/jsx-runtime') return {
                        Fragment: React.Fragment,
                        jsx: (type, props, key) => React.createElement(type, {...props, key}),
                        jsxs: (type, props, key) => React.createElement(type, {...props, key})};
                    if (name.startsWith('.')) name = from.slice(0, from.lastIndexOf('/') + 1) + name.replace(/^\.\//, '');
                    if (name === '@/lib/api') return api;
                    if (name === '@/lib/context') return {useApp: () => window.app,
                        getRcsDetails: () => ({botId: 'reviewed-bot', botName: 'Reviewed bot', name: account})};
                    if (name === '@/components/connection-workflow') return hook;
                    if (name === '@/components/jira-creative') return {JiraCreativeImage: () => null, JiraCreativeDownload: () => null};
                    if (name === '@/components/KarixAuthSync') return {default: () => null};
                    if (modules[name]) return modules[name].exports;
                    if (!window.sources[name]) throw new Error('Unexpected import: ' + name);
                    const module = {exports: {}};
                    modules[name] = module;
                    new Function('require', 'exports', 'module', window.sources[name])(child => load(child, name), module.exports, module);
                    if (name === '@/components/sms-dlt') module.exports.SmsDltReview = props =>
                        React.createElement('pre', {'data-testid': 'sms-review'}, JSON.stringify(props.initialDrafts));
                    return module.exports;
                }
                window.tabState = load('@/lib/tab-state');
                const Page = load('@/app/briefs/page').default;
                window.root = ReactDOM.createRoot(document.getElementById('root'));
                window.renderJira = () => window.root.render(React.createElement(Page));
                window.remountJira = () => {
                    window.root.unmount();
                    window.root = ReactDOM.createRoot(document.getElementById('root'));
                    window.renderJira();
                };
                window.renderJira();
                window.releaseCheck = async result => {
                    window.resolveCheck(result);
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                };
            };
        }""", modules)
        try:
            yield page
        finally:
            browser.close()
            assert not page_errors, "Uncaught Jira page errors:\n" + "\n".join(page_errors)


def mount(page, channel):
    page.evaluate("channel => window.mountJira(channel)", channel)
    expect(page.get_by_role("heading", name="Review fixture", exact=True)).to_be_visible()
    if channel != "sms":
        expect(page.get_by_role("button", name="Review & whitelist (1)", exact=True)).to_be_enabled()


@pytest.mark.parametrize("channel", ["whatsapp", "rcs", "sms"])
def test_restored_channel_drafts_survive_return_and_explicit_reload_cancel(jira_page, channel):
    page = jira_page
    mount(page, channel)
    before = page.evaluate("() => ({...sessionStorage})")
    page.evaluate("() => window.remountJira()")
    expect(page.get_by_role("heading", name="Review fixture", exact=True)).to_be_visible()
    assert page.evaluate("() => window.calls.loads") == 0
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reload from Jira", exact=True).click()
    assert page.evaluate("() => window.calls.loads") == 0
    assert page.evaluate("() => ({...sessionStorage})") == before
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reload from Jira", exact=True).click()
    expect(page.get_by_role("heading", name="Review fixture", exact=True)).to_be_visible()
    page.wait_for_function("window.calls.loads === 1")
    page.wait_for_function("""channel => JSON.parse(sessionStorage.getItem(
        'karix_tab:briefs_' + (channel === 'whatsapp' ? 'wa' : channel) + '_templates'
    ))[0][channel === 'sms' ? 'text' : 'body'] === 'Original Jira copy'""", arg=channel)


@pytest.mark.parametrize("channel", ["rcs", "sms"])
def test_return_to_cached_ticket_cancels_loading_without_replacing_edits(jira_page, channel):
    page = jira_page
    mount(page, channel)
    before = page.evaluate("() => ({...sessionStorage})")
    page.evaluate("() => { window.holdBrief = true; }")
    page.get_by_role("button").filter(has=page.get_by_text("TCN-408", exact=True)).click()
    page.wait_for_function("typeof window.resolveBrief === 'function'")
    expect(page.get_by_role("status").filter(has_text="Loading brief…")).to_be_visible()
    page.get_by_role("button").filter(has=page.get_by_text("TCN-407", exact=True)).click()
    expect(page.get_by_role("heading", name="Review fixture", exact=True)).to_be_visible()
    page.evaluate("""async () => {
        window.resolveBrief();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    expect(page.get_by_role("heading", name="Review fixture", exact=True)).to_be_visible()
    assert page.evaluate("() => window.calls.loadKeys") == ["TCN-408"]
    assert page.evaluate("() => ({...sessionStorage})") == before


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_expiry_before_confirmation_preserves_drafts_without_auto_continuing(jira_page, channel):
    page = jira_page
    mount(page, channel)
    before = page.evaluate("() => ({...sessionStorage})")
    review = page.get_by_role("button", name="Review & whitelist (1)", exact=True)
    page.evaluate("() => { window.connectionResult = false; }")
    review.click()
    expect(review).to_be_enabled()
    expect(page.get_by_role("dialog", name="Confirm whitelisting", exact=True)).to_have_count(0)
    assert page.evaluate("() => window.calls.reconnects") == 1
    assert page.evaluate("() => ({...sessionStorage})") == before
    page.evaluate("() => { window.connectionResult = true; window.dispatchEvent(new Event('focus')); }")
    expect(page.get_by_role("dialog", name="Confirm whitelisting", exact=True)).to_have_count(0)
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.loads") == 0
    review.click()
    expect(page.get_by_role("dialog", name="Confirm whitelisting", exact=True)).to_be_visible()
    assert page.evaluate("() => window.calls.checks") == 2


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_expiry_keeps_confirmation_and_requires_another_deliberate_click(jira_page, channel):
    page = jira_page
    mount(page, channel)
    page.get_by_role("button", name="Review & whitelist (1)", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Confirm whitelisting", exact=True)
    expect(confirmation).to_be_visible()
    assert page.evaluate("() => window.calls.checks") == 1
    before = page.evaluate("() => ({...sessionStorage})")
    page.evaluate("() => { window.connectionResult = false; }")
    confirmation.get_by_role("button", name="Confirm & Whitelist", exact=False).click()
    expect(confirmation.get_by_role("button", name="Confirm & Whitelist", exact=False)).to_be_enabled()
    expect(confirmation).to_be_visible()
    assert page.evaluate("() => window.calls.reconnects") == 1
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => ({...sessionStorage})") == before
    page.evaluate("() => { window.connectionResult = true; window.dispatchEvent(new Event('focus')); }")
    expect(confirmation).to_be_visible()
    assert page.evaluate("() => window.calls.posts") == []
    confirmation.get_by_role("button", name="Confirm & Whitelist", exact=False).click()
    expect(confirmation).to_have_count(0)
    page.wait_for_function("window.calls.posts.length === 1")
    args = page.evaluate("() => window.calls.posts[0]")
    submitted = args[3] if channel == "whatsapp" else args[4]
    assert args[0] == "TCN-407" and args[1] == [channel] and args[5] == "tcl_promo"
    assert len(submitted) == 1 and submitted[0]["template_name"] == "att_review_1"
    assert submitted[0]["body"] == "Edited exact copy 1"
    assert submitted[0]["media_file"] == "/reviewed/creative-1.png"
    assert page.evaluate("() => window.calls.loads") == 0
    assert page.evaluate("() => window.calls.checks") == 3


def change_workflow(page, change):
    if change in ("destination", "channel"):
        page.evaluate("""change => {
            window.app = {...window.app, ...(change === 'destination' ? {account: 'bajaj'} : {channel: 'rcs'})};
            ReactDOM.flushSync(() => window.renderJira());
        }""", change)
    elif change == "selection":
        page.get_by_role("checkbox", name="Select att_review_0 for whitelisting", exact=True).check()
    elif change == "source":
        page.get_by_role("button", name="Edit", exact=True).nth(1).click()
        page.locator("textarea").fill("Copy changed during connection verification")
    elif change == "ticket":
        page.get_by_role("button").filter(has=page.get_by_text("TCN-408", exact=True)).click()
        expect(page.get_by_role("heading", name="Other fixture", exact=True)).to_be_visible()
    elif change == "comments":
        page.get_by_role("button").filter(has=page.get_by_text("Comments", exact=True)).click()
    elif change == "moengage":
        page.get_by_text("More tools", exact=True).click()
        page.get_by_role("button").filter(has=page.get_by_text("MoEngage staging", exact=True)).click()
    elif change == "unmount":
        page.evaluate("() => window.root.unmount()")


@pytest.mark.parametrize("stage", ["confirmation", "submission"])
@pytest.mark.parametrize("change", ["selection", "source", "ticket", "destination", "channel", "comments", "moengage", "unmount"])
def test_pending_verification_cannot_continue_with_stale_workflow(jira_page, stage, change):
    page = jira_page
    mount(page, "whatsapp")
    confirmation = page.get_by_role("dialog", name="Confirm whitelisting", exact=True)
    if stage == "submission":
        page.get_by_role("button", name="Review & whitelist (1)", exact=True).click()
        expect(confirmation).to_be_visible()
    page.evaluate("() => { window.holdCheck = true; }")
    if stage == "submission":
        confirmation.get_by_role("button", name="Confirm & Whitelist", exact=False).click()
    else:
        page.get_by_role("button", name="Review & whitelist (1)", exact=True).click()
    page.wait_for_function("typeof window.resolveCheck === 'function'")
    change_workflow(page, change)
    page.evaluate("() => window.releaseCheck(true)")
    if stage == "confirmation":
        expect(confirmation).to_have_count(0)
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.loads") == (1 if change == "ticket" else 0)


def test_sms_preparation_verifies_without_submitting_or_reloading(jira_page):
    page = jira_page
    mount(page, "sms")
    review = page.get_by_role("button", name="Review selected SMS (1)", exact=True)
    before = page.evaluate("() => ({...sessionStorage})")
    page.evaluate("() => { window.connectionResult = false; }")
    review.click()
    expect(review).to_be_enabled()
    expect(page.get_by_test_id("sms-review")).to_have_count(0)
    assert page.evaluate("() => window.calls.reconnects") == 1
    assert page.evaluate("() => ({...sessionStorage})") == before
    page.evaluate("() => { window.connectionResult = true; window.dispatchEvent(new Event('focus')); }")
    expect(page.get_by_test_id("sms-review")).to_have_count(0)
    review.click()
    expect(page.get_by_test_id("sms-review")).to_contain_text("Edited exact copy 1")
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.loads") == 0
    assert page.evaluate("() => window.calls.checks") == 2


@pytest.mark.parametrize("change", ["selection", "source", "ticket", "destination"])
def test_sms_preparation_discards_stale_connection_result(jira_page, change):
    page = jira_page
    mount(page, "sms")
    page.evaluate("() => { window.holdCheck = true; }")
    page.get_by_role("button", name="Review selected SMS (1)", exact=True).click()
    page.wait_for_function("typeof window.resolveCheck === 'function'")
    if change == "selection":
        page.get_by_role("checkbox", name="Select source message 1: att_review_0 for SMS DLT whitelisting", exact=True).check()
    elif change == "source":
        page.get_by_role("button", name="Edit", exact=True).nth(1).click()
        page.get_by_role("textbox", name="Message body for source message 2", exact=True).fill("Changed SMS source")
    else:
        change_workflow(page, change)
    page.evaluate("() => window.releaseCheck(true)")
    expect(page.get_by_test_id("sms-review")).to_have_count(0)
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.checks") == 1


@pytest.mark.parametrize("channel", ["whatsapp", "rcs", "sms"])
def test_message_source_uses_real_provenance_beside_editable_copy(jira_page, channel):
    page = jira_page
    mount(page, channel)
    sources = page.get_by_role("complementary", name="Source for TCN-407", exact=True)
    expect(sources).to_have_count(2)
    expect(sources.nth(0)).to_contain_text("campaign-copy.xlsx")
    expect(sources.nth(0)).to_contain_text("Approved copy")
    expect(sources.nth(0)).to_contain_text("D7")
    expect(sources.nth(1)).to_contain_text("Original source paragraph 1")
    expect(sources.nth(1)).to_contain_text("mapping was not supplied")
    expect(sources.nth(1)).not_to_contain_text("D7")
    page.get_by_role("button", name="Edit", exact=True).nth(1).click()
    body = page.get_by_role("textbox", name={
        "whatsapp": "Message body for WhatsApp template 2",
        "rcs": "Message body for RCS template 2",
        "sms": "Message body for source message 2",
    }[channel], exact=True)
    body.fill("A deliberate operator edit")
    expect(body).to_have_value("A deliberate operator edit")
    expect(sources.nth(1)).to_contain_text("Original source paragraph 1")
    assert page.evaluate("() => window.calls.loads") == 0


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_automatic_approval_readback_preserves_drafts_creatives_and_selections(jira_page, channel):
    page = jira_page
    page.evaluate("() => { window.mountOptions = {registered: true}; }")
    mount(page, channel)
    page.wait_for_function("window.calls.statusReads.length === 1")
    expect(page.get_by_text("Awaiting approval", exact=False)).to_be_visible()
    before = page.evaluate("""() => Object.fromEntries(Object.entries(sessionStorage)
        .filter(([key]) => /briefs_(?:wa_templates|rcs_templates|selected_wa|selected_rcs)$/.test(key)))""")
    page.evaluate("() => { window.statusRows[0].approval_status = 'approved'; }")
    page.evaluate("() => window.tickStatuses()")
    expect(page.get_by_role("status", name="Registration outcome", exact=True)).to_contain_text("Approved")
    assert page.evaluate("""() => Object.fromEntries(Object.entries(sessionStorage)
        .filter(([key]) => /briefs_(?:wa_templates|rcs_templates|selected_wa|selected_rcs)$/.test(key)))""") == before
    assert page.evaluate("() => window.calls.statusReads") == [
        {"account": "tcl_promo", "channel": channel, "live": False},
        {"account": "tcl_promo", "channel": channel, "live": False},
    ]
    assert page.evaluate("() => window.calls.loads") == 0
    assert page.evaluate("() => window.calls.posts") == []


@pytest.mark.parametrize("change", ["ticket", "destination", "channel", "source", "unmount"])
def test_stale_approval_readback_is_discarded(jira_page, change):
    page = jira_page
    page.evaluate("() => { window.mountOptions = {registered: true, holdStatus: true}; }")
    mount(page, "whatsapp")
    page.wait_for_function("window.pendingStatuses.length >= 1")
    change_workflow(page, change)
    page.evaluate("""async () => {
        window.pendingStatuses[0]([{template_name: 'att_review_1', provider_ref_id: 'provider-407-1',
            source_ref: 'TCN-407_att_review_1', status: 'submitted', approval_status: 'approved'}]);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    assert page.evaluate("""() => JSON.parse(sessionStorage.getItem('karix_tab:briefs_registrations'))[0].approval_status""") == "pending"
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.loads") == (1 if change == "ticket" else 0)


def test_status_readback_requires_identity_and_retains_last_known_on_failure(jira_page):
    page = jira_page
    page.evaluate("() => { window.mountOptions = {registered: true}; }")
    mount(page, "whatsapp")
    expect(page.get_by_text("Awaiting approval", exact=False)).to_be_visible()
    page.evaluate("""() => { window.statusRows = [
        {template_name: 'att_review_1', provider_ref_id: 'wrong-provider-id', source_ref: 'unrelated',
            status: 'submitted', approval_status: 'approved'},
        {template_name: 'att_review_0', provider_ref_id: 'other-id', status: 'submitted', approval_status: 'approved'},
    ]; }""")
    page.evaluate("() => window.tickStatuses()")
    expect(page.get_by_text("Awaiting approval", exact=False)).to_be_visible()
    timestamp = page.get_by_text("Last known status read:", exact=False).inner_text()
    page.evaluate("() => { window.statusError = 'Inventory timed out'; }")
    page.evaluate("() => window.tickStatuses()")
    expect(page.get_by_role("alert").filter(has_text="Inventory timed out")).to_be_visible()
    expect(page.get_by_text("Last known status read:", exact=False)).to_have_text(timestamp)
    expect(page.get_by_text("Awaiting approval", exact=False)).to_be_visible()
    page.get_by_role("button", name="Clear status message", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Inventory timed out")).to_have_count(0)
    assert page.evaluate("() => window.calls.loads") == 0
    assert page.evaluate("() => window.calls.posts") == []


@pytest.fixture
def dashboard_page(jira_page):
    page = jira_page
    page.evaluate("""() => {
        window.app = {account: 'tcl_promo', channel: 'whatsapp', user: 'Operator', mounted: true,
            getAccountLabel: value => value};
        window.dashboardCalls = {templates: [], stats: [], polls: 0, reconnects: 0};
        const row = (name, id, approval, live = false) => ({
            template_name: name, source_ref: id, provider_ref_id: id, status: 'submitted',
            approval_status: approval, retry_count: 0, submitted_at: '2026-11-19T08:00:00Z',
            live, exists_on_waba: live, submitted_by: live ? null : 'Operator',
        });
        window.liveRows = [row('att_local_review', 'local-1', 'pending'), row('att_provider_only', 'provider-2', 'approved', true)];
        window.savedRows = [row('att_local_review', 'local-1', 'approved')];
        window.pendingDashboard = [];
        window.dashboardTimers = new Map();
        let timerId = 1;
        window.setInterval = callback => { const id = timerId++; window.dashboardTimers.set(id, callback); return id; };
        window.clearInterval = id => window.dashboardTimers.delete(id);
        window.tickDashboard = async () => {
            for (const callback of [...window.dashboardTimers.values()]) callback();
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        };
        const api = {
            fetchTemplates: async params => {
                window.dashboardCalls.templates.push(params);
                if (window.dashboardError) throw new Error(window.dashboardError);
                if (window.holdDashboard) return await new Promise(resolve => window.pendingDashboard.push(resolve));
                return structuredClone(params.live === false ? window.savedRows : window.liveRows);
            },
            fetchStats: async (account, channel, options) => {
                window.dashboardCalls.stats.push({account, channel, ...options});
                if (window.dashboardError) throw new Error(window.dashboardError);
                return {total: options.live === false ? 1 : 2, submitted: 2, pending: options.live === false ? 0 : 1,
                    approved: options.live === false ? 1 : 1, rejected: 0, failed: 0, duplicate: 0};
            },
            fetchActivityLogs: async () => [],
            fetchActivityStats: async () => ({total_users: 0, total_actions: 0, user_activity: []}),
            pollPending: async () => { window.dashboardCalls.polls++; },
        };
        const modules = {};
        function load(name, from = '') {
            if (name === 'react') return React;
            if (name === 'react/jsx-runtime') return {Fragment: React.Fragment,
                jsx: (type, props, key) => React.createElement(type, {...props, key}),
                jsxs: (type, props, key) => React.createElement(type, {...props, key})};
            if (name.startsWith('.')) name = from.slice(0, from.lastIndexOf('/') + 1) + name.replace(/^\\.\\//, '');
            if (name === 'next/link') return {default: props => React.createElement('a', props)};
            if (name === '@/lib/api') return api;
            if (name === '@/lib/context') return {useApp: () => window.app};
            if (name === '@/components/connection-workflow') return {useWhitelistingConnection: () => ({
                reconnect: () => window.dashboardCalls.reconnects++,
            })};
            if (modules[name]) return modules[name].exports;
            if (!window.sources[name]) throw new Error('Unexpected import: ' + name);
            const module = {exports: {}};
            modules[name] = module;
            new Function('require', 'exports', 'module', window.sources[name])(child => load(child, name), module.exports, module);
            return module.exports;
        }
        const Page = load('@/app/page').default;
        window.root = ReactDOM.createRoot(document.getElementById('root'));
        window.renderDashboard = () => window.root.render(React.createElement(Page));
        window.renderDashboard();
    }""")
    expect(page.get_by_text("att_local_review", exact=True)).to_be_visible()
    expect(page.get_by_text("att_provider_only", exact=True)).to_be_visible()
    return page


def test_dashboard_background_reads_durable_status_without_dropping_provider_catalog(dashboard_page):
    page = dashboard_page
    page.get_by_role("checkbox", name="Select att_provider_only", exact=True).check()
    page.evaluate("() => window.tickDashboard()")
    local_row = page.locator("tr").filter(has=page.get_by_text("att_local_review", exact=True))
    expect(local_row).to_contain_text("Approved")
    expect(page.get_by_text("att_provider_only", exact=True)).to_be_visible()
    expect(page.get_by_role("checkbox", name="Select att_provider_only", exact=True)).to_be_checked()
    assert page.evaluate("() => window.dashboardCalls.templates") == [
        {"account": "tcl_promo", "channel": "whatsapp", "live": True},
        {"account": "tcl_promo", "channel": "whatsapp", "live": False},
    ]
    assert page.evaluate("() => window.dashboardCalls.stats")[-1] == {
        "account": "tcl_promo", "channel": "whatsapp", "live": False,
    }
    assert page.evaluate("() => window.dashboardCalls.polls") == 0
    expect(page.get_by_text("Karix Synced", exact=False)).to_have_count(0)


def test_dashboard_inventory_error_retains_data_and_last_known_time(dashboard_page):
    page = dashboard_page
    timestamp = page.get_by_text("Last live inventory read:", exact=False).inner_text()
    page.evaluate("() => { window.dashboardError = 'Inventory timed out'; }")
    page.evaluate("() => window.tickDashboard()")
    expect(page.get_by_text("Inventory timed out", exact=False).first).to_be_visible()
    expect(page.get_by_text("att_provider_only", exact=True)).to_be_visible()
    expect(page.get_by_text("Last live inventory read:", exact=False)).to_have_text(timestamp)
    expect(page.get_by_role("button", name="Retry inventory", exact=True)).to_be_visible()
    page.get_by_role("button", name="Reconnect Karix", exact=True).click()
    assert page.evaluate("() => window.dashboardCalls.reconnects") == 1
    assert page.evaluate("() => window.dashboardCalls.polls") == 0


@pytest.mark.parametrize("change", ["account", "channel", "search", "unmount"])
def test_dashboard_discards_stale_status_readback(dashboard_page, change):
    page = dashboard_page
    page.evaluate("() => { window.holdDashboard = true; }")
    page.evaluate("() => window.tickDashboard()")
    page.wait_for_function("window.pendingDashboard.length === 1")
    page.evaluate("() => window.tickDashboard()")
    assert page.evaluate("() => window.pendingDashboard.length") == 1
    if change == "search":
        page.get_by_role("searchbox", name="Search inventory", exact=True).fill("new query")
        page.wait_for_function("window.dashboardCalls.templates.some(call => call.search === 'new query')")
    elif change == "unmount":
        page.evaluate("() => window.root.unmount()")
    else:
        page.evaluate("""change => {
            window.app = {...window.app, ...(change === 'account' ? {account: 'bajaj'} : {channel: 'sms'})};
            ReactDOM.flushSync(() => window.renderDashboard());
        }""", change)
    page.evaluate("""async () => {
        window.pendingDashboard[0]([{template_name: 'att_stale_leak', source_ref: 'stale', status: 'submitted',
            approval_status: 'approved', retry_count: 0, submitted_at: '2026-11-19T08:00:00Z'}]);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    expect(page.get_by_text("att_stale_leak", exact=True)).to_have_count(0)


def test_jira_unknown_registration_is_not_reported_as_rejection_or_approval(jira_page):
    page = jira_page
    page.evaluate("() => { window.mountOptions = {registered: true}; }")
    mount(page, "whatsapp")
    page.evaluate("""() => { window.statusRows[0] = {...window.statusRows[0],
        status: 'failed', approval_status: 'unknown', provider_response: {outcome: 'unknown'},
        error: 'Registration outcome unknown. Provider response was lost.'}; }""")
    page.evaluate("() => window.tickStatuses()")
    outcome = page.get_by_role("status", name="Registration outcome", exact=True)
    expect(outcome).to_contain_text("Outcome unknown")
    expect(outcome).to_contain_text("before submitting again")
    expect(outcome).not_to_contain_text("Rejected")
    assert page.evaluate("() => window.calls.posts") == []
    assert page.evaluate("() => window.calls.loads") == 0
