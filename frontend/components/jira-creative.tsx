'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { fetchJiraCreativeBlob, type JiraCreativeSource } from '@/lib/api';
import { formatError } from '@/lib/format';

export function JiraCreativeImage({ source, className, onPreview }: {
  source: JiraCreativeSource;
  className?: string;
  onPreview?: () => void;
}) {
  const { path, attachmentId, filename } = source;
  const sourceKey = JSON.stringify([path, attachmentId, filename]);
  const [attempt, setAttempt] = useState(0);
  const [image, setImage] = useState<{ key: string; url?: string; error?: string }>({ key: '' });

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let objectUrl: string | undefined;
    setImage({ key: sourceKey });
    fetchJiraCreativeBlob({ path, attachmentId, filename }, controller.signal)
      .then((blob) => {
        if (disposed) return;
        objectUrl = URL.createObjectURL(blob);
        setImage({ key: sourceKey, url: objectUrl });
      })
      .catch((error) => {
        if (!disposed) setImage({ key: sourceKey, error: formatError(error) });
      });
    return () => {
      disposed = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, attachmentId, filename, sourceKey, attempt]);

  const current = image.key === sourceKey ? image : { key: sourceKey };
  if (current.error) {
    return (
      <div role="alert" className="p-2 text-xs text-rose-700 space-y-1">
        <p>Unable to load creative: {current.error}</p>
        <button type="button" className="font-semibold underline" onClick={() => setAttempt((value) => value + 1)}>
          Retry preview
        </button>
      </div>
    );
  }
  if (!current.url) return <p role="status" className="p-2 text-xs text-gray-500">Loading creative…</p>;

  const imageElement = (
    <img
      src={current.url}
      alt={filename || 'Creative preview'}
      className={className}
      onError={() => setImage({ key: sourceKey, error: 'The original file could not be displayed as an image.' })}
    />
  );
  return onPreview ? (
    <button type="button" onClick={onPreview} className="block max-w-full" title="View full-size creative" aria-label={`View ${filename || 'creative'} full-size`}>
      {imageElement}
    </button>
  ) : imageElement;
}

export function JiraCreativeDownload({ source, className, children = 'Download' }: {
  source: JiraCreativeSource;
  className?: string;
  children?: ReactNode;
}) {
  const { path, attachmentId, filename } = source;
  const sourceKey = JSON.stringify([path, attachmentId, filename]);
  const [state, setState] = useState<{ key: string; loading?: boolean; error?: string }>({ key: '' });
  const download = useRef<{ controller?: AbortController; url?: string; timer?: number }>({});

  useEffect(() => () => {
    download.current.controller?.abort();
    window.clearTimeout(download.current.timer);
    if (download.current.url) URL.revokeObjectURL(download.current.url);
    download.current = {};
  }, [sourceKey]);

  const handleDownload = async () => {
    const controller = new AbortController();
    download.current.controller = controller;
    setState({ key: sourceKey, loading: true });
    try {
      const blob = await fetchJiraCreativeBlob(source, controller.signal);
      if (controller.signal.aborted) return;
      window.clearTimeout(download.current.timer);
      if (download.current.url) URL.revokeObjectURL(download.current.url);
      const url = URL.createObjectURL(blob);
      download.current.url = url;
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'creative';
      document.body.appendChild(link);
      link.click();
      link.remove();
      download.current.timer = window.setTimeout(() => {
        URL.revokeObjectURL(url);
        if (download.current.url === url) download.current.url = undefined;
      }, 1000);
      setState({ key: sourceKey });
    } catch (error) {
      if (!controller.signal.aborted) setState({ key: sourceKey, error: formatError(error) });
    }
  };

  const current = state.key === sourceKey ? state : { key: sourceKey };
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button type="button" onClick={handleDownload} disabled={current.loading} className={className}>
        {current.loading ? 'Downloading…' : current.error ? 'Retry download' : children}
      </button>
      {current.error && <span role="alert" className="text-xs text-rose-700">Download failed: {current.error}</span>}
    </span>
  );
}
