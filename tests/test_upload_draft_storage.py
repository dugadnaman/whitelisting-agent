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
        window.calls = {checks: 0, previews: [], posts: [], reconnects: 0, smsReviews: 0, smsPosts: [], options: 0, jobs: []};
        window.connectionResult = true;
        window.connectionAvailable = true;
        window.holdConnection = false;
        window.app = {account: 'tcl_promo', channel: 'whatsapp', user: 'Operator',
            currentUser: {id: 'operator-1', tenant_id: 'tata'}, accounts: [],
            getAccountLabel: value => value, setDestination: () => false};
        window.previews = [{template_name: 'att_exact_draft', category: 'MARKETING', language: 'en',
            inventory_status: 'verified', submission_ready: true,
            components: [{type: 'BODY', text: 'Exact reviewed copy'}]}];
        window.inventoryRequests = [];
        window.smsReviewRequests = [];
        window.languageOverrideObjects = [];
        window.reviewFileObjects = [];
        window.smsDraft = {template_name: 'reviewed_sms', text: 'Exact SMS copy', sample_message: '',
            template_type: '1', message_type: '1', category_id: 'finance', header_id: 'header', header: 'TATAXX'};
        const fileDetails = async file => ({name: file.name, type: file.type, lastModified: file.lastModified,
            bytes: Array.from(new Uint8Array(await file.arrayBuffer()))});
        const api = {
            getSampleCsvUrl: () => '#sample',
            previewFile: async (file, account, channel, options) => {
                window.languageOverrideObjects.push(options?.languageOverrides);
                window.reviewFileObjects.push(file);
                window.calls.previews.push({...await fileDetails(file), account, channel,
                    verifyInventory: options?.verifyInventory, languageOverrides: options?.languageOverrides});
                const result = structuredClone(window.previews);
                for (const preview of result) {
                    const language = options?.languageOverrides?.[preview.source_ref];
                    if (language) Object.assign(preview, {language, language_review_required: false,
                        language_review_message: null, submission_ready: true});
                }
                if (options?.verifyInventory === true && window.holdInventory) {
                    const deferred = Promise.withResolvers();
                    window.inventoryRequests.push({...deferred, result});
                    return deferred.promise;
                }
                if (options?.verifyInventory === true && window.inventoryFailure) throw new Error(window.inventoryFailure);
                return result;
            },
            submitFile: async (file, account, channel, _user, _fixGrammar, _skipDuplicates, _review, _botId, languageOverrides) => {
                window.languageOverrideObjects.push(languageOverrides);
                window.reviewFileObjects.push(file);
                window.calls.posts.push({...await fileDetails(file), languageOverrides});
                if (window.failPost) throw new Error('Submission response lost');
                return {account, channel, submitted: 1, results: [], status: 'COMPLETED'};
            },
            fetchSmsDltOptions: async () => {
                window.calls.options++;
                if (window.holdOptions) {
                    const deferred = Promise.withResolvers();
                    window.resolveOptions = deferred.resolve;
                    await deferred.promise;
                }
                return {categories: [{id: 'finance', text: 'Finance'}],
                    headers: [{id: 'header', text: 'TATAXX'}], brands: []};
            },
            previewSmsDltDrafts: async (_account, drafts) => {
                window.calls.smsReviews++;
                const result = drafts.map(draft => ({template_name: draft.template_name, sms_dlt: structuredClone(draft),
                    inventory_status: 'verified', submission_ready: true}));
                if (window.holdSmsReview) {
                    const deferred = Promise.withResolvers();
                    window.smsReviewRequests.push({...deferred, result});
                    return deferred.promise;
                }
                if (window.smsReviewFailure) throw new Error(window.smsReviewFailure);
                return result;
            },
            submitSmsDltDrafts: async (_account, drafts) => {
                window.calls.smsPosts.push(structuredClone(drafts));
                if (window.failPost) throw new Error('Submission response lost');
                return {status: 'COMPLETED', results: []};
            },
            fetchJob: async (jobId, reconcile) => {
                window.calls.jobs.push({jobId, reconcile: Boolean(reconcile)});
                if (window.holdJob) {
                    const deferred = Promise.withResolvers();
                    window.resolveJob = deferred.resolve;
                    return deferred.promise;
                }
                const result = window.jobSnapshots?.length > 1 ? window.jobSnapshots.shift() : window.jobSnapshots?.[0];
                return structuredClone(result || {job: {status: 'COMPLETED'}, tasks: []});
            }
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


def test_offline_upload_and_exact_file_survive_reconnect_and_navigation(upload_page):
    page = upload_page
    page.evaluate("connectionResult = false; mountUpload()")
    source = b'template_name,body\r\natt_exact_draft,Exact reviewed copy\r\n'
    page.locator('input[type="file"]').first.set_input_files(
        {"name": "reviewed.csv", "mimeType": "text/csv", "buffer": source},
    )
    expect(page.get_by_text("reviewed.csv", exact=True)).to_be_visible()
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.previews.map(call => call.verifyInventory)") == [False, True]
    assert page.evaluate("calls.checks") == 0
    page.evaluate("unmount(); mountUpload()")
    expect(page.get_by_text("reviewed.csv", exact=True)).to_be_visible()
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.previews.length") == 2
    submit.click()
    page.wait_for_function("calls.reconnects === 1")
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.posts.length") == 0
    page.evaluate("connectionResult = true; mountUpload()")
    assert page.evaluate("calls.posts.length") == 0
    page.evaluate("connectionResults = [true, false]")
    submit.click()
    page.wait_for_function("calls.reconnects === 2")
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
    assert page.evaluate("calls.previews.length") == 2
    page.get_by_role("button", name="Retry inventory check", exact=True).click()
    expect(submit).to_be_enabled()
    assert page.evaluate("calls.previews[2].bytes") == list(b'exact retained bytes')
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
    expect(page.get_by_role("dialog")).to_contain_text("session is not connected")
    page.evaluate("connectionResult = true; mountSms()")
    assert page.evaluate("calls.smsReviews") == 0
    page.get_by_role("button", name="Retry inventory check", exact=True).click()
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
        page.wait_for_function("calls.previews.length === 2")
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


def test_messages_and_provenance_are_visible_before_live_inventory(upload_page):
    page = upload_page
    page.evaluate("""() => {
        holdInventory = true;
        Object.assign(previews[0], {source_file: 'Client workbook.xlsx',
            source_sheet: 'Offers', source_cell: 'D17', source_ref: 'client-row-17'});
        mountUpload();
    }""")
    source = b'exact retained workbook bytes'
    page.locator('input[type="file"]').first.set_input_files({
        "name": "Client workbook.xlsx", "mimeType": "application/octet-stream", "buffer": source,
    })
    page.wait_for_function("inventoryRequests.length === 1")
    row = page.get_by_role("row").filter(has_text="att_exact_draft")
    expect(row).to_contain_text("Exact reviewed copy")
    expect(row).to_contain_text("Client workbook.xlsx")
    expect(row).to_contain_text("Offers!D17")
    expect(row).to_contain_text("client-row-17")
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_disabled()
    assert page.evaluate("calls.checks") == 0
    page.evaluate("""() => {
        const current = tabState.getTabState('submit_state', null);
        current.operator_review = 'preserve this review';
        current.previews[0].operator_note = 'reviewed exact original';
        inventoryRequests[0].resolve(inventoryRequests[0].result);
    }""")
    expect(submit).to_be_enabled()
    assert page.evaluate("tabState.getTabState('submit_state', null).operator_review") == "preserve this review"
    assert page.evaluate("tabState.getTabState('submit_state', null).previews[0].operator_note") == "reviewed exact original"
    assert page.evaluate("calls.previews.map(call => call.bytes)") == [list(source), list(source)]
    assert page.evaluate("calls.posts.length") == 0


def test_inventory_failure_retries_retained_file_without_resetting_review(upload_page):
    page = upload_page
    page.evaluate("inventoryFailure = 'Inventory service timed out, not an authentication failure'; mountUpload()")
    source = b'private original source'
    page.locator('input[type="file"]').first.set_input_files({
        "name": "retained.csv", "mimeType": "text/csv", "buffer": source,
    })
    expect(page.get_by_text("Inventory service timed out, not an authentication failure", exact=True)).to_be_visible()
    page.evaluate("tabState.setTabState('submit_auto_fix_grammar', false); unmount(); mountUpload()")
    page.get_by_role("button", name="Reconnect this destination", exact=True).click()
    page.evaluate("inventoryFailure = ''; mountUpload()")
    assert page.evaluate("calls.previews.length") == 2
    page.get_by_role("button", name="Retry inventory check", exact=True).click()
    expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_be_enabled()
    assert page.evaluate("tabState.getTabState('submit_auto_fix_grammar', true)") is False
    assert page.evaluate("calls.previews[2].bytes") == list(source)
    assert page.evaluate("calls.posts.length") == 0


@pytest.mark.parametrize("change", ["replacement", "scope", "discard"])
def test_late_inventory_cannot_verify_a_different_upload_or_destination(upload_page, change):
    page = upload_page
    page.evaluate("holdInventory = true; mountUpload()")
    page.locator('input[type="file"]').first.set_input_files({
        "name": "first.csv", "mimeType": "text/csv", "buffer": b'first exact source',
    })
    page.wait_for_function("inventoryRequests.length === 1")
    if change == "replacement":
        page.evaluate("previews[0].template_name = 'second_draft'; previews[0].components[0].text = 'Second exact copy'")
        page.locator('input[type="file"]').first.set_input_files({
            "name": "second.csv", "mimeType": "text/csv", "buffer": b'second exact source',
        })
        page.wait_for_function("inventoryRequests.length === 2")
    elif change == "scope":
        page.evaluate("app.account = 'tcl_trans'; mountUpload()")
        expect(page.get_by_text("first.csv", exact=True)).to_have_count(0)
    else:
        page.get_by_role("button", name="Remove", exact=True).click()
    page.evaluate("inventoryRequests[0].resolve(inventoryRequests[0].result)")
    if change == "replacement":
        expect(page.get_by_text("Second exact copy", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_be_disabled()
        assert page.evaluate("tabState.getTabState('submit_state', null).previews[0].inventory_status") == "unverified"
    else:
        expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_have_count(0)
    assert page.evaluate("calls.posts.length") == 0


@pytest.mark.parametrize("change", ["provider-name", "operator-copy"])
def test_inventory_mismatch_never_overwrites_copy_or_enables_submission(upload_page, change):
    page = upload_page
    page.evaluate("holdInventory = true; mountUpload()")
    page.locator('input[type="file"]').first.set_input_files({
        "name": "identity.csv", "mimeType": "text/csv", "buffer": b'exact identity',
    })
    page.wait_for_function("inventoryRequests.length === 1")
    page.evaluate("""change => {
        if (change === 'provider-name') inventoryRequests[0].result[0].template_name = 'unexpected_server_name';
        else tabState.getTabState('submit_state', null).previews[0].components[0].text = 'Operator retained exact copy';
        inventoryRequests[0].resolve(inventoryRequests[0].result);
        mountUpload();
    }""", change)
    expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_be_disabled()
    expect(page.get_by_text("att_exact_draft", exact=True)).to_be_visible()
    expect(page.get_by_text("unexpected_server_name", exact=True)).to_have_count(0)
    expected_copy = "Operator retained exact copy" if change == "operator-copy" else "Exact reviewed copy"
    expect(page.get_by_text(expected_copy, exact=True)).to_be_visible()
    assert page.evaluate("calls.posts.length") == 0


@pytest.mark.parametrize("detected_language,language,body", [
    ("", "mr", "आपल्या खात्यासाठी खास ऑफर.\nमूळ संदेश जसाच्या तसा ठेवा."),
    ("", "ur", "آپ کے اکاؤنٹ کے لیے خصوصی پیشکش۔\nاصل پیغام بغیر تبدیلی کے محفوظ رکھیں۔"),
    ("en", "hi", "Aapke khate ke liye khaas offer.\nAsli sandesh bilkul waise hi rakhein."),
])
def test_whatsapp_language_review_rechecks_exact_source_and_bytes_before_submit(upload_page, detected_language, language, body):
    page = upload_page
    page.evaluate("""([body, detectedLanguage]) => {
        holdInventory = true;
        Object.assign(previews[0], {language: detectedLanguage, language_review_required: !detectedLanguage,
            language_review_message: 'Choose the language of the original message.',
            source_ref: 'Offers!D17', source_file: 'Regional.xlsx', source_sheet: 'Offers', source_cell: 'D17',
            components: [{type: 'BODY', text: body}]});
        mountUpload();
    }""", [body, detected_language])
    source = (body + "\r\nunchanged workbook bytes").encode()
    page.locator('input[type="file"]').first.set_input_files({
        "name": "Regional.xlsx", "mimeType": "application/octet-stream", "buffer": source,
    })
    page.wait_for_function("inventoryRequests.length === 1")
    selector = page.get_by_role("combobox", name="Language for att_exact_draft (Offers!D17)", exact=True)
    expect(selector).to_have_value(detected_language)
    if not detected_language:
        expect(page.get_by_text("Needs review: language", exact=True)).to_be_visible()
    assert selector.locator("option").all_text_contents() == [
        "Choose language", "English (en)", "Hindi (hi)", "Marathi (mr)", "Gujarati (gu)", "Punjabi (pa)",
        "Bengali (bn)", "Tamil (ta)", "Telugu (te)", "Kannada (kn)", "Malayalam (ml)",
        "Urdu (ur)", "Odia (or)", "Assamese (as)",
    ]
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_disabled()
    selector.select_option(language)
    page.evaluate("inventoryRequests[0].resolve(inventoryRequests[0].result)")
    expect(submit).to_be_disabled()
    expect(selector).to_have_value(language)
    row = page.get_by_role("row").filter(has_text="att_exact_draft")
    expect(row.locator("pre").first).to_have_text(body)
    expect(row).to_contain_text("Regional.xlsx")
    expect(row).to_contain_text("Offers!D17")
    assert page.evaluate("tabState.getTabState('submit_state', null).previews[0].language") == detected_language
    page.get_by_role("button", name="Reconnect this destination", exact=True).click()
    page.evaluate("unmount(); mountUpload()")
    expect(page.get_by_text("Regional.xlsx", exact=True)).to_be_visible()
    expect(selector).to_have_value(language)
    expect(row.locator("pre").first).to_have_text(body)
    expect(submit).to_be_disabled()
    assert page.evaluate("calls.previews.length") == 2
    assert page.evaluate("calls.reconnects") == 1
    assert page.evaluate("calls.posts.length") == 0
    page.get_by_role("button", name="Recheck language & inventory", exact=True).click()
    page.wait_for_function("inventoryRequests.length === 2")
    expect(submit).to_be_disabled()
    page.evaluate("inventoryRequests[1].resolve(inventoryRequests[1].result)")
    expect(submit).to_be_enabled()
    expect(selector).to_have_value(language)
    assert page.evaluate("calls.previews.slice(2).map(call => call.languageOverrides)") == [
        {"Offers!D17": language}, {"Offers!D17": language},
    ]
    assert page.evaluate("calls.previews.every(call => call.name === 'Regional.xlsx')") is True
    assert page.evaluate("calls.previews.map(call => call.bytes)") == [list(source)] * 4
    submit.click()
    page.wait_for_function("calls.posts.length === 1")
    assert page.evaluate("calls.posts[0].languageOverrides") == {"Offers!D17": language}
    assert page.evaluate("calls.posts[0].bytes") == list(source)
    assert page.evaluate("languageOverrideObjects[2] === languageOverrideObjects[3] && languageOverrideObjects[3] === languageOverrideObjects[4]") is True
    assert page.evaluate("reviewFileObjects[2] === reviewFileObjects[3] && reviewFileObjects[3] === reviewFileObjects[4]") is True


def test_language_override_persists_with_review_and_resets_with_file_and_destination(upload_page):
    page = upload_page
    page.evaluate("""() => {
        Object.assign(previews[0], {language: '', language_review_required: true, source_ref: 'CSV row 7'});
        mountUpload();
    }""")
    page.locator('input[type="file"]').first.set_input_files({
        "name": "regional.csv", "mimeType": "text/csv", "buffer": b'exact original bytes',
    })
    selector = page.get_by_role("combobox", name="Language for att_exact_draft (CSV row 7)", exact=True)
    selector.select_option("ur")
    page.wait_for_function("""async () => {
        const selected = tabState.getTabState('submit_upload', null);
        const stored = await uploadDrafts.loadUploadDraft(selected.scope, selected.id);
        return stored.review?.languageOverrides?.['CSV row 7'] === 'ur';
    }""")
    page.reload()
    page.evaluate("mountUpload()")
    expect(selector).to_have_value("ur")
    expect(page.get_by_role("button", name="Submit 1 template to", exact=False)).to_be_disabled()
    assert page.evaluate("calls.previews.length") == 0
    page.locator('input[type="file"]').first.set_input_files({
        "name": "replacement.csv", "mimeType": "text/csv", "buffer": b'new original bytes',
    })
    page.wait_for_function("calls.previews.length === 2")
    assert page.evaluate("calls.previews[0].languageOverrides") == {}
    assert page.evaluate("tabState.getTabState('submit_language_overrides', null)") == {}
    page.evaluate("app.account = 'tcl_trans'; mountUpload()")
    expect(page.get_by_text("replacement.csv", exact=True)).to_have_count(0)
    assert page.evaluate("tabState.getTabState('submit_language_overrides', null)") == {}


def test_sms_offline_import_and_body_editing_do_not_wait_for_portal_options(upload_page):
    page = upload_page
    page.evaluate("""() => {
        app.account = 'tata'; app.channel = 'sms'; holdOptions = true;
        previews = [{template_name: smsDraft.template_name, sms_dlt: {...smsDraft,
            source_file: 'Native client.xlsx', source_ref: 'SMS!C8'}}];
        mountUpload();
    }""")
    page.get_by_label("Upload DLT CSV / Excel", exact=False).first.set_input_files({
        "name": "Native client.xlsx", "mimeType": "application/octet-stream", "buffer": b'exact sms source',
    })
    message = page.get_by_role("textbox", name="Message", exact=True)
    expect(message).to_be_editable()
    message.fill("Exact edited SMS while routing loads")
    expect(page.get_by_text("Source: Native client.xlsx · SMS!C8", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Review & whitelist (1)")).to_be_disabled()
    assert page.evaluate("calls.previews.map(call => call.verifyInventory)") == [False]
    assert page.evaluate("calls.checks") == 0
    assert page.evaluate("calls.smsReviews") == 0
    assert page.evaluate("calls.smsPosts.length") == 0


def test_sms_edit_during_inventory_keeps_new_copy_and_invalidates_old_review(upload_page):
    page = upload_page
    page.evaluate("holdSmsReview = true; smsDraft.source_ref = 'SMS!G19'; mountSms()")
    review = page.get_by_role("button", name="Review & whitelist (1)")
    expect(review).to_be_enabled()
    review.click()
    page.wait_for_function("smsReviewRequests.length === 1")
    expect(page.get_by_role("button", name="Confirm & whitelist", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Back to editing", exact=True).click()
    message = page.get_by_role("textbox", name="Message", exact=True)
    expect(message).to_be_editable()
    message.fill("Operator current SMS ₹")
    page.evaluate("smsReviewRequests[0].resolve(smsReviewRequests[0].result)")
    expect(message).to_have_value("Operator current SMS ₹")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(review).to_be_enabled()
    review.click()
    page.wait_for_function("smsReviewRequests.length === 2")
    assert page.evaluate("smsReviewRequests[1].result[0].sms_dlt.text") == "Operator current SMS ₹"
    page.evaluate("smsReviewRequests[1].resolve(smsReviewRequests[1].result)")
    checkbox = page.get_by_role("checkbox", name="I reviewed the destination", exact=False)
    expect(checkbox).to_be_enabled()
    checkbox.check()
    expect(page.get_by_role("button", name="Confirm & whitelist", exact=True)).to_be_enabled()
    expect(page.get_by_role("dialog")).to_contain_text("SMS!G19")
    expect(page.get_by_role("dialog")).to_contain_text("Operator current SMS ₹")
    assert page.evaluate("calls.smsPosts.length") == 0


def test_sms_inventory_failure_has_in_place_retry_without_reediting(upload_page):
    page = upload_page
    page.evaluate("smsReviewFailure = 'Catalog unavailable; session is still valid'; mountSms()")
    page.get_by_role("textbox", name="Message", exact=True).fill("Retained SMS after inventory failure")
    page.get_by_role("button", name="Review & whitelist (1)").click()
    expect(page.get_by_role("dialog")).to_contain_text("Catalog unavailable; session is still valid")
    expect(page.get_by_role("button", name="Confirm & whitelist", exact=True)).to_be_disabled()
    page.evaluate("smsReviewFailure = ''; mountSms()")
    assert page.evaluate("calls.smsReviews") == 1
    page.get_by_role("button", name="Retry inventory check", exact=True).click()
    checkbox = page.get_by_role("checkbox", name="I reviewed the destination", exact=False)
    expect(checkbox).to_be_enabled()
    expect(page.get_by_role("dialog")).to_contain_text("Retained SMS after inventory failure")
    assert page.evaluate("calls.smsReviews") == 2
    assert page.evaluate("calls.smsPosts.length") == 0


def _seed_completed_review_job(page, channel, *, unknown=False):
    page.evaluate("""({channel, unknown}) => {
        const account = channel === 'sms' ? 'tata' : 'tcl_promo';
        app.account = account; app.channel = channel;
        const task = {id: 'task-1', job_id: 'job-1', tenant_id: account, channel,
            source_ref: 'Workbook!C9', template_name: 'registered_exact_copy', created_at: '2026-11-20T00:00:00Z',
            retry_count: 0, status: unknown ? 'FAILED' : 'SUBMITTED',
            approval_status: unknown ? 'unknown' : 'pending',
            registration_outcome: unknown ? 'unknown' : 'verified', provider_ref_id: unknown ? undefined : 'provider-1'};
        jobSnapshots = [{job: {id: 'job-1', status: 'COMPLETED'}, tasks: [task]}];
        const result = {...task, task_id: task.id, status: task.status.toLowerCase()};
        if (channel === 'sms') {
            tabState.setTabState('sms_fixture_job', {job_id: 'job-1', status: 'COMPLETED', results: [result]});
            mountSms();
        } else {
            tabState.setTabState('submit_state', {step: 'submitted', account, channel,
                submitted: 1, results: [result], jobId: 'job-1', isStreaming: false});
            mountUpload();
        }
    }""", {"channel": channel, "unknown": unknown})


@pytest.mark.parametrize("channel", ["whatsapp", "rcs", "sms"])
def test_completed_registration_job_gets_approval_updates_without_resubmission(upload_page, channel):
    page = upload_page
    page.clock.install()
    _seed_completed_review_job(page, channel)
    page.wait_for_function("calls.jobs.length === 1")
    expect(page.get_by_role("row").filter(has_text="registered_exact_copy")).to_contain_text("Awaiting approval")
    page.evaluate("jobSnapshots[0].tasks[0].approval_status = 'approved'")
    page.clock.fast_forward(10001)
    expect(page.get_by_role("row").filter(has_text="registered_exact_copy")).to_contain_text("Approved")
    assert page.evaluate("calls.jobs.length") == 2
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 2
    assert page.evaluate("calls.jobs.every(call => !call.reconcile)") is True
    assert page.evaluate("calls.posts.length + calls.smsPosts.length") == 0


@pytest.mark.parametrize("channel", ["whatsapp", "sms"])
def test_status_reads_pause_when_hidden_and_stop_after_unmount(upload_page, channel):
    page = upload_page
    page.clock.install()
    page.evaluate("""() => {
        window.pageVisibility = 'visible';
        Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => pageVisibility});
    }""")
    _seed_completed_review_job(page, channel)
    page.wait_for_function("calls.jobs.length === 1")
    page.evaluate("pageVisibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))")
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 1
    page.evaluate("pageVisibility = 'visible'; document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("calls.jobs.length === 2")
    page.evaluate("unmount()")
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 2
    assert page.evaluate("calls.posts.length + calls.smsPosts.length") == 0


@pytest.mark.parametrize("channel", ["whatsapp", "sms"])
def test_slow_status_get_does_not_overlap_or_publish_after_scope_change(upload_page, channel):
    page = upload_page
    page.clock.install()
    page.evaluate("holdJob = true")
    _seed_completed_review_job(page, channel)
    page.wait_for_function("calls.jobs.length === 1 && typeof resolveJob === 'function'")
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 1
    page.evaluate("""() => {
        app.account = 'bajaj';
        mountUpload();
        resolveJob(jobSnapshots[0]);
    }""")
    expect(page.get_by_text("registered_exact_copy", exact=True)).to_have_count(0)
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 1
    assert page.evaluate("calls.posts.length + calls.smsPosts.length") == 0


@pytest.mark.parametrize("channel", ["whatsapp", "sms"])
def test_unknown_registration_is_not_rejected_or_automatically_replayed(upload_page, channel):
    page = upload_page
    page.clock.install()
    _seed_completed_review_job(page, channel, unknown=True)
    page.wait_for_function("calls.jobs.length === 1")
    row = page.get_by_role("row").filter(has_text="registered_exact_copy")
    expect(row).to_contain_text("Outcome unknown")
    expect(row).not_to_contain_text("Rejected")
    page.clock.fast_forward(30001)
    assert page.evaluate("calls.jobs.length") == 1
    assert page.evaluate("calls.posts.length + calls.smsPosts.length") == 0
    assert page.evaluate("calls.jobs.every(call => !call.reconcile)") is True


def test_lost_upload_submission_response_cannot_be_replayed_from_preview(upload_page):
    page = upload_page
    page.evaluate("failPost = true; mountUpload()")
    page.locator('input[type="file"]').first.set_input_files({
        "name": "uncertain.csv", "mimeType": "text/csv", "buffer": b'exact uncertain original',
    })
    submit = page.get_by_role("button", name="Submit 1 template to", exact=False)
    expect(submit).to_be_enabled()
    submit.click()
    expect(page.get_by_role("heading", name="Submission outcome unknown", exact=True)).to_be_visible()
    page.get_by_role("button", name="Back to preview", exact=True).click()
    expect(submit).to_be_disabled()
    page.evaluate("failPost = false; unmount(); mountUpload()")
    expect(page.get_by_text("uncertain.csv", exact=True)).to_be_visible()
    expect(submit).to_be_disabled()
    assert page.evaluate("calls.posts.length") == 1


def test_rcs_rich_card_and_carousel_sources_stay_beside_full_copy(upload_page):
    page = upload_page
    page.evaluate("""() => {
        app.channel = 'rcs'; holdInventory = true;
        previews = [
            {template_name: 'rich_card', source_file: 'RCS.xlsx', source_sheet: 'Rich', source_cell: 'B4',
                card_title: 'Exact rich title', card_description: 'Exact full rich message, not just its title'},
            {template_name: 'carousel', source_ref: 'Client carousel 8', source_file: 'RCS.xlsx',
                carousel_cards: [{cardTitle: 'First card title', cardDescription: 'First exact card body'},
                    {cardTitle: 'Second card title', cardDescription: 'Second exact card body'}]}
        ];
        mountUpload();
    }""")
    page.locator('input[type="file"]').first.set_input_files({
        "name": "RCS.xlsx", "mimeType": "application/octet-stream", "buffer": b'exact rcs workbook',
    })
    page.wait_for_function("inventoryRequests.length === 1")
    rich = page.get_by_role("row").filter(has_text="rich_card")
    expect(rich).to_contain_text("Rich!B4")
    expect(rich).to_contain_text("Exact full rich message, not just its title")
    carousel = page.get_by_role("row").filter(has_text="Client carousel 8")
    expect(carousel).to_contain_text("RCS.xlsx")
    expect(carousel).to_contain_text("First exact card body")
    expect(carousel).to_contain_text("Second exact card body")
    expect(page.get_by_role("button", name="Submit 2 templates to", exact=False)).to_be_disabled()
    assert page.evaluate("calls.posts.length") == 0


@pytest.mark.parametrize("field,value", [("id", "operator-2"), ("tenant_id", "all")])
def test_sms_inventory_result_is_discarded_after_operator_or_tenant_change(upload_page, field, value):
    page = upload_page
    page.evaluate("holdSmsReview = true; mountSms()")
    page.get_by_role("button", name="Review & whitelist (1)").click()
    page.wait_for_function("smsReviewRequests.length === 1")
    page.evaluate("""([field, value]) => {
        app.currentUser = {...app.currentUser, [field]: value};
        mountSms();
        smsReviewRequests[0].resolve(smsReviewRequests[0].result);
    }""", [field, value])
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert page.evaluate("calls.smsPosts.length") == 0
