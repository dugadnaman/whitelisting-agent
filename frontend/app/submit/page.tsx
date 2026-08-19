'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { previewFile, submitFile, getSampleCsvUrl } from '@/lib/api';
import type { TemplatePreview, Template } from '@/lib/api';
import { useApp } from '@/lib/context';
import { formatError } from '@/lib/format';
function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-100 text-amber-800 border border-amber-200',
    approved: 'bg-green-100 text-green-800 border border-green-200',
    rejected: 'bg-red-100 text-red-800 border border-red-200',
    failed: 'bg-red-100 text-red-800 border border-red-200',
    submitted: 'bg-blue-100 text-blue-800 border border-blue-200',
    duplicate: 'bg-blue-100 text-blue-800 border border-blue-200',
    unknown: 'bg-gray-100 text-gray-800 border border-gray-200',
  };
  const s = (status || 'unknown').toLowerCase();
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${colors[s] || colors.unknown}`}>
      {status}
    </span>
  );
}


type State =
  | { step: 'idle' }
  | { step: 'previewing' }
  | { step: 'previewed'; previews: TemplatePreview[] }
  | { step: 'submitting' }
  | { step: 'submitted'; submitted: number; results: Template[] }
  | { step: 'error'; message: string; previews: TemplatePreview[] | null };

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

export default function SubmitPage() {
  const { account, channel, user, getAccountLabel } = useApp();
  const [state, setState] = useState<State>({ step: 'idle' });
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset state if account/channel changes while on submit page
  useEffect(() => {
    setState({ step: 'idle' });
    setFile(null);
  }, [account, channel]);

  const handleFile = useCallback(
    async (selected: File) => {
      if (!isAcceptedFile(selected)) {
        setState({ step: 'error', message: 'Please upload a .csv, .xlsx, or .xls file.', previews: null });
        return;
      }
      setFile(selected);
      setState({ step: 'previewing' });
      try {
        const previews = await previewFile(selected, account, channel);
        setState({ step: 'previewed', previews });
      } catch (err) {
        setState({
          step: 'error',
          message: err instanceof Error ? err.message : 'Failed to parse template file.',
          previews: null,
        });
      }
    },
    [account, channel]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const dropped = e.dataTransfer.files?.[0];
      if (dropped) handleFile(dropped);
    },
    [handleFile]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) handleFile(selected);
    },
    [handleFile]
  );

  const handleClear = useCallback(() => {
    setFile(null);
    setState({ step: 'idle' });
    if (inputRef.current) inputRef.current.value = '';
  }, []);
  const currentPreviews = state.step === 'previewed' ? state.previews : null;

  const handleSubmit = useCallback(async () => {
    if (!file || !currentPreviews) return;
    setState({ step: 'submitting' });
    try {
      const res = await submitFile(file, account, channel, user);
      setState({ step: 'submitted', submitted: res.submitted, results: res.results });
    } catch (err) {
      // Preserve the parsed previews so a transient failure doesn't force a re-upload.
      setState({
        step: 'error',
        message: err instanceof Error ? err.message : 'Submission failed.',
        previews: currentPreviews,
      });
    }
  }, [file, account, channel, user, currentPreviews]);

  const handleReset = useCallback(() => {
    handleClear();
  }, [handleClear]);

  const accountLabel = getAccountLabel(account);
  const channelLabel = channel === 'whatsapp' ? 'WhatsApp' : 'RCS (DLT)';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Submit Templates</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                channel === 'whatsapp'
                  ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                  : 'bg-blue-100 text-blue-800 border border-blue-200'
              }`}
            >
              {accountLabel} &bull; {channelLabel}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Upload a spreadsheet of {channelLabel} templates to validate, preview, and submit for {accountLabel}.
          </p>
        </div>

        {/* Sample download */}
        <a
          href={getSampleCsvUrl(channel)}
          download
          className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold shadow-xs transition-colors"
        >
          <svg className="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
          </svg>
          Download Sample CSV ({channelLabel})
        </a>
      </div>

      {/* STEP 1: Upload Dropzone (Visible when idle, error, previewing, previewed) */}
      {state.step !== 'submitted' && (
        <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-6">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
              dragging
                ? 'border-blue-500 bg-blue-50/50 ring-4 ring-blue-50'
                : file
                ? 'border-blue-400 bg-blue-50/20'
                : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50/50'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={handleInputChange}
              className="hidden"
            />
            <div className="flex flex-col items-center">
              <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center text-blue-600 mb-3 shadow-xs">
                <svg className="w-6 h-6" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M10 14V3M5 7l5-5 5 5M3 17h14" />
                </svg>
              </div>
              <p className="text-sm font-semibold text-gray-900">
                Drop your {channelLabel} CSV or Excel spreadsheet here
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Supports <span className="font-semibold text-gray-700">.xlsx, .xls, .csv</span> files
              </p>
            </div>
          </div>

          {/* Selected File Info */}
          {file && (
            <div className="flex items-center justify-between mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded bg-blue-100 text-blue-700 font-bold text-xs flex items-center justify-center uppercase">
                  {file.name.split('.').pop() || 'file'}
                </div>
                <div>
                  <p className="text-xs font-semibold text-gray-900">{file.name}</p>
                  <p className="text-[11px] text-gray-400">{formatBytes(file.size)}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleClear();
                }}
                className="text-xs font-semibold text-red-600 hover:text-red-800 transition-colors"
              >
                Remove
              </button>
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {state.step === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-sm text-red-700 flex items-start gap-3">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">
            <h4 className="font-semibold text-red-800">Submission Error</h4>
            <p className="mt-1 text-xs">{formatError(state.message)}</p>
            {state.previews && state.previews.length > 0 && (
              <p className="mt-1.5 text-[11px] text-red-500">
                Your parsed templates are still loaded — retry submission below.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {state.previews && state.previews.length > 0 && (
              <button
                onClick={() => setState({ step: 'previewed', previews: state.previews as TemplatePreview[] })}
                className="text-xs font-semibold text-blue-700 underline"
              >
                Back to preview
              </button>
            )}
            <button onClick={handleReset} className="text-xs font-semibold text-red-700 underline">
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Loading state: Previewing */}
      {state.step === 'previewing' && (
        <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-12 text-center text-gray-500">
          <div className="flex flex-col items-center gap-3">
            <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <p className="text-sm font-semibold text-gray-800">Parsing and validating templates...</p>
            <p className="text-xs text-gray-400">Verifying columns and component format</p>
          </div>
        </div>
      )}

      {/* STEP 2: Preview Table */}
      {state.step === 'previewed' && (
        <div className="bg-white rounded-xl border border-blue-200 shadow-xs overflow-hidden">
          <div className="p-4 bg-blue-50/60 border-b border-blue-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-600" />
                <h3 className="text-sm font-bold text-blue-950">
                  {state.previews.length} Template{state.previews.length === 1 ? '' : 's'} Found
                </h3>
              </div>
              <p className="text-xs text-blue-700/80 mt-0.5">
                Ready to submit to {accountLabel} on {channelLabel}. Review before final submission.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleClear}
                className="px-3.5 py-2 rounded-lg text-xs font-semibold text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 transition-colors"
              >
                Clear
              </button>
              <button
                onClick={handleSubmit}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-sm transition-colors flex items-center gap-2"
              >
                <span>Submit All ({state.previews.length})</span>
                <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="bg-blue-50/30 text-blue-900 font-semibold border-b border-blue-100">
                  {channel === 'whatsapp' ? (
                    <>
                      <th className="px-5 py-3">#</th>
                      <th className="px-5 py-3">Template Name</th>
                      <th className="px-5 py-3">Category</th>
                      <th className="px-5 py-3">Language</th>
                      <th className="px-5 py-3">Components</th>
                    </>
                  ) : (
                    <>
                      <th className="px-5 py-3">#</th>
                      <th className="px-5 py-3">Template Name</th>
                      <th className="px-5 py-3">Type</th>
                      <th className="px-5 py-3">Content / Title</th>
                      <th className="px-5 py-3">Buttons / Cards</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {state.previews.map((p, idx) => (
                  <tr key={idx} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3 text-gray-400 font-mono">{idx + 1}</td>
                    <td className="px-5 py-3 font-semibold text-gray-900 font-mono">{p.template_name}</td>
                    {channel === 'whatsapp' ? (
                      <>
                        <td className="px-5 py-3 text-gray-700">{p.category || 'MARKETING'}</td>
                        <td className="px-5 py-3 text-gray-700">{p.language || 'en'}</td>
                        <td className="px-5 py-3 text-gray-600">
                          {p.components?.length ? (
                            <div className="flex flex-wrap gap-1">
                              {p.components.map((c, cIdx) => {
                                const isHeader = c.type === 'HEADER';
                                const format = c.format ? ` (${c.format})` : '';
                                const color = isHeader
                                  ? 'bg-blue-100 text-blue-800 border border-blue-200'
                                  : c.type === 'BODY'
                                  ? 'bg-blue-100 text-blue-800 border-blue-200'
                                  : c.type === 'BUTTONS'
                                  ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                                  : 'bg-gray-100 text-gray-700 border-gray-200';
                                return (
                                  <span
                                    key={cIdx}
                                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border ${color}`}
                                  >
                                    {c.type}{format}
                                  </span>
                                );
                              })}
                            </div>
                          ) : (
                            'Standard'
                          )}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-5 py-3 font-semibold text-gray-800 uppercase tracking-wider text-[11px]">
                          {p.template_type || (p.carousel_cards?.length ? 'carousel' : (p.media_url ? 'richcard' : 'text'))}
                        </td>
                        <td className="px-5 py-3 text-gray-700 max-w-xs truncate">
                          {p.card_title || p.text_message || p.template_message || '—'}
                        </td>
                        <td className="px-5 py-3 text-gray-600 text-[11px]">
                          {p.carousel_cards?.length
                            ? `${p.carousel_cards.length} card(s)`
                            : p.suggestions?.length
                            ? `${p.suggestions.length} button(s)`
                            : 'No buttons'}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Loading state: Submitting */}
      {state.step === 'submitting' && (
        <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-12 text-center text-gray-500">
          <div className="flex flex-col items-center gap-3">
            <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <p className="text-sm font-semibold text-gray-800">Submitting templates to Karix API...</p>
            <p className="text-xs text-gray-400">Processing batch submission for {accountLabel}</p>
          </div>
        </div>
      )}

      {/* STEP 3: Results */}
      {state.step === 'submitted' && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center font-bold">
                  ✓
                </div>
                <div>
                  <h3 className="text-base font-bold text-gray-900">
                    Submission Complete!
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Processed {state.results.length} templates for {accountLabel} on {channelLabel}.
                  </p>
                </div>
              </div>

              <button
                onClick={handleReset}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors"
              >
                + Submit Another File
              </button>
            </div>
          </div>

          {/* Results Table */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs overflow-hidden">
            <div className="p-4 bg-gray-50/80 border-b border-gray-200 font-semibold text-xs text-gray-700">
              Batch Submission Results
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="bg-gray-50/50 text-gray-500 font-semibold border-b border-gray-200 uppercase tracking-wider text-[11px]">
                    <th className="px-5 py-3">#</th>
                    <th className="px-5 py-3">Template Name</th>
                    {channel === 'whatsapp' ? (
                      <>
                        <th className="px-5 py-3">Submission Status</th>
                        <th className="px-5 py-3">Approval</th>
                        <th className="px-5 py-3">Notes</th>
                        <th className="px-5 py-3">Submitted By</th>
                      </>
                    ) : (
                      <>
                        <th className="px-5 py-3">Karix Template ID</th>
                        <th className="px-5 py-3">Status</th>
                        <th className="px-5 py-3">Details / Response</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {state.results.map((r, idx) => (
                    <tr
                      key={idx}
                      className={r.status === 'failed' ? 'bg-red-50/40' : 'hover:bg-gray-50/50'}
                    >
                      <td className="px-5 py-3 text-gray-400 font-mono">{idx + 1}</td>
                      <td className="px-5 py-3 font-semibold text-gray-900 font-mono">{r.template_name}</td>
                      {channel === 'whatsapp' ? (
                        <>
                          <td className="px-5 py-3">
                            <StatusBadge status={r.status} />
                          </td>
                          <td className="px-5 py-3">
                            <StatusBadge status={r.approval_status || 'unknown'} />
                          </td>
                          <td className="px-5 py-3 text-gray-500">
                            {r.error ? (
                              <span className="text-red-600 font-medium">{formatError(r.error)}</span>
                            ) : (
                              'Submitted successfully'
                            )}
                          </td>
                          <td className="px-5 py-3">
                            <span className="inline-flex items-center gap-1.5">
                              <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-700 font-bold text-[10px] flex items-center justify-center shrink-0">
                                {(r.submitted_by || user || 'U').charAt(0).toUpperCase()}
                              </span>
                              <span className="text-[11px] font-semibold text-gray-700">
                                {r.submitted_by || user || '—'}
                              </span>
                            </span>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-5 py-3 font-mono font-semibold text-blue-700 text-xs">
                            {r.template_id || r.provider_ref_id || '—'}
                          </td>
                          <td className="px-5 py-3">
                            <StatusBadge status={r.status} />
                          </td>
                          <td className="px-5 py-3 text-gray-600">
                            {r.error ? (
                              <span className="text-red-600 font-medium">{formatError(r.error)}</span>
                            ) : (
                              <span className="text-emerald-700 font-medium">Template created on Karix Bot Builder</span>
                            )}
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
