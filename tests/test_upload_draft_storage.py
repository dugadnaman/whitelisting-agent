"""Exercise real IndexedDB/File storage and mounted upload/SMS connection guards.

Requires frontend npm dependencies and Playwright Chromium; no provider traffic.
"""

import json
from pathlib import Path
import subprocess

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def upload_modules():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    result = subprocess.run(
        ["node", "-e", r"""
        const fs = require('node:fs');
        const ts = require('typescript');
        const paths = ['app/submit/page.tsx', 'components/sms-dlt.tsx',
            ...fs.readdirSync('lib').filter(name => name.endsWith('.ts')).map(name => 'lib/' + name)];
        process.stdout.write(JSON.stringify(Object.fromEntries(paths.map(path => [
            '@/' + path.replace(/\.tsx?$/, ''),
            ts.transpileModule(fs.readFileSync(path, 'utf8'), {compilerOptions: {
                module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
                jsx: ts.JsxEmit.ReactJSX
            }}).outputText
        ]))));
        """], cwd=frontend, check=True, capture_output=True, text=True,
    )
    return frontend, json.loads(result.stdout)


@pytest.fixture
def upload_page(upload_modules):
    frontend, sources = upload_modules
    react = (frontend / "node_modules/react/umd/react.development.js").read_text()
    react_dom = (frontend / "node_modules/react-dom/umd/react-dom.development.js").read_text()
    harness = r"""
        window.calls = {checks: 0, previews: [], posts: [], reconnects: 0, smsReviews: 0, smsPosts: [], options: 0};
        window.connectionResult = true;
        window.connectionAvailable = true;
        window.holdConnection = false;
        window.app = {account: 'tcl_promo', channel: 'whatsapp', user: 'Operator',
            currentUser: {id: 'operator-1', tenant_id: 'tata'}, accounts: [],
            getAccountLabel: value => value, setDestination: () => false};
        window.previews = [{template_name: 'att_exact_draft', category: 'MARKETING', language: 'en',
            inventory_status: 'verified', submission_ready: true,
            components: [{type: 'BODY', text: 'Exact reviewed copy'}]}];
        window.smsDraft = {template_name: 'reviewed_sms', text: 'Exact SMS copy', sample_message: '',
            template_type: '1', message_type: '1', category_id: 'finance', header_id: 'header', header: 'TATAXX'};
        const fileDetails = async file => ({name: file.name, type: file.type, lastModified: file.lastModified,
            bytes: Array.from(new Uint8Array(await file.arrayBuffer()))});
        const api = {
            getSampleCsvUrl: () => '#sample',
            previewFile: async file => { window.calls.previews.push(await fileDetails(file)); return structuredClone(window.previews); },
            submitFile: async (file, account, channel) => {
                window.calls.posts.push(await fileDetails(file));
                if (window.failPost) throw new Error('Submission response lost');
                return {account, channel, submitted: 1, results: [], status: 'COMPLETED'};
            },
            fetchSmsDltOptions: async () => { window.calls.options++; return {
                categories: [{id: 'finance', text: 'Finance'}], headers: [{id: 'header', text: 'TATAXX'}], brands: []}; },
            previewSmsDltDrafts: async (_account, drafts) => {
                window.calls.smsReviews++; return drafts.map(() => ({inventory_status: 'verified', submission_ready: true}));
            },
            submitSmsDltDrafts: async (_account, drafts) => {
                window.calls.smsPosts.push(structuredClone(drafts));
                if (window.failPost) throw new Error('Submission response lost');
                return {status: 'COMPLETED', results: []};
            },
            fetchJob: async () => ({job: {status: 'COMPLETED'}, tasks: []})
        };
        const connection = {useWhitelistingConnection: () => ({connected: window.connectionAvailable,
            reconnect: () => { window.calls.reconnects++; },
            ensureConnected: async () => {
                window.calls.checks++;
                let result = window.connectionResults?.length ? window.connectionResults.shift() : window.connectionResult;
                if (window.holdConnection) {
                    const deferred = Promise.withResolvers();
                    window.resolveConnection = deferred.resolve;
                    result = await deferred.promise;
                }
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
                getRcsDetails: () => ({botId: 'reviewed-bot', botName: 'Reviewed bot'})};
            if (name === '@/components/connection-workflow') return connection;
            if (name === '@/components/KarixAuthSync') return {default: () => null};
            if (modules[name]) return modules[name].exports;
            if (!window.sources[name]) throw new Error('Unexpected import: ' + name);
            const module = {exports: {}};
            modules[name] = module;
            new Function('require', 'exports', 'module', window.sources[name])(
                child => load(child, name), module.exports, module);
            return module.exports;
        }
        window.uploadDrafts = load('@/lib/upload-draft');
        window.tabState = load('@/lib/tab-state');
        window.scope = window.uploadDrafts.uploadDraftScope({userId: 'operator-1', tenant: 'tata',
            account: 'tcl_promo', channel: 'whatsapp'});
        let reactRoot = null;
        window.mountUpload = () => {
            reactRoot ||= ReactDOM.createRoot(document.getElementById('root'));
            reactRoot.render(React.createElement(load('@/app/submit/page').default));
        };
        window.mountSms = () => {
            window.app.account = 'tata'; window.app.channel = 'sms';
            reactRoot ||= ReactDOM.createRoot(document.getElementById('root'));
            reactRoot.render(React.createElement(load('@/components/sms-dlt').SmsDltReview,
                {initialDrafts: [window.smsDraft], storageKey: 'sms_fixture'}));
        };
        window.unmount = () => { reactRoot.unmount(); reactRoot = null; };
    """
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("Install the browser with: playwright install chromium")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://upload-draft.test/**", lambda route: route.fulfill(
            content_type="text/html", body='<!doctype html><div id="root"></div>',
        ))
        page.add_init_script(react + "\n" + react_dom + "\nwindow.sources = " + json.dumps(sources) + ";\n" + harness)
        page.goto("https://upload-draft.test/submit")
        try:
            yield page
        finally:
            browser.close()


def test_real_file_and_matching_review_survive_reload(upload_page):
    page = upload_page
    saved = page.evaluate("""async () => {
        const bytes = new Uint8Array([0, 255, 80, 75, 13, 10, 228, 184, 173]);
        const file = new File([bytes], 'Exact source.xlsx', {
            type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', lastModified: 123456789});
        const id = await uploadDrafts.saveUploadDraft(scope, file);
        const review = {uploadId: id, previews: [{template_name: 'edited_name', body: 'Exact copy ₹'}], botId: 'reviewed-bot'};
        await uploadDrafts.saveUploadReview(scope, id, review);
        sessionStorage.setItem('restore-id', id);
        return {id, review};
    }""")
    page.reload()
    restored = page.evaluate("""async () => {
        const saved = await uploadDrafts.loadUploadDraft(scope, sessionStorage.getItem('restore-id'));
        return {isFile: saved.file instanceof File, name: saved.file.name, type: saved.file.type,
            modified: saved.file.lastModified, bytes: Array.from(new Uint8Array(await saved.file.arrayBuffer())), review: saved.review};
    }""")
    assert restored == {
        "isFile": True, "name": "Exact source.xlsx",
        "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "modified": 123456789, "bytes": [0, 255, 80, 75, 13, 10, 228, 184, 173], "review": saved["review"],
    }


@pytest.mark.parametrize("field,value", [
    ("userId", "operator-2"), ("tenant", "other-tenant"), ("tenant", "all"), ("account", "tcl_trans"), ("channel", "rcs"),
])
def test_upload_scope_and_review_identity_do_not_cross(upload_page, field, value):
    result = upload_page.evaluate("""async ([field, value]) => {
        const otherScope = uploadDrafts.uploadDraftScope({userId: 'operator-1', tenant: 'tata',
            account: 'tcl_promo', channel: 'whatsapp', [field]: value});
        const first = await uploadDrafts.saveUploadDraft(scope, new File(['original'], 'same.csv', {type: 'text/csv'}));
        const other = await uploadDrafts.saveUploadDraft(otherScope, new File(['other scope'], 'same.csv', {type: 'text/csv'}));
        const crossed = await uploadDrafts.loadUploadDraft(otherScope, first);
        const replacement = await uploadDrafts.saveUploadDraft(scope, new File(['replacement'], 'same.csv', {type: 'text/csv'}));
        const staleReview = await uploadDrafts.saveUploadReview(scope, first, {body: 'stale review'});
        const current = await uploadDrafts.loadUploadDraft(scope, replacement);
        return {crossed, staleReview, replaced: await uploadDrafts.loadUploadDraft(scope, first),
            current: await current.file.text(), review: current.review ?? null,
            other: await (await uploadDrafts.loadUploadDraft(otherScope, other)).file.text()};
    }""", [field, value])
    assert result == {"crossed": None, "staleReview": False, "replaced": None,
                      "current": "replacement", "review": None, "other": "other scope"}


@pytest.mark.parametrize("prefix", ["submit_upload", None], ids=["discard", "logout-or-destination-change"])
def test_clear_tab_state_deletes_bytes_and_blocks_late_operations(upload_page, prefix):
    result = upload_page.evaluate("""async prefix => {
        const id = await uploadDrafts.saveUploadDraft(scope, new File(['private bytes'], 'private.csv'));
        tabState.setTabState('submit_upload', {scope, id});
        tabState.setTabState('selection', new Set([2, 4]));
        const restoring = uploadDrafts.loadUploadDraft(scope, id);
        const updating = uploadDrafts.saveUploadReview(scope, id, {body: 'late review'});
        const writing = uploadDrafts.saveUploadDraft(scope, new File(['late private bytes'], 'late.csv'));
        const operations = Promise.allSettled([restoring, updating, writing]);
        tabState.clearTabState(prefix || undefined);
        const settled = await operations;
        return {old: await uploadDrafts.loadUploadDraft(scope, id),
            late: settled[2].status === 'fulfilled' ? await uploadDrafts.loadUploadDraft(scope, settled[2].value) : null,
            restorePublished: settled[0].status === 'fulfilled' && settled[0].value !== null,
            updatePublished: settled[1].status === 'fulfilled' && settled[1].value === true,
            selection: tabState.getTabState('submit_upload', null),
            setPreserved: prefix ? Array.from(tabState.getTabState('selection', new Set())) : []};
    }""", prefix)
    assert result == {"old": None, "late": None, "restorePublished": False, "updatePublished": False,
                      "selection": None, "setPreserved": [2, 4] if prefix else []}


def test_clear_during_native_write_cannot_resurrect_file(upload_page):
    result = upload_page.evaluate("""async () => {
        const nativePut = IDBObjectStore.prototype.put;
        let clearing;
        IDBObjectStore.prototype.put = function (...args) {
            const request = nativePut.apply(this, args);
            IDBObjectStore.prototype.put = nativePut;
            clearing = uploadDrafts.clearUploadDrafts();
            return request;
        };
        const [write] = await Promise.allSettled([
            uploadDrafts.saveUploadDraft(scope, new File(['discarded'], 'discarded.csv'))]);
        await clearing;
        const opened = Promise.withResolvers();
        const opening = indexedDB.open('karix-upload-drafts', 1);
        opening.onsuccess = () => opened.resolve(opening.result); opening.onerror = () => opened.reject(opening.error);
        const db = await opened.promise;
        const counted = Promise.withResolvers();
        const request = db.transaction('files').objectStore('files').count();
        request.onsuccess = () => counted.resolve(request.result); request.onerror = () => counted.reject(request.error);
        const count = await counted.promise;
        db.close();
        return {write: write.status, count};
    }""")
    assert result == {"write": "rejected", "count": 0}


def test_upload_requires_explicit_recheck_and_restores_exact_file_after_navigation(upload_page):
    page = upload_page
    page.evaluate("connectionResult = false; mountUpload()")
    source = b'template_name,body\r\natt_exact_draft,Exact reviewed copy\r\n'
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "reviewed.csv", "mimeType": "text/csv", "buffer": source},
    )
    expect(page.get_by_text("reviewed.csv", exact=True)).to_be_visible()
    page.wait_for_function("calls.checks === 1 && tabState.getTabState('submit_upload', null)")
    assert page.evaluate("calls.previews.length") == 0
    page.evaluate("connectionResult = true; mountUpload()")
    assert page.evaluate("calls.previews.length") == 0
    page.get_by_role("button", name="Validate retained file").click()
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_enabled()
    page.evaluate("unmount(); mountUpload()")
    expect(page.get_by_text("reviewed.csv", exact=True)).to_be_visible()
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.previews.length") == 1
    page.evaluate("connectionResult = false")
    submit.click()
    page.wait_for_function("calls.reconnects === 2")
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.posts.length") == 0
    page.evaluate("connectionResult = true; mountUpload()")
    assert page.evaluate("calls.posts.length") == 0
    page.evaluate("connectionResults = [true, false]")
    submit.click()
    page.wait_for_function("calls.reconnects === 3")
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.posts.length") == 0
    submit.click()
    page.wait_for_function("calls.posts.length === 1")
    assert page.evaluate("calls.posts[0].bytes") == list(source)
    assert page.evaluate("calls.posts[0].name") == "reviewed.csv"


def test_upload_discard_removes_restorable_review_and_bytes(upload_page):
    page = upload_page
    page.evaluate("mountUpload()")
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "discard.csv", "mimeType": "text/csv", "buffer": b'original upload'},
    )
    expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_be_enabled()
    selection = page.evaluate("tabState.getTabState('submit_upload', null)")
    page.get_by_role("button", name="Remove", exact=True).click()
    assert page.evaluate("async saved => await uploadDrafts.loadUploadDraft(saved.scope, saved.id)", selection) is None
    page.evaluate("unmount(); mountUpload()")
    expect(page.get_by_text("discard.csv", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_have_count(0)


def test_recovered_upload_inventory_is_rechecked_only_by_explicit_action(upload_page):
    page = upload_page
    page.evaluate("""previews[0].inventory_status = 'unverified';
        previews[0].submission_ready = false; mountUpload()""")
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "unverified.csv", "mimeType": "text/csv", "buffer": b'exact retained bytes'},
    )
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_disabled()
    page.evaluate("unmount(); mountUpload()")
    expect(page.get_by_text("unverified.csv", exact=True)).to_be_visible()
    page.evaluate("""previews[0].inventory_status = 'verified';
        previews[0].submission_ready = true; mountUpload()""")
    assert page.evaluate("calls.previews.length") == 1
    page.get_by_role("button", name="Retry validation", exact=True).click()
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.previews[1].bytes") == list(b'exact retained bytes')
    assert page.evaluate("calls.posts.length") == 0


def test_discard_cancels_an_inflight_connection_check(upload_page):
    page = upload_page
    page.evaluate("mountUpload()")
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "cancel.csv", "mimeType": "text/csv", "buffer": b'never submit this'},
    )
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_enabled()
    page.evaluate("holdConnection = true")
    submit.click()
    page.wait_for_function("typeof resolveConnection === 'function'")
    page.get_by_role("button", name="Remove", exact=True).click()
    page.evaluate("resolveConnection(true)")
    expect(submit).to_have_count(0)
    assert page.evaluate("calls.posts.length") == 0


def test_sms_reconnect_preserves_edits_and_never_replays_uncertain_post(upload_page):
    page = upload_page
    page.evaluate("connectionAvailable = false; mountSms()")
    expect(page.get_by_role("heading", name="SMS whitelisting", exact=True)).to_be_visible()
    assert page.evaluate("calls.options") == 0
    page.evaluate("connectionAvailable = true; mountSms()")
    review = page.get_by_role("button", name="Review & whitelist (1)")
    expect(review).to_be_enabled()
    loaded_options = page.evaluate("calls.options")
    page.get_by_role("textbox", name="Message", exact=True).fill("Operator edited exact SMS copy")
    page.evaluate("connectionResult = false")
    review.click()
    page.wait_for_function("calls.checks === 1")
    assert page.evaluate("calls.smsReviews") == 0
    page.evaluate("connectionResult = true; mountSms()")
    assert page.evaluate("calls.smsReviews") == 0
    review.click()
    expect(page.get_by_role("heading", name="3. Confirm SMS whitelisting")).to_be_visible()
    page.get_by_role("checkbox", name="I reviewed the destination", exact=False).check()
    page.evaluate("connectionAvailable = false; mountSms()")
    expect(page.get_by_role("checkbox", name="I reviewed the destination", exact=False)).to_be_checked()
    page.evaluate("connectionAvailable = true; mountSms()")
    assert page.evaluate("calls.options") == loaded_options
    page.evaluate("connectionResult = false")
    page.get_by_role("button", name="Confirm & whitelist", exact=True).click()
    page.wait_for_function("calls.reconnects === 2")
    assert page.evaluate("calls.smsPosts.length") == 0
    expect(page.get_by_role("checkbox", name="I reviewed the destination", exact=False)).to_be_checked()
    page.evaluate("connectionResult = true; failPost = true; mountSms()")
    assert page.evaluate("calls.smsPosts.length") == 0
    page.get_by_role("button", name="Confirm & whitelist", exact=True).click()
    expect(page.get_by_text("The last submission response is unconfirmed.", exact=False)).to_be_visible()
    assert page.evaluate("calls.smsPosts[0][0].text") == "Operator edited exact SMS copy"
    page.evaluate("unmount(); mountSms()")
    expect(page.get_by_text("The last submission response is unconfirmed.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Confirm & whitelist", exact=True)).to_be_disabled()
    assert page.evaluate("calls.smsPosts.length") == 1


def test_navigation_during_file_write_keeps_the_original_selection(upload_page):
    page = upload_page
    page.evaluate("""() => { mountUpload();
        const nativePut = IDBObjectStore.prototype.put;
        IDBObjectStore.prototype.put = function (...args) {
            const request = nativePut.apply(this, args);
            IDBObjectStore.prototype.put = nativePut;
            window.navigatedDuringWrite = true;
            unmount(); mountUpload();
            return request;
        }; }""")
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "write-in-flight.csv", "mimeType": "text/csv", "buffer": b'exact original file'},
    )
    page.wait_for_function("window.navigatedDuringWrite === true")
    expect(page.get_by_text("write-in-flight.csv", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Validate retained file")).to_be_enabled()
    assert page.evaluate("calls.previews.length") == 0
    assert page.evaluate("calls.checks") == 0
    restored = page.evaluate("""async () => {
        const selection = tabState.getTabState('submit_upload', null);
        return await (await uploadDrafts.loadUploadDraft(selection.scope, selection.id)).file.text();
    }""")
    assert restored == "exact original file"


@pytest.mark.parametrize("channel", ["whatsapp", "rcs", "sms"])
def test_superadmin_workspace_can_open_selected_destination_without_crashing(upload_page, channel):
    page = upload_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.evaluate("""channel => {
        app.currentUser = {id: 'admin-1', tenant_id: 'all', role: 'superadmin'};
        app.account = channel === 'sms' ? 'tata' : 'tcl_promo';
        app.channel = channel;
        mountUpload();
    }""", channel)
    if channel == "sms":
        expect(page.get_by_text("Upload DLT CSV / Excel", exact=True)).to_be_visible()
    else:
        page.locator('input[type="file"]').first.set_input_files({
            "name": "admin-review.csv", "mimeType": "text/csv", "buffer": b"exact admin source",
        })
        expect(page.get_by_text("admin-review.csv", exact=True)).to_be_visible()
        page.wait_for_function("calls.previews.length === 1")
        restored = page.evaluate("""async () => {
            const selection = tabState.getTabState('submit_upload', null);
            return (await uploadDrafts.loadUploadDraft(selection.scope, selection.id)).file.text();
        }""")
        assert restored == "exact admin source"
    assert not errors, errors


def test_all_accounts_overview_cannot_be_used_as_upload_destination(upload_page):
    page = upload_page
    page.evaluate("""() => {
        app.currentUser = {id: 'admin-1', tenant_id: 'all', role: 'superadmin'};
        app.account = 'all';
        mountUpload();
    }""")
    expect(page.get_by_role("alert")).to_contain_text("Choose a specific account")
    assert page.evaluate("calls.posts.length") == 0
