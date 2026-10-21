'use client';

import { useEffect, useRef, useState } from 'react';
import { startGoogleSignIn } from '@/lib/api';

type GoogleIdentity = {
  initialize(options: {
    client_id: string;
    nonce: string;
    callback: (response: { credential: string }) => void;
    auto_select: false;
    ux_mode: 'popup';
  }): void;
  renderButton(element: HTMLElement, options: {
    type: 'standard';
    theme: 'outline';
    size: 'large';
    text: 'signin_with';
    width: number;
  }): void;
};

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleIdentity } };
  }
}

type Props = {
  disabled: boolean;
  onCredential: (credential: string, signal: AbortSignal) => Promise<void>;
};

export default function GoogleSignIn({ disabled, onCredential }: Props) {
  const button = useRef<HTMLDivElement>(null);
  const latest = useRef({ disabled, onCredential });
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'loading' | 'ready' | 'submitting' | 'disabled' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    latest.current = { disabled, onCredential };
  }, [disabled, onCredential]);

  useEffect(() => {
    let active = true;
    let submitted = false;
    let script: HTMLScriptElement | undefined;
    let scriptTimeout: ReturnType<typeof setTimeout> | undefined;
    let challengeTimeout: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const element = button.current;
    element?.replaceChildren();
    setStatus('loading');
    setError(null);

    function fail(message: string) {
      if (!active) return;
      submitted = true;
      controller.abort();
      clearTimeout(scriptTimeout);
      clearTimeout(challengeTimeout);
      script?.remove();
      element?.replaceChildren();
      setError(message);
      setStatus('error');
    }

    async function start() {
      try {
        const config = await startGoogleSignIn(controller.signal);
        if (!active) return;
        if (!config.enabled) {
          setStatus('disabled');
          return;
        }
        const { client_id, nonce } = config;
        // The browser challenge lasts ten minutes, including script loading time.
        challengeTimeout = setTimeout(() => fail('Google sign-in expired. Please retry for a fresh sign-in challenge.'), 10 * 60 * 1000);

        function renderButton() {
          if (!active || submitted) return;
          clearTimeout(scriptTimeout);
          const identity = window.google?.accounts?.id;
          if (!identity || !element) {
            fail('Google sign-in could not load. Please retry or sign in with your password.');
            return;
          }
          try {
            identity.initialize({
              client_id,
              nonce,
              auto_select: false,
              ux_mode: 'popup',
              callback: (response) => {
                if (!active || submitted || latest.current.disabled) return;
                if (!response.credential) {
                  fail('Google did not return a sign-in credential. Please retry.');
                  return;
                }
                submitted = true;
                clearTimeout(challengeTimeout);
                setStatus('submitting');
                latest.current.onCredential(response.credential, controller.signal).catch((err: unknown) => {
                  fail(err instanceof Error ? `Google sign-in failed: ${err.message}` : 'Google sign-in failed. Please retry or use your password.');
                });
              },
            });
            identity.renderButton(element, {
              type: 'standard',
              theme: 'outline',
              size: 'large',
              text: 'signin_with',
              width: Math.max(200, Math.min(400, element.clientWidth)),
            });
            setStatus('ready');
          } catch {
            fail('Google sign-in could not initialize. Please retry or sign in with your password.');
          }
        }

        if (window.google?.accounts?.id) {
          renderButton();
          return;
        }
        script = document.createElement('script');
        script.src = 'https://accounts.google.com/gsi/client';
        script.async = true;
        script.onload = renderButton;
        script.onerror = () => fail('Google sign-in was blocked or could not load. Allow accounts.google.com, retry, or use your password.');
        scriptTimeout = setTimeout(() => fail('Google sign-in could not load. Check your connection or browser blocking settings, then retry or use your password.'), 15000);
        document.head.appendChild(script);
      } catch (err) {
        fail(err instanceof Error ? `Google sign-in is unavailable: ${err.message}` : 'Google sign-in is unavailable. Please retry or use your password.');
      }
    }

    // Defer until mounted so React Strict Mode's discarded effect starts no request.
    const startTimer = setTimeout(start, 0);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(startTimer);
      clearTimeout(scriptTimeout);
      clearTimeout(challengeTimeout);
      script?.remove();
      element?.replaceChildren();
    };
  }, [attempt]);

  if (status === 'disabled') return null;

  return (
    <div className="space-y-3 border-t border-gray-100 pt-4 min-w-0">
      <div className="text-center text-xs text-gray-500">Or sign in with your work Google account</div>
      <div ref={button} hidden={disabled || status === 'error' || status === 'submitting'} className="w-full min-w-0 overflow-hidden" />
      {(status === 'loading' || status === 'submitting') && (
        <p role="status" className="text-center text-xs text-gray-500">
          {status === 'submitting' ? 'Signing in with Google...' : 'Checking Google sign-in...'}
        </p>
      )}
      {error && (
        <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
          <p>{error}</p>
          <button type="button" disabled={disabled} onClick={() => setAttempt((value) => value + 1)} className="font-semibold underline disabled:opacity-50">
            Retry Google sign-in
          </button>
        </div>
      )}
    </div>
  );
}
