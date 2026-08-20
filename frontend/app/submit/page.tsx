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
  const [autoFixAspectRatio, setAutoFixAspectRatio] = useState(true);
  const [autoFixGrammar, setAutoFixGrammar] = useState(true);
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
      const res = await submitFile(file, account, channel, user, autoFixAspectRatio, autoFixGrammar);
    } catch (err) {
      // Preserve the parsed previews so a transient failure doesn't force a re-upload.
      setState({
        step: 'error',
        message: err instanceof Error ? err.message : 'Submission failed.',
        previews: currentPreviews,
      });
    }
  }, [file, account, channel, user, currentPreviews, autoFixAspectRatio, autoFixGrammar]);
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
        <div className="space-y-4">
          {/* Aspect Ratio Alert Banner if non-16:9 images are detected */}
          {(() => {
            const warned = state.previews.filter(p => p.aspect_ratio_warnings && p.aspect_ratio_warnings.length > 0);
            if (!warned.length) return null;
            return (
              <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-3 shadow-xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-amber-500 text-white flex items-center justify-center font-bold text-sm shrink-0 mt-0.5 shadow-xs">
                      ⚠️
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-amber-950">
                        Image Aspect Ratio Warning ({warned.length} of {state.previews.length} template{warned.length === 1 ? '' : 's'} non-standard)
                      </h4>
                      <p className="text-[11px] text-amber-800/90 mt-0.5 leading-relaxed">
                        WhatsApp and RCS recommend a <strong>16:9 aspect ratio (1280x720)</strong> for header creatives. Images with square (1:1), portrait (9:16), or irregular dimensions can result in unexpected edge cropping on end-user devices.
                      </p>
                    </div>
                  </div>

                  {/* Auto-fix Toggle */}
                  <label className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-amber-300 text-xs font-semibold text-amber-900 shadow-xs cursor-pointer shrink-0 hover:bg-amber-50/50 transition-colors">
                    <input
                      type="checkbox"
                      checked={autoFixAspectRatio}
                      onChange={(e) => setAutoFixAspectRatio(e.target.checked)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>Auto-Pad to 16:9 Canvas (Recommended)</span>
                  </label>
                </div>

                {autoFixAspectRatio ? (
                  <div className="text-[11px] text-amber-900 bg-amber-100/70 p-2.5 rounded-lg border border-amber-200/80 flex items-center gap-2">
                    <span className="text-xs">✨</span>
                    <span>
                      <strong>Auto-Adjustment Enabled:</strong> The system will place non-standard images centered onto a clean 16:9 canvas with matching background padding so <strong>100% of your text, buttons, and logos</strong> remain visible on mobile devices.
                    </span>
                  </div>
                ) : (
                  <div className="text-[11px] text-amber-900 bg-white/80 p-2.5 rounded-lg border border-amber-200 flex items-center gap-2">
                    <span className="text-xs">⚠️</span>
                    <span>
                      <strong>Raw Upload Active:</strong> Images will be submitted without canvas padding. WhatsApp and RCS mobile apps may crop top/bottom edges of non-16:9 creatives.
                    </span>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Grammar & Content Quality Alert Banner if typos/rejection rules are detected */}
          {(() => {
            const grammarWarned = state.previews.filter(p => p.grammar_warnings && p.grammar_warnings.length > 0);
            if (!grammarWarned.length) return null;
            return (
              <div className="p-4 bg-blue-50/80 border border-blue-200 rounded-xl space-y-3 shadow-xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-sm shrink-0 mt-0.5 shadow-xs">
                      📝
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-blue-950">
                        Grammar &amp; Formatting Suggestions ({grammarWarned.length} of {state.previews.length} template{grammarWarned.length === 1 ? '' : 's'} flagged)
                      </h4>
                      <p className="text-[11px] text-blue-800/90 mt-0.5 leading-relaxed">
                        Spelling typos, repeated words, punctuation spacing, or Meta variable formatting rules detected in template text.
                      </p>
                    </div>
                  </div>

                  {/* Auto-fix Toggle */}
                  <label className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-blue-300 text-xs font-semibold text-blue-900 shadow-xs cursor-pointer shrink-0 hover:bg-blue-50/50 transition-colors">
                    <input
                      type="checkbox"
                      checked={autoFixGrammar}
                      onChange={(e) => setAutoFixGrammar(e.target.checked)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>Auto-Fix Grammar &amp; Typos (Recommended)</span>
                  </label>
                </div>

                {autoFixGrammar ? (
                  <div className="text-[11px] text-blue-900 bg-blue-100/70 p-2.5 rounded-lg border border-blue-200/80 flex items-center gap-2">
                    <span className="text-xs">✨</span>
                    <span>
                      <strong>Auto-Correction Enabled:</strong> Typos (e.g. &ldquo;recieved&rdquo; &rarr; &ldquo;received&rdquo;), repeated words, and spacing will be automatically cleaned before submission to maximize Meta approval speed.
                    </span>
                  </div>
                ) : (
                  <div className="text-[11px] text-blue-900 bg-white/80 p-2.5 rounded-lg border border-blue-200 flex items-center gap-2">
                    <span className="text-xs">⚠️</span>
                    <span>
                      <strong>Raw Text Mode:</strong> Text will be submitted exactly as written in your spreadsheet without typo corrections.
                    </span>
                  </div>
                )}
              </div>
            );
          })()}

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
                            <div className="space-y-1">
                              <div className="flex flex-wrap gap-1">
                                {p.components.map((c, cIdx) => {
                                  const isHeader = c.type === 'HEADER';
                                  const format = c.format ? ` (${c.format})` : '';
                                  const color = isHeader
                                    ? 'bg-blue-100 text-blue-800 border border-blue-200'
                                    : c.type === 'BODY'
                                    ? 'bg-blue-100 text-blue-800 border border-blue-200'
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

                              {p.aspect_ratio_warnings && p.aspect_ratio_warnings.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {p.aspect_ratio_warnings.map((w, wIdx) => (
                                    <span
                                      key={wIdx}
                                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-100 text-amber-800 border border-amber-200"
                                      title={w.action}
                                    >
                                      <span>⚠️ Ratio {w.current_ratio}</span>
                                      <span className="font-normal text-amber-700">({w.original_size})</span>
                                      <span className={`px-1 py-0.2 rounded font-semibold ${autoFixAspectRatio ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-700'}`}>
                                        {autoFixAspectRatio ? '→ Fix to 16:9' : '→ Keep Raw'}
                                      </span>
                                    </span>
                                  ))}
                                </div>
                              )}

                              {p.grammar_warnings && p.grammar_warnings.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {p.grammar_warnings.slice(0, 3).map((gw, gIdx) => (
                                    <span
                                      key={gIdx}
                                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-50 text-blue-800 border border-blue-200"
                                      title={gw.issue}
                                    >
                                      <span>📝 {gw.suggestion}</span>
                                      <span className={`px-1 py-0.2 rounded font-semibold ${autoFixGrammar ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-700'}`}>
                                        {autoFixGrammar ? 'Fix Active' : 'Raw'}
                                      </span>
                                    </span>
                                  ))}
                                  {p.grammar_warnings.length > 3 && (
                                    <span className="text-[9px] font-semibold text-blue-600 px-1">
                                      +{p.grammar_warnings.length - 3} more
                                    </span>
                                  )}
                                </div>
                              )}
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
        </div>
      )}
      {/* Loading state: Submitting */}
      {state.step === 'submitting' && (
        <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-10 text-center text-gray-500 space-y-4">
          <div className="flex flex-col items-center gap-3">
            <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <p className="text-sm font-semibold text-gray-800">Submitting templates to Karix API...</p>
            <p className="text-xs text-gray-400">Processing concurrent batch submission for {accountLabel}</p>
          </div>
          {currentPreviews && (
            <button
              type="button"
              onClick={() => setState({ step: 'previewed', previews: currentPreviews })}
              className="text-xs font-semibold text-gray-600 hover:text-gray-900 bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded-lg transition-colors inline-flex items-center gap-1.5 shadow-xs"
            >
              Cancel &amp; Return to Preview
            </button>
          )}
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
