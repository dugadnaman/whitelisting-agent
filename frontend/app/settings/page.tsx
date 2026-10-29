'use client';

import { useState, useEffect, useRef } from 'react';
import { updateCredentials, testCredentials, testGemini, createAccount, deleteAccount, fetchCredentials, fetchTeam, inviteColleague, fetchMoEngageCredentials, saveMoEngageCredentials, testMoEngageConnection, canAccessAccount, authorizedAccount, accountOrganization, fetchAccessRequests, approveAccessRequest } from '@/lib/api';
import type { AccountItem, AuthUser, RequestedTenant } from '@/lib/api';
import { useApp } from '@/lib/context';
import { destinationAccountLabel } from '@/lib/destination';
import { clearTabState, setTabState } from '@/lib/tab-state';
import KarixAuthSync from '@/components/KarixAuthSync';
import { SmsDltSessionForm } from '@/components/sms-dlt';

type Banner = { type: 'success' | 'error'; message: string } | null;

export default function SettingsPage() {
  const {
    account: selectedAccount,
    channel: selectedChannel,
    setDestination,
    user: currentOperator,
    currentUser,
    accounts,
    refreshAccounts,
    getAccountLabel,
    isTenantLocked,
  } = useApp();
  const hasAccountAccess = canAccessAccount(currentUser, selectedAccount);
  const isAssigned = selectedAccount !== 'all' && hasAccountAccess;
  const teamTenant = currentUser?.role === 'superadmin'
    ? (isAssigned ? selectedAccount : undefined)
    : currentUser?.tenant_id;
  const canManageTeam = Boolean(currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin'));

  // New Account Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [newAccountName, setNewAccountName] = useState('');
  const [newAccountId, setNewAccountId] = useState('');
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [accountToDelete, setAccountToDelete] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  // WhatsApp form fields
  const [wabaAuthToken, setWabaAuthToken] = useState('');
  const [wabaId, setWabaId] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [session, setSession] = useState('');
  const [user, setUser] = useState('');
  const [manualPortalSession, setManualPortalSession] = useState(false);
  const [showMoEngage, setShowMoEngage] = useState(false);
  const [smsSessionDirty, setSmsSessionDirty] = useState(false);
  const [syncRevision, setSyncRevision] = useState(0);
  const settingsScope = `${currentUser?.id}:${currentUser?.tenant_id}:${currentUser?.role}:${selectedAccount}:${selectedChannel}:${showMoEngage ? 'moengage' : 'karix'}`;
  const [loadedScope, setLoadedScope] = useState('');
  const savedFields = useRef<Record<string, string>>({});
  const currentSettingsScope = useRef(settingsScope);
  currentSettingsScope.current = settingsScope;
  useEffect(() => {
    savedFields.current = {};
    setSmsSessionDirty(false);
    setManualPortalSession(false);
    setBearerToken('');
    setSession('');
    setUser('');
    setRcsAuthToken('');
    setPortalPassword('');
    setWabaAuthToken('');
    setEditPermanent(false);
    setGeminiApiKey('');
    setLoadedScope('');
    setWabaId('');
    setPortalUsername('');
    setTemplateNamespaceId('');
    setEntityId('');
    setRcsBotId('');
    setEsmeaddr('');
    setBanner(null);
  }, [settingsScope, syncRevision]);
  const [portalUsername, setPortalUsername] = useState('');
  const [portalPassword, setPortalPassword] = useState('');
  const [templateNamespaceId, setTemplateNamespaceId] = useState('');
  const [entityId, setEntityId] = useState('');
  const [rcsBotId, setRcsBotId] = useState('');
  const [rcsAuthToken, setRcsAuthToken] = useState('');
  const [esmeaddr, setEsmeaddr] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [geminiTesting, setGeminiTesting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [editPermanent, setEditPermanent] = useState(false);

  // MoEngage form state
  const [moeBearerToken, setMoeBearerToken] = useState('');
  const [moeRefreshToken, setMoeRefreshToken] = useState('');
  const [moeCookie, setMoeCookie] = useState('');
  const [moeBaseUrl, setMoeBaseUrl] = useState('');
  const [moeSenderId, setMoeSenderId] = useState('');
  const [moeWorkspaceId, setMoeWorkspaceId] = useState('');
  const [manualMoeSession, setManualMoeSession] = useState(false);
  const savedMoeFields = useRef<Record<string, string>>({});
  const [moeLoadedScope, setMoeLoadedScope] = useState('');
  // Load MoEngage credentials for the selected account
  useEffect(() => {
    savedMoeFields.current = {};
    setManualMoeSession(false);
    setMoeBearerToken('');
    setMoeRefreshToken('');
    setMoeCookie('');
    setMoeBaseUrl('');
    setMoeWorkspaceId('');
    setMoeSenderId('');
    setMoeLoadedScope('');
    if (!isAssigned) return;
    let ignore = false;
    async function loadMoEngage() {
      try {
        const creds = await fetchMoEngageCredentials(selectedAccount);
        if (ignore) return;
        // Renewable credentials remain server-side; only an explicit new snapshot may replace them.
        setMoeBaseUrl(creds.base_url || '');
        setMoeSenderId(creds.sender_id || '');
        setMoeWorkspaceId(creds.workspace_id || '');
        savedMoeFields.current = { base_url: creds.base_url || '', workspace_id: creds.workspace_id || '', sender_id: creds.sender_id || '' };
        setMoeLoadedScope(settingsScope);
      } catch {
        if (!ignore) setBanner({ type: 'error', message: 'Could not load MoEngage settings for this account. Retry after checking your access and connection.' });
      }
    }
    loadMoEngage();
    return () => { ignore = true; };
  }, [selectedAccount, isAssigned, settingsScope, syncRevision]);

  // Team Directory state
  const [teamMembers, setTeamMembers] = useState<AuthUser[]>([]);
  const [loadingTeam, setLoadingTeam] = useState(false);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteName, setInviteName] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [invitePassword, setInvitePassword] = useState('');
  const [inviteRole, setInviteRole] = useState('operator');
  const [inviting, setInviting] = useState(false);
  const [pendingRequests, setPendingRequests] = useState<AuthUser[]>([]);
  const [loadingRequests, setLoadingRequests] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [approvingUserId, setApprovingUserId] = useState<string | null>(null);
  const [requestFilter, setRequestFilter] = useState<RequestedTenant | ''>(() => {
    const organization = accountOrganization(selectedAccount);
    return organization === 'bajaj' || organization === 'tata' || organization === 'apparel' ? organization : '';
  });
  const canApprove = canManageTeam && Boolean(currentUser?.role === 'superadmin' || (
    currentUser && ['bajaj', 'tata', 'apparel'].includes(currentUser.tenant_id)
  ));
  const requestTenant = currentUser?.role === 'superadmin' ? requestFilter || undefined : currentUser?.tenant_id as RequestedTenant | undefined;

  useEffect(() => {
    if (!canApprove) {
      setPendingRequests([]);
      return;
    }
    let ignore = false;
    setLoadingRequests(true);
    setPendingRequests([]);
    setRequestError(null);
    fetchAccessRequests(requestTenant)
      .then((requests) => { if (!ignore) setPendingRequests(requests); })
      .catch((err) => { if (!ignore) setRequestError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!ignore) setLoadingRequests(false); });
    return () => { ignore = true; };
  }, [canApprove, requestTenant]);

  async function handleApprove(applicant: AuthUser) {
    setApprovingUserId(applicant.id);
    setRequestError(null);
    try {
      const approved = await approveAccessRequest(applicant.id);
      setPendingRequests((requests) => requests.filter((request) => request.id !== applicant.id));
      if (approved.tenant_id === teamTenant) {
        setTeamMembers((members) => [...members.filter((member) => member.id !== approved.id), approved]);
      }
      setBanner({ type: 'success', message: `Approved ${approved.name || approved.email} for ${getAccountLabel(approved.tenant_id)} as an operator.` });
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err));
    } finally {
      setApprovingUserId(null);
    }
  }

  useEffect(() => {
    if (!hasAccountAccess) return;
    let ignore = false;
    async function loadServerCreds() {
      try {
        const creds = await fetchCredentials(selectedAccount, selectedChannel);
        if (ignore) return;
        savedFields.current = {
          waba_id: creds.waba_id || '', portal_username: creds.portal_username || '',
          esmeaddr: creds.esmeaddr || '',
          template_namespace_id: creds.template_namespace_id || '', entity_id: creds.entity_id || '',
          rcs_bot_id: creds.rcs_bot_id || '', rcs_esmeaddr: creds.rcs_esmeaddr || creds.esmeaddr || '',
        };
        setGeminiApiKey('');
        if (selectedChannel === 'whatsapp') {
          setWabaAuthToken('');
          setWabaId(creds.waba_id || '');
          setEsmeaddr(creds.esmeaddr || '');
          setEntityId(creds.entity_id || '');
          setBearerToken('');
          setSession('');
          setUser('');
          setPortalUsername(creds.portal_username || '');
          setPortalPassword('');
          setTemplateNamespaceId(creds.template_namespace_id || '');
        } else if (selectedChannel !== 'sms') {
          setEntityId(creds.entity_id || '');
          setPortalUsername(creds.portal_username || '');
          setPortalPassword('');
          setRcsBotId(creds.rcs_bot_id || '');
          setRcsAuthToken('');
          setEsmeaddr(creds.rcs_esmeaddr || creds.esmeaddr || '');
        }
        setLoadedScope(settingsScope);
      } catch {
        if (ignore) return;
        setBanner({ type: 'error', message: 'Could not load organization credentials. Check your connection and company access.' });
      }
    }

    async function loadTeam() {
      setLoadingTeam(true);
      try {
        const team = await fetchTeam(teamTenant);
        if (!ignore) setTeamMembers(team || []);
      } catch {
        if (!ignore) setTeamMembers([]);
      } finally {
        if (!ignore) setLoadingTeam(false);
      }
    }

    if (isAssigned && selectedChannel !== 'sms') loadServerCreds();
    loadTeam();
    return () => {
      ignore = true;
    };
  }, [selectedAccount, selectedChannel, teamTenant, isAssigned, hasAccountAccess, settingsScope, syncRevision]);
  const isWhatsApp = selectedChannel === 'whatsapp';
  const isSms = selectedChannel === 'sms';
  const isRcs = selectedChannel === 'rcs';
  function changedFields(values: Record<string, string>, saved = savedFields.current) {
    return Object.fromEntries(Object.entries(values).filter(([key, value]) => value.trim() && value.trim() !== (saved[key] || '').trim()).map(([key, value]) => [key, value.trim()]));
  }
  function portalCredentialsForRequest() {
    if (!manualPortalSession || isSms) return {};
    if (isWhatsApp && (!bearerToken.trim() || !session.trim() || !user.trim())) {
      throw new Error('A manual WhatsApp override requires Bearer Token, Session ID, and User from one request. Supply all three or cancel the override.');
    }
    if (isRcs && !rcsAuthToken.trim()) throw new Error('A manual RCS override requires its own RCS bearer token. WhatsApp credentials cannot be reused.');
    return isWhatsApp ? { bearer_token: bearerToken.trim(), session: session.trim(), user: user.trim() }
      : { rcs_auth_token: rcsAuthToken.trim(), session: session.trim() || undefined, user: user.trim() || undefined };
  }
  function credentialMetadata(): Record<string, string> {
    return isWhatsApp
      ? { waba_auth_token: wabaAuthToken, waba_id: wabaId, esmeaddr, portal_username: portalUsername, portal_password: portalPassword, template_namespace_id: templateNamespaceId, entity_id: entityId }
      : { rcs_bot_id: rcsBotId, rcs_esmeaddr: esmeaddr, entity_id: entityId };
  }
  const hasUnsavedSettings = isAssigned && (
    Boolean(geminiApiKey.trim()) ||
    (!showMoEngage && isSms && smsSessionDirty) ||
    (!showMoEngage && loadedScope === settingsScope && (
      manualPortalSession || Object.entries(credentialMetadata()).some(([key, value]) => value.trim() !== (savedFields.current[key] || '').trim())
    )) ||
    (showMoEngage && moeLoadedScope === settingsScope && (
      manualMoeSession || Object.entries({ base_url: moeBaseUrl, workspace_id: moeWorkspaceId, sender_id: moeSenderId }).some(([key, value]) => value.trim() !== (savedMoeFields.current[key] || '').trim())
    ))
  );
  useEffect(() => {
    setTabState('settings_unsaved', hasUnsavedSettings);
  }, [hasUnsavedSettings]);
  useEffect(() => () => clearTabState('settings_unsaved'), []);
  function showConnection(moengage: boolean) {
    if (moengage === showMoEngage) return;
    if (hasUnsavedSettings && !window.confirm('Discard unsaved connection edits? Saved sessions and your whitelisting destination will not change.')) return;
    setShowMoEngage(moengage);
    setBanner(null);
  }

  function credentialDraft() {
    if (!isAssigned || loadedScope !== settingsScope) throw new Error('Wait for settings to load for the selected account and integration.');
    const changed = changedFields(credentialMetadata());
    if (manualPortalSession && !isSms && ['waba_id', 'esmeaddr', 'rcs_bot_id', 'rcs_esmeaddr'].some((key) => key in changed)) {
      throw new Error('Save the account routing identifiers first with manual override off. Then pair or replace the complete session for that configured identity.');
    }
    return { ...changed, ...portalCredentialsForRequest(),
      ...(currentUser?.role === 'superadmin' && geminiApiKey.trim() ? { gemini_api_key: geminiApiKey.trim() } : {}) };
  }
  const accountTitle = destinationAccountLabel(selectedAccount, getAccountLabel(selectedAccount));
  const channelTitle = isWhatsApp ? 'WhatsApp' : isSms ? 'SMS' : 'RCS';
  const envPrefix = selectedAccount.replace(/[^a-zA-Z0-9_]/g, '_').toUpperCase();
  const selectedAccountItem = accounts.find((a) => a.id === selectedAccount);
  const isCustomAccount = selectedAccountItem && !selectedAccountItem.is_builtin;
  async function handleCreateAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!newAccountName.trim()) return;
    setCreatingAccount(true);
    setCreateError(null);
    try {
      const created = await createAccount(
        newAccountName.trim(),
        newAccountId.trim() || undefined,
        currentOperator
      );
      await refreshAccounts();
      const switched = setDestination(created.id, selectedChannel);
      setShowAddModal(false);
      setNewAccountName('');
      setNewAccountId('');
      setBanner({ type: 'success', message: `Account "${created.name}" created.${switched ? ' Configure its connection below.' : ' Choose it in Whitelisting for when you are ready to configure its connection.'}` });
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create account');
    } finally {
      setCreatingAccount(false);
    }
  }

  async function handleConfirmDelete() {
    if (!accountToDelete) return;
    const accId = accountToDelete.id;
    const accName = accountToDelete.name;
    setDeleting(true);
    try {
      if (selectedAccount === accId && currentUser) {
        const preferred = authorizedAccount(currentUser, null);
        const fallback = preferred !== accId && canAccessAccount(currentUser, preferred)
          ? preferred
          : accounts.find((item) => item.id !== accId && canAccessAccount(currentUser, item.id))?.id;
        if (!fallback) throw new Error('No authorized destination is available. This account cannot be deleted while it is selected.');
        if (!setDestination(fallback, fallback === 'apparel' ? 'rcs' : selectedChannel)) return;
      }
      try {
        localStorage.removeItem(`karix_creds_${accId}_whatsapp`);
        localStorage.removeItem(`karix_creds_${accId}_rcs`);
        localStorage.removeItem(`karix_creds_${accId}_sms`);
        const stored = localStorage.getItem('karix_custom_accounts');
        if (stored) {
          const arr: AccountItem[] = JSON.parse(stored);
          const filtered = arr.filter((a) => a.id !== accId);
          localStorage.setItem('karix_custom_accounts', JSON.stringify(filtered));
        }
      } catch {}
      await deleteAccount(accId, currentOperator);
      await refreshAccounts();
      setAccountToDelete(null);
      setBanner({ type: 'success', message: `Account "${accName}" deleted.` });
    } catch (err) {
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to delete account',
      });
    } finally {
      setDeleting(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setBanner(null);
    try {
      const res = await testCredentials(selectedAccount, selectedChannel, {
        ...credentialDraft(),
        user_name: currentOperator,
      });
      if (currentSettingsScope.current !== settingsScope) return;
      if (res.ok) {
        setBanner({ type: 'success', message: res.message || 'Connection verified successfully!' });
      } else {
        setBanner({ type: 'error', message: res.message || 'Connection test failed.' });
      }
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Connection test failed',
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleTestGemini() {
    setGeminiTesting(true);
    setBanner(null);
    try {
      const res = await testGemini(geminiApiKey.trim());
      if (currentSettingsScope.current !== settingsScope) return;
      if (res.ok) {
        setBanner({
          type: 'success',
          message: `Gemini connected (${res.model || 'Google AI Studio'}). Semantic decisions are available.`,
        });
      } else {
        setBanner({ type: 'error', message: res.error || 'Gemini connectivity test failed.' });
      }
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Gemini connectivity test failed',
      });
    } finally {
      setGeminiTesting(false);
    }
  }

  async function handleSaveGemini() {
    if (currentUser?.role !== 'superadmin' || !isAssigned || !geminiApiKey.trim()) return;
    setSaving(true);
    setBanner(null);
    try {
      await updateCredentials({ account: selectedAccount, channel: selectedChannel, gemini_api_key: geminiApiKey.trim(), user_name: currentOperator });
      if (currentSettingsScope.current !== settingsScope) return;
      setGeminiApiKey('');
      setBanner({ type: 'success', message: 'Gemini API key saved to encrypted server storage. No portal sessions were changed.' });
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({ type: 'error', message: err instanceof Error ? err.message : 'Could not save Gemini API key.' });
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setBanner(null);
    try {
      const credsToSave = {
        account: selectedAccount,
        channel: selectedChannel,
        ...credentialDraft(),
        user_name: currentOperator,
      };
      await updateCredentials(credsToSave);
      if (currentSettingsScope.current !== settingsScope) return;
      {
        for (const key of Object.keys(savedFields.current)) {
          const value = Object.entries(credsToSave).find(([name]) => name === key)?.[1];
          if (typeof value === 'string') savedFields.current[key] = value;
        }
        setManualPortalSession(false);
        setBearerToken('');
        setSession('');
        setUser('');
        setRcsAuthToken('');
        setWabaAuthToken('');
        setPortalPassword('');
        setGeminiApiKey('');
        setSyncRevision((revision) => revision + 1);
      }

      // Run immediate test to verify
      const testRes = await testCredentials(selectedAccount, selectedChannel, { user_name: currentOperator });
      if (currentSettingsScope.current !== settingsScope) return;

      if (testRes.ok) {
        setBanner({
          type: 'success',
          message: `Saved & Verified credentials for ${accountTitle} — ${channelTitle}! (${testRes.message})`,
        });
      } else {
        setBanner({
          type: 'error',
          message: `Saved credentials for ${accountTitle} — ${channelTitle}, but verification failed. ${testRes.message}`,
        });
      }
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to save credentials',
      });
    } finally {
      setSaving(false);
    }
  }

  function moengageDraft() {
    if (!isAssigned || moeLoadedScope !== settingsScope) throw new Error('Wait for MoEngage settings to load for this account.');
    if (manualMoeSession && (!moeBearerToken.trim() || !moeRefreshToken.trim() || !moeCookie.trim())) {
      throw new Error('A manual MoEngage override requires Bearer Token, Refresh Token, and Cookie from one request. Supply all three or cancel the override.');
    }
    const metadata = changedFields({ base_url: moeBaseUrl, workspace_id: moeWorkspaceId, sender_id: moeSenderId }, savedMoeFields.current);
    if (manualMoeSession && Object.keys(metadata).length) {
      throw new Error('Save workspace metadata first with manual override off. Then connect the extension or enter a new complete session for that configured workspace.');
    }
    return { ...metadata, ...(manualMoeSession ? { bearer_token: moeBearerToken.trim(), refresh_token: moeRefreshToken.trim(), cookie: moeCookie.trim() } : {}) };
  }

  async function handleSaveMoEngage() {
    setSaving(true);
    setBanner(null);
    try {
      const draft = moengageDraft();
      await saveMoEngageCredentials(selectedAccount, draft);
      if (currentSettingsScope.current !== settingsScope) return;
      savedMoeFields.current = { base_url: moeBaseUrl.trim(), workspace_id: moeWorkspaceId.trim(), sender_id: moeSenderId.trim() };
      setManualMoeSession(false);
      setMoeBearerToken('');
      setMoeRefreshToken('');
      setMoeCookie('');
      setSyncRevision((revision) => revision + 1);
      setBanner({
        type: 'success',
        message: `MoEngage settings saved for ${accountTitle}.`,
      });
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to save MoEngage credentials',
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleTestMoEngage() {
    setTesting(true);
    setBanner(null);
    try {
      const res = await testMoEngageConnection(selectedAccount, moengageDraft());
      if (currentSettingsScope.current !== settingsScope) return;
      if (res.ok) {
        setBanner({
          type: 'success',
          message: res.template_count === undefined
            ? `MoEngage session verified for ${accountTitle}.`
            : `MoEngage connection verified for ${accountTitle} — ${res.template_count} templates accessible live in MoEngage.`,
        });
      } else {
        setBanner({
          type: 'error',
          message: res.error || 'MoEngage connection test failed.',
        });
      }
    } catch (err) {
      if (currentSettingsScope.current !== settingsScope) return;
      setBanner({
        type: 'error',
        message: err instanceof Error ? err.message : 'MoEngage connection test failed',
      });
    } finally {
      setTesting(false);
    }
  }

  if (!hasAccountAccess) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-gray-900">Account settings</h1>
        <div className="rounded-2xl border border-gray-200 bg-white p-6 space-y-2">
          <p className="text-sm font-semibold text-gray-900">{currentUser?.name}</p>
          <p className="text-sm text-gray-600">{currentUser?.email}</p>
          <p className="text-sm text-gray-600">Organization: {getAccountLabel(currentUser?.tenant_id)}</p>
          <p className="text-xs text-gray-500">Your account is pending administrator approval before you can access organization workspaces and credentials.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings &amp; Credentials</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage connections for the destination selected in Whitelisting for above.
          </p>
        </div>
      </div>

      {/* Tenant Security Notice */}
      {isTenantLocked && (
        <div className="p-3.5 bg-blue-50/70 border border-blue-200 rounded-xl text-xs text-blue-800 flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2.5">
            <span className="text-base">🔒</span>
            <div>
              <span className="font-bold">Multi-Tenant Boundary Active: </span>
              <span>Logged in as <strong>{currentUser?.name}</strong> ({currentUser?.email}). Scoped exclusively to <strong>{getAccountLabel(currentUser?.tenant_id)}</strong>.</span>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-100 text-blue-900 uppercase">
            {currentUser?.role || 'Operator'}
          </span>
        </div>
      )}


      <section aria-labelledby="connections-heading" className="space-y-3">
        <h2 id="connections-heading" className="text-lg font-bold text-gray-900">Connections</h2>
        <p className="text-sm text-gray-500">
          Connection management follows Whitelisting for. Opening an integration does not change your delivery destination or the extension’s active target.
        </p>
        {!isAssigned ? (
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-5 text-sm text-blue-900">
            Choose a specific account and channel in Whitelisting for above to manage its Karix connection or MoEngage integration. All accounts is an overview, not a connection destination.
          </div>
        ) : (
          <div className="flex flex-wrap gap-2 rounded-xl border border-gray-200 bg-white p-2">
            <button type="button" aria-pressed={!showMoEngage} onClick={() => showConnection(false)} className={`rounded-lg px-4 py-2 text-xs font-bold ${!showMoEngage ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
              {isSms ? 'VILPOWER · SMS DLT' : `Karix · ${channelTitle}`}
            </button>
            <button type="button" aria-pressed={showMoEngage} onClick={() => showConnection(true)} className={`rounded-lg px-4 py-2 text-xs font-bold ${showMoEngage ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
              MoEngage integration
            </button>
          </div>
        )}
      </section>

      {isAssigned && <>

      {/* Target Info Banner */}
      <div className="flex items-center justify-between p-4 bg-blue-50/50 border border-blue-100 rounded-xl">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-xs uppercase">
            {showMoEngage ? 'MO' : accountTitle.slice(0, 2)}
          </div>
          <div>
            <div className="text-xs font-bold text-gray-900">
              {showMoEngage ? `MoEngage integration · ${accountTitle}` : `${isSms ? 'VILPOWER DLT' : 'Karix'} connection · ${accountTitle} · ${channelTitle}`}
            </div>
            <div className="text-[11px] text-gray-500">
              {showMoEngage
                ? 'MoEngage dashboard session used to sync approved Karix RCS templates into MoEngage Settings'
                : isWhatsApp
                ? 'Karix Portal Session for Media Uploads & Official WABA Template API'
                : isSms
                ? 'DLT SMS template whitelisting via the Tata Capital VILPOWER portal; no SMS sending'
                : 'RCS bot template registration using Karix bearer authentication'}
            </div>
          </div>
        </div>

      </div>

      {/* Credential Form Card */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-6 space-y-5">
        {isAssigned && currentUser && (!isSms || showMoEngage) && (
          <KarixAuthSync key={`${settingsScope}:${syncRevision}`} account={selectedAccount} integration={showMoEngage ? 'moengage' : selectedChannel} />
        )}
        {showMoEngage ? (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label htmlFor="moe_base_url" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  MoEngage Dashboard URL
                </label>
                <input
                  id="moe_base_url"
                  type="text"
                  value={moeBaseUrl}
                  onChange={(e) => setMoeBaseUrl(e.target.value)}
                  placeholder="https://dashboard-XX.moengage.com"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  The dashboard domain shown in the browser URL bar for this brand's MoEngage workspace.
                </p>
              </div>
              <div>
                <label htmlFor="moe_sender_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  MoEngage Sender Profile ID
                </label>
                <input
                  id="moe_sender_id"
                  type="text"
                  value={moeSenderId}
                  onChange={(e) => setMoeSenderId(e.target.value)}
                  placeholder="MoEngage Sender Profile ID or Karix Bot ID (e.g. P7hzkqCcW3x96I6T)"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  The <code>sender_ids</code> value from MoEngage → Settings → SMS & RCS → Sender configuration.
                </p>
              </div>
              <div className="sm:col-span-2">
                <label htmlFor="moe_workspace_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">MoEngage Internal Workspace ID</label>
                <input id="moe_workspace_id" type="text" value={moeWorkspaceId} onChange={(event) => setMoeWorkspaceId(event.target.value)} placeholder="24-character alphanumeric ID from listApps / changeApp" className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 outline-none" />
                <p className="text-[11px] text-gray-500 mt-1">The portal’s 24-character alphanumeric workspace ID from listApps or changeApp. Preserve its exact case and confirm it belongs to this account; unknown workspaces are never adopted from browsing.</p>
              </div>
            </div>
            <p className="text-xs text-gray-600">For first-time setup, save Dashboard URL, Internal Workspace ID, and Sender Profile ID with manual override off. Then refresh Auth Sync and connect, or explicitly enter a complete session for that configured workspace. Editing metadata never resubmits saved tokens or cookies.</p>
            <label className="flex items-center gap-2 text-xs font-semibold text-gray-700">
              <input type="checkbox" checked={manualMoeSession} onChange={(event) => {
                setManualMoeSession(event.target.checked);
                setMoeBearerToken('');
                setMoeRefreshToken('');
                setMoeCookie('');
              }} />
              Explicitly replace this account’s complete MoEngage session manually
            </label>
            {manualMoeSession && <>

            <div>
              <label htmlFor="moe_bearer_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                MoEngage Bearer Token
              </label>
              <input
                id="moe_bearer_token"
                type="password"
                value={moeBearerToken}
                autoComplete="off"
                onChange={(event) => setMoeBearerToken(event.target.value)}
                placeholder="Paste the Authorization: Bearer <JWT> header from MoEngage DevTools..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Copy the Authorization bearer header from a read-only request for the configured workspace. Copy Refresh Token and Cookie from that same request; do not mix sessions.
              </p>
            </div>

            <div>
              <label htmlFor="moe_refresh_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                MoEngage Refresh Token
              </label>
              <input
                id="moe_refresh_token"
                type="password"
                autoComplete="off"
                value={moeRefreshToken}
                onChange={(event) => setMoeRefreshToken(event.target.value)}
                placeholder="Copy the refreshtoken request header from MoEngage DevTools"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Copy <code>refreshtoken</code> from the same request as the bearer token and cookie.
              </p>
            </div>

            <div>
              <label htmlFor="moe_cookie" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                MoEngage Session Cookie
              </label>
              <input
                id="moe_cookie"
                type="password"
                value={moeCookie}
                autoComplete="off"
                onChange={(event) => setMoeCookie(event.target.value)}
                placeholder="Copy the complete Cookie header from the same request"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Session cookies (<code>moe_uuid</code>, <code>moe_i_m</code>, <code>AWSALBTG</code>, etc.) that keep the dashboard session alive.
              </p>
            </div>

            <div className="p-3.5 bg-amber-50/70 border border-amber-200 rounded-xl space-y-2">
              <div className="text-xs font-bold text-amber-900 flex items-center gap-1.5">
                Manual snapshot instructions
              </div>
              <ol className="space-y-1 text-[11px] text-amber-800 list-decimal list-inside">
                <li>Open MoEngage dashboard in Chrome (logged in)</li>
                <li>Press F12 → Network tab → reload the page</li>
                <li>Open a read-only inventory request on this account’s configured dashboard host and confirm its internal workspace ID.</li>
                <li>Copy <code>authorization</code>, <code>refreshtoken</code>, and <code>cookie</code> together from that one request.</li>
                <li>Paste all three above and Save. Cancel the override to discard the draft and keep the latest saved session.</li>
              </ol>
            </div>
            </>}

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-4 border-t border-gray-100">
              <div className="text-[11px] text-gray-400">
                Enables the <span className="font-semibold text-gray-600">🔄 Sync to MoEngage</span> button on RCS template cards in Jira Briefs.
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleTestMoEngage}
                  disabled={testing || saving || !isAssigned || moeLoadedScope !== settingsScope}
                  className="flex-1 sm:flex-none px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
                <button
                  type="button"
                  onClick={handleSaveMoEngage}
                  disabled={saving || testing || !isAssigned || moeLoadedScope !== settingsScope}
                  className="flex-1 sm:flex-none px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {saving ? 'Saving...' : 'Save MoEngage Credentials'}
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
        {isWhatsApp ? (
          <>
            {/* Active / Expiring Portal Session Section */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold text-gray-900 flex items-center gap-1.5">
                    <span>Manual Karix Portal Session Override</span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                      Optional — replaces this scope’s session
                    </span>
                  </h4>
                  <p className="text-[11px] text-gray-500">
                    Leave manual override off to preserve the latest synced session. Saved portal credentials are never copied into this form. Configure and save account identifiers before replacing the session.
                  </p>
                </div>
              </div>

                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-xs font-semibold text-gray-700">
                    <input
                      type="checkbox"
                      checked={manualPortalSession}
                      onChange={(event) => {
                        setManualPortalSession(event.target.checked);
                        setBearerToken('');
                        setSession('');
                        setUser('');
                      }}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    Explicitly replace this account’s WhatsApp portal session manually
                  </label>
                  {manualPortalSession && <p className="text-xs text-amber-800">Paste all three headers from one request. Test checks this draft; Save validates and replaces only this account’s WhatsApp session. A later extension capture can replace it again. Cancel to discard this draft.</p>}
                </div>

              {manualPortalSession && (
              <div className="space-y-4 p-4 bg-gray-50/70 rounded-xl border border-gray-200">
                <div>
                  <label htmlFor="bearer_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                    Current Portal Bearer Token ({envPrefix}_KARIX_BEARER_TOKEN)
                  </label>
                  <input
                    id="bearer_token"
                    type="password"
                    value={bearerToken}
                    onChange={(e) => setBearerToken(e.target.value)}
                    placeholder="Paste Authorization: Bearer eyJhbGciOi... from rcsgui.karix.solutions DevTools"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                  />
                  <p className="text-[11px] text-gray-500 mt-1">
                    Accepts the token alone, <code>Bearer …</code>, or <code>Authorization: Bearer …</code>. Test Connection checks this portal session, not the separate WABA API token. Copy Session ID and User from the same request.
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="session" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Portal Session ID ({envPrefix}_KARIX_SESSION)
                    </label>
                    <input
                      id="session"
                      type="password"
                      value={session}
                      onChange={(e) => setSession(e.target.value)}
                      placeholder="Paste Session header from DevTools..."
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                    />
                  </div>

                  <div>
                    <label htmlFor="user" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Portal User Header ({envPrefix}_KARIX_USER)
                    </label>
                    <input
                      id="user"
                      type="text"
                      value={user}
                      onChange={(e) => setUser(e.target.value)}
                      placeholder="Paste User header from DevTools..."
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                    />
                  </div>
                </div>
              </div>
              )}
            </div>

            {/* Permanent Account Identifiers & Static API Token (Pre-Configured) */}
            <div className="mt-6 p-4 rounded-xl border border-gray-200 bg-gray-50/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold text-gray-900 flex items-center gap-1.5">
                    <span>🔒 Permanent Account Constants &amp; API Token</span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                      One-time setup
                    </span>
                  </h4>
                  <p className="text-[11px] text-gray-500">
                    Existing WABA service/API token and account identifiers require one-time provider setup. Auth Sync transfers only the separate renewable browser session; it cannot generate service keys.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditPermanent((prev) => !prev)}
                  className="px-2.5 py-1 text-[11px] font-semibold text-gray-600 hover:text-gray-900 bg-white border border-gray-200 rounded-lg shadow-2xs transition"
                >
                  {editPermanent ? 'Done' : '✏️ Override'}
                </button>
              </div>

              {!editPermanent ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 pt-1">
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Official WABA Token</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">
                      {wabaAuthToken ? 'New value entered' : 'Saved value not displayed'}
                    </div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Provider-managed API token</div>
                  </div>
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">WABA ID</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{wabaId || 'Not configured'}</div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Configured account identity</div>
                  </div>
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">DLT Entity ID</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{entityId || 'Not configured'}</div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Provider-issued entity ID</div>
                  </div>
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Namespace ID</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{templateNamespaceId || 'Not configured'}</div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Account namespace</div>
                  </div>
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">WhatsApp ESME Address</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{esmeaddr || 'Not configured'}</div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Configured WhatsApp routing identity</div>
                  </div>
                  <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Portal User</div>
                    <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{portalUsername || 'Standard'}</div>
                    <div className="text-[10px] text-gray-500 font-medium mt-0.5">Karix Workspace</div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                  <div className="sm:col-span-2">
                    <label htmlFor="waba_auth_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Official Permanent WABA API Token ({envPrefix}_WABA_AUTH_TOKEN)
                    </label>
                    <input
                      id="waba_auth_token"
                      name="waba_auth_token_field"
                      type="password"
                      autoComplete="new-password"
                      value={wabaAuthToken}
                      onChange={(e) => setWabaAuthToken(e.target.value)}
                      placeholder="Leave blank to preserve saved token..."
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                    <p className="text-[11px] text-gray-500 mt-1">Leave blank to keep the saved key. A value entered here is tested exactly as an official API token, not as a portal session. Save rejects invalid replacements and preserves the previous key.</p>
                  </div>
                  <div>
                    <label htmlFor="waba_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      WABA ID
                    </label>
                    <input
                      id="waba_id"
                      type="text"
                      value={wabaId}
                      onChange={(e) => setWabaId(e.target.value)}
                      placeholder="e.g. 286109054585247"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="whatsapp_esmeaddr" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">WhatsApp ESME Address</label>
                    <input id="whatsapp_esmeaddr" type="text" value={esmeaddr} onChange={(event) => setEsmeaddr(event.target.value)} placeholder="Provider-configured ESME address for this WhatsApp account" className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none" />
                    <p className="text-[11px] text-gray-500 mt-1">Save this account’s ESME and WABA identifiers before pairing Auth Sync. This is separate from RCS routing.</p>
                  </div>
                  <div>
                    <label htmlFor="entity_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      DLT Principal Entity ID
                    </label>
                    <input
                      id="entity_id"
                      type="text"
                      value={entityId}
                      onChange={(e) => setEntityId(e.target.value)}
                      placeholder="e.g. 1001490234791338781"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="template_namespace_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Template Namespace ID
                    </label>
                    <input
                      id="template_namespace_id"
                      type="text"
                      value={templateNamespaceId}
                      onChange={(e) => setTemplateNamespaceId(e.target.value)}
                      placeholder="e.g. 42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="portal_username" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Portal Username
                    </label>
                    <input
                      id="portal_username"
                      type="text"
                      value={portalUsername}
                      onChange={(e) => setPortalUsername(e.target.value)}
                      placeholder="e.g. TATACAPPROMO"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        ) : isSms ? (
          <SmsDltSessionForm key={settingsScope} account={selectedAccount} onDirty={setSmsSessionDirty} />
        ) : (
          <>
            {/* RCS requests use bearer authentication, not the legacy Lounge cookie. */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold text-gray-900">
                    Karix RCS Authorization
                  </h4>
                  <p className="text-[11px] text-gray-500">
                    Leave manual override off to keep the latest saved RCS session. WhatsApp credentials are never used for RCS. Configure and save routing identifiers before replacing the session.
                  </p>
                </div>
                {rcsAuthToken && (
                  <span className="text-[10px] font-semibold text-blue-700 bg-blue-50 px-2.5 py-1 rounded-full border border-blue-200 shrink-0">
                    Token entered — test to verify
                  </span>
                )}
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold text-gray-700">
                <input type="checkbox" checked={manualPortalSession} onChange={(event) => {
                  setManualPortalSession(event.target.checked);
                  setRcsAuthToken('');
                  setSession('');
                  setUser('');
                }} />
                Explicitly replace this account’s RCS session manually
              </label>
              {manualPortalSession && (
              <div className="p-4 bg-gray-50/70 rounded-xl border border-gray-200">
                <label htmlFor="rcs_auth_token" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Current RCS Bearer Token ({envPrefix}_RCS_AUTH_TOKEN)
                </label>
                <input
                  id="rcs_auth_token"
                  type="password"
                  autoComplete="off"
                  value={rcsAuthToken}
                  onChange={(e) => setRcsAuthToken(e.target.value)}
                  placeholder="Paste the token, Bearer token, or Authorization: Bearer token"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors bg-white"
                />
                <p className="text-[11px] text-gray-400 mt-1">
                  Test Connection checks this token against the RCS template API without saving it.
                  After a successful test, save it to use for whitelisting. A Lounge session cookie is not an RCS bearer token.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
                  <label className="text-xs text-gray-700">Session header (if present on that request)
                    <input type="password" autoComplete="off" value={session} onChange={(event) => setSession(event.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono" />
                  </label>
                  <label className="text-xs text-gray-700">User header (if present on that request)
                    <input type="password" autoComplete="off" value={user} onChange={(event) => setUser(event.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono" />
                  </label>
                </div>
              </div>
              )}
            </div>

            {/* RCS routing identifiers are separate from the editable bearer token. */}
            <div className="mt-6 p-4 rounded-xl border border-gray-200 bg-gray-50/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold text-gray-900 flex items-center gap-1.5">
                    <span>RCS Routing Identifiers</span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                      Account routing
                    </span>
                  </h4>
                  <p className="text-[11px] text-gray-500">
                    Bot ID, ESME routing address, and entity ID for {accountTitle}.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditPermanent((prev) => !prev)}
                  className="px-2.5 py-1 text-[11px] font-semibold text-gray-600 hover:text-gray-900 bg-white border border-gray-200 rounded-lg shadow-2xs transition"
                >
                  {editPermanent ? 'Done' : '✏️ Override'}
                </button>
              </div>

              {!editPermanent ? (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pt-1">
                    <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">
                        {selectedAccount === 'apparel' ? 'RCS Bot IDs (10 Bots Active)' : 'RCS Bot ID'}
                      </div>
                      <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{rcsBotId || 'Not configured'}</div>
                      <div className="text-[10px] text-gray-500 font-medium mt-0.5">Configured brand bot</div>
                    </div>
                    <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Karix ESME Address</div>
                      <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{esmeaddr || 'Not configured'}</div>
                      <div className="text-[10px] text-gray-500 font-medium mt-0.5">ESME routing address</div>
                    </div>
                    <div className="p-2.5 bg-white rounded-lg border border-gray-200 shadow-2xs">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">DLT Principal Entity ID</div>
                      <div className="text-xs font-mono font-bold text-gray-900 mt-0.5 truncate">{entityId || 'Not configured'}</div>
                      <div className="text-[10px] text-gray-500 font-medium mt-0.5">Provider-issued entity ID</div>
                    </div>
                  </div>
                  {selectedAccount === 'apparel' && (
                    <div className="p-3 bg-white rounded-lg border border-gray-200 shadow-2xs space-y-1.5 mt-2">
                      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">
                        All Configured Apparel RCS Sender IDs (10 Karix Bot IDs)
                      </div>
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {[
                          "P7hzkqCcW3x96I6T",
                          "6aa232b4734aa52ea966d1b4",
                          "6aa23696b110433d2a28c793",
                          "6aa2396e734aa52ea966d23f",
                          "6aa23c2d734aa52ea966d26f",
                          "axf2bekeNANA8h90",
                          "pp6wKCHJhdAlvEP6",
                          "Wk4lAtdRnQmXTHXF",
                          "Wk4lBploJGyg1Dlr",
                          "Wk5ESRsm6mAwxjZo"
                        ].map((id) => (
                          <span key={id} className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-purple-50 text-purple-700 border border-purple-200">
                            {id}
                          </span>
                        ))}
                      </div>
                      <p className="text-[10px] text-gray-400">
                        All 10 sender IDs are active for Karix inventory queries, template sync, and MoEngage routing.
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-1">
                  <div>
                    <label htmlFor="rcs_bot_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Karix RCS Bot ID
                    </label>
                    <input
                      id="rcs_bot_id"
                      type="text"
                      value={rcsBotId}
                      onChange={(e) => setRcsBotId(e.target.value)}
                      placeholder="e.g. Uv9tdd0KNADbq3pX"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="esmeaddr" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      Karix ESME Address
                    </label>
                    <input
                      id="esmeaddr"
                      type="text"
                      value={esmeaddr}
                      onChange={(e) => setEsmeaddr(e.target.value)}
                      placeholder="e.g. 72434700000000"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor="entity_id" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                      DLT Entity ID
                    </label>
                    <input
                      id="entity_id"
                      type="text"
                      value={entityId}
                      onChange={(e) => setEntityId(e.target.value)}
                      placeholder="e.g. 1001490234791338781"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {/* Action Buttons */}
        {!isSms && <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-4 border-t border-gray-100">
          <div className="text-[11px] text-gray-400">
            Current operator: <span className="font-semibold text-gray-600">{currentOperator}</span>
          </div>
          <p className="text-[11px] text-gray-500">Test Connection checks unsaved edits when present; otherwise it checks the saved connection. Testing does not save credentials.</p>

          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => { setLoadedScope(''); setSyncRevision((revision) => revision + 1); }} disabled={testing || saving || !isAssigned || loadedScope !== settingsScope} className="px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-100 rounded-lg disabled:opacity-50">Discard unsaved edits</button>
            <button
              type="button"
              onClick={handleTest}
              disabled={testing || saving || !isAssigned || loadedScope !== settingsScope}
              className="flex-1 sm:flex-none px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {testing ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Testing...
                </>
              ) : (
                'Test Connection'
              )}
            </button>

            <button
              type="button"
              onClick={handleSave}
              disabled={saving || testing || !isAssigned || loadedScope !== settingsScope}
              className="flex-1 sm:flex-none px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {saving ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Saving...
                </>
              ) : (
                'Save Credentials'
              )}
            </button>
          </div>
        </div>}
          </>
        )}
      </div>

      {/* Gemini Semantic Decision Engine */}
      {currentUser?.role === 'superadmin' && <div className="bg-white rounded-xl border border-violet-200 shadow-xs p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-gray-900">Gemini Semantic Decision Engine</h3>
            <p className="text-[11px] text-gray-500 mt-1">
              Uses Google Gemini for supreme semantic decisions on identified components: category, language,
              template completeness, and rejecting internal workflow identifiers (like ticket keys and sheet names) from customer headings.
            </p>
          </div>
          <span className="shrink-0 px-2 py-1 rounded-md bg-violet-50 text-violet-700 text-[10px] font-bold uppercase tracking-wide">
            AI-assisted
          </span>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <label htmlFor="gemini_api_key" className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
              Google AI Studio API Key
            </label>
            <input
              id="gemini_api_key"
              type="password"
              value={geminiApiKey}
              onChange={(e) => setGeminiApiKey(e.target.value)}
              placeholder="Paste GEMINI_API_KEY"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-violet-500 focus:border-violet-500 outline-none transition-colors"
            />
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={handleTestGemini}
              disabled={geminiTesting || saving || !geminiApiKey.trim()}
              className="w-full sm:w-auto px-4 py-2 bg-violet-100 hover:bg-violet-200 text-violet-800 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              {geminiTesting ? 'Testing...' : 'Test Gemini'}
            </button>
            <button type="button" onClick={handleSaveGemini} disabled={saving || geminiTesting || !isAssigned || !geminiApiKey.trim()} className="ml-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-semibold disabled:opacity-50">
              {saving ? 'Saving...' : 'Save Gemini key'}
            </button>
          </div>
        </div>
        <p className="text-[11px] text-gray-400">
          One-time setup with an existing Google AI Studio API key; the browser cannot generate it.
          Save the key to encrypted server storage. Leave it blank to preserve the saved key.
        </p>
      </div>}
      </>}
      <details className="rounded-2xl border border-gray-200 bg-white p-6">
        <summary className="cursor-pointer text-sm font-bold text-gray-900">Team &amp; administration</summary>
        <div className="pt-5 space-y-4">
        {!isTenantLocked && (
          <button
            onClick={() => {
              setShowAddModal(true);
              setCreateError(null);
            }}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors self-start sm:self-auto"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add New Account
          </button>
        )}
          {!isTenantLocked && isCustomAccount && selectedAccountItem && (
            <button type="button" onClick={() => setAccountToDelete({ id: selectedAccountItem.id, name: selectedAccountItem.name })} className="rounded-lg border border-red-200 px-3.5 py-2 text-xs font-semibold text-red-700 hover:bg-red-50">
              Delete {accountTitle} account
            </button>
          )}
          <div className="space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-gray-100">
          <div>
            <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
              <span>👥 Organization Team Directory</span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                {teamMembers.length} Members
              </span>
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Team accounts registered for <strong>{teamTenant ? getAccountLabel(teamTenant) : 'all organizations'}</strong>.
            </p>
          </div>
          {canManageTeam && Boolean(teamTenant) && (
            <button
              type="button"
              onClick={() => setShowInviteModal(true)}
              className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-2xs transition flex items-center gap-1.5"
            >
              <span>➕ Add Colleague</span>
            </button>
          )}
        </div>

        {loadingTeam ? (
          <div className="py-6 text-center text-xs text-gray-400">Loading team members...</div>
        ) : teamMembers.length === 0 ? (
          <div className="py-6 text-center text-xs text-gray-400">No team members registered yet for this organization.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {teamMembers.map((member) => (
              <div
                key={member.id || member.email}
                className="p-3.5 rounded-xl border border-gray-200 bg-gray-50/50 flex items-start gap-3 hover:bg-white hover:border-blue-300 transition"
              >
                <div className="w-8 h-8 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-2xs">
                  {(member.name || member.email || 'U').charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-1">
                    <h4 className="text-xs font-bold text-gray-900 truncate">{member.name}</h4>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase font-mono ${
                        member.role === 'superadmin'
                          ? 'bg-emerald-100 text-emerald-800'
                          : member.role === 'admin'
                          ? 'bg-purple-100 text-purple-800'
                          : 'bg-blue-100 text-blue-800'
                      }`}
                    >
                      {member.role || 'Operator'}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-500 font-mono truncate">{member.email}</p>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-gray-400">
                    <span className="font-semibold text-gray-600">{getAccountLabel(member.tenant_id)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {canApprove && (
          <section className="border-t border-gray-100 pt-4 space-y-3" aria-labelledby="access-requests-heading">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4 id="access-requests-heading" className="text-sm font-bold text-gray-900">Pending access requests</h4>
                <p className="text-xs text-gray-500">Approval grants operator access only to the requested organization.</p>
              </div>
              {currentUser?.role === 'superadmin' && (
                <div>
                  <label htmlFor="access-request-filter" className="block text-xs font-semibold text-gray-600 mb-1">Requested organization</label>
                  <select id="access-request-filter" value={requestFilter} disabled={Boolean(approvingUserId)} onChange={(e) => setRequestFilter(e.target.value as RequestedTenant | '')} className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs">
                    <option value="">All organizations</option>
                    <option value="bajaj">Bajaj Finserv</option>
                    <option value="tata">Tata Capital</option>
                    <option value="apparel">Apparel</option>
                  </select>
                </div>
              )}
            </div>
            {requestError && <p role="alert" className="text-xs text-red-700">{requestError}</p>}
            {loadingRequests ? (
              <p role="status" className="py-3 text-xs text-gray-500">Loading access requests...</p>
            ) : pendingRequests.length === 0 ? (
              <p className="py-3 text-xs text-gray-500">No pending requests for {requestTenant ? getAccountLabel(requestTenant) : 'any organization'}.</p>
            ) : (
              <div className="space-y-2">
                {pendingRequests.map((applicant) => (
                  <div key={applicant.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50/50 p-3">
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-gray-900">{applicant.name}</p>
                      <p className="text-xs text-gray-600 break-all">{applicant.email}</p>
                      <p className="text-xs text-blue-700 mt-1">Requested: {getAccountLabel(applicant.requested_tenant_id || '')}</p>
                    </div>
                    <button type="button" disabled={Boolean(approvingUserId)} onClick={() => handleApprove(applicant)} aria-label={`Approve ${applicant.name || applicant.email} for ${getAccountLabel(applicant.requested_tenant_id || '')}`} className="rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 px-3.5 py-2 text-xs font-semibold text-white">
                      {approvingUserId === applicant.id ? 'Approving...' : 'Approve'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
        </div>
      </details>

      {/* Invite Modal */}
      {showInviteModal && canManageTeam && teamTenant && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-gray-100 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900">Add Team Colleague</h3>
              <button onClick={() => setShowInviteModal(false)} className="text-gray-400 hover:text-gray-600 font-bold">
                &times;
              </button>
            </div>
            <p className="text-xs text-gray-500">
              Create a new user account for {getAccountLabel(teamTenant || selectedAccount)}. Share the initial password securely.
            </p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!canManageTeam || !teamTenant) return;
                setInviting(true);
                try {
                  await inviteColleague(inviteEmail.trim(), invitePassword, inviteName.trim(), inviteRole, teamTenant);
                  setShowInviteModal(false);
                  const nameSaved = inviteName.trim();
                  setInviteName('');
                  setInviteEmail('');
                  setInvitePassword('');
                  const team = await fetchTeam(teamTenant);
                  setTeamMembers(team || []);
                  setBanner({ type: 'success', message: `Added ${nameSaved} to ${getAccountLabel(teamTenant || selectedAccount)}!` });
                } catch (err) {
                  setBanner({ type: 'error', message: err instanceof Error ? err.message : String(err) });
                } finally {
                  setInviting(false);
                }
              }}
              className="space-y-3"
            >
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Full Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Rahul Sharma"
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Work Email <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  required
                  placeholder="e.g. rahul@attributics.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Initial Password <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  required
                  minLength={12}
                  autoComplete="new-password"
                  placeholder="At least 12 characters (maximum 72 UTF-8 bytes)"
                  value={invitePassword}
                  onChange={(e) => setInvitePassword(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Role
                </label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs bg-white focus:ring-2 focus:ring-blue-500 outline-none"
                >
                  <option value="operator">Operator (Preview, Submit, Poll)</option>
                  <option value="admin">Admin (Manage Team & Credentials)</option>
                </select>
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="px-3.5 py-2 text-xs text-gray-600 hover:bg-gray-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={inviting}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg text-xs font-semibold"
                >
                  {inviting ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Banner */}
      {banner && (
        <div
          className={`p-4 rounded-xl text-xs font-medium flex items-start gap-3 border ${
            banner.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : 'bg-red-50 text-red-800 border-red-200'
          }`}
        >
          {banner.type === 'success' ? (
            <svg className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-red-600 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          )}
          <span className="flex-1 leading-relaxed">{banner.message}</span>
          <button onClick={() => setBanner(null)} className="text-gray-400 hover:text-gray-600 text-sm font-bold">
            &times;
          </button>
        </div>
      )}

      {/* Add Account Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-gray-100 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900">Add New Client Account</h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-gray-400 hover:text-gray-600 font-bold"
              >
                &times;
              </button>
            </div>

            <p className="text-xs text-gray-500">
              Create a new client environment (e.g. Kotak Mahindra, HDFC Bank, Axis, Groww). Each account maintains its own isolated credentials and template logs.
            </p>

            <form onSubmit={handleCreateAccount} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Account Display Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Kotak Mahindra Bank"
                  value={newAccountName}
                  onChange={(e) => setNewAccountName(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">
                  Account Identifier Slug <span className="text-gray-400 font-normal">(Optional)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. kotak (auto-generated if empty)"
                  value={newAccountId}
                  onChange={(e) => setNewAccountId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                />
              </div>

              {createError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg">
                  {createError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingAccount || !newAccountName.trim()}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {creatingAccount ? 'Creating...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {accountToDelete && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-xl border border-gray-100 space-y-4">
            <div className="flex items-center gap-3 text-red-600">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-red-600" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-gray-900">Delete Account?</h3>
                <p className="text-xs text-gray-500">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-xs text-gray-600 leading-relaxed">
              Are you sure you want to delete <span className="font-bold text-gray-900">&quot;{accountToDelete.name}&quot;</span>? All saved WABA tokens, IDs, and configurations for this brand will be removed.
            </p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setAccountToDelete(null)}
                disabled={deleting}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {deleting ? 'Deleting...' : 'Delete Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
