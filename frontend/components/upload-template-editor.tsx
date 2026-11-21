'use client';

import { useState } from 'react';
import type { Channel, TemplatePreview, UploadTemplatePatch } from '@/lib/api';
import { normalizeNewTemplateName } from '@/lib/jira-template-name';
import { isUrlCta } from '@/lib/cta';

type Row = Record<string, unknown>;
type Component = NonNullable<TemplatePreview['components']>[number];
const text = (value: unknown): string => typeof value === 'string' ? value : '';
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter((item): item is Row => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
const pick = (value: Row, keys: string[]): Row => Object.fromEntries(keys.filter((key) => value[key] !== undefined && value[key] !== null).map((key) => [key, value[key]]));
const component = (preview: TemplatePreview, type: string) => preview.components?.find((item) => item.type === type);
const cardField = (card: Row, snake: string, camel: string) => camel in card ? camel : snake;
const actionType = (button: Row) => text(button.type || button.suggestionType || 'URL');
const actionLabel = (button: Row) => text(button.text || button.label);
const phone = (button: Row) => text(button.phone_number || button.phoneNumber);
const samples = (value: unknown): string[] => Array.isArray(value) ? value.map(text) : [];
const message = (preview: TemplatePreview) => [component(preview, 'BODY')?.text, component(preview, 'FOOTER')?.text].filter(Boolean).join('\n\n');
const languages = ['en', 'hi', 'mr', 'gu', 'pa', 'bn', 'ta', 'te', 'kn', 'ml', 'ur', 'or', 'as'];
type RcsLayout = { orientation?: string; height?: string; width?: string; template_category?: string; thumbnail_url?: string };

function publicHttps(value: string): boolean {
  if (/\s/.test(value)) return false;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return false;
    if (host === 'localhost' || /\.(localhost|local|internal)$/.test(host)) return false;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b] = host.split('.').map(Number);
      return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127));
    }
    if (host.startsWith('[')) return /^\[2[0-9a-f]{3}:/.test(host);
    return host.includes('.');
  } catch { return false; }
}

// Send editable content only. Source identity and embedded creative references remain server-owned.
export function uploadTemplatePatch(preview: TemplatePreview, channel: Channel): UploadTemplatePatch {
  if (channel === 'whatsapp') return {
    template_name: preview.template_name, category: preview.category || 'MARKETING', language: preview.language || '',
    components: (preview.components || []).filter((item) => item.type !== 'FOOTER').map((item) => {
      if (item.type === 'BUTTONS') return { type: item.type, buttons: rows(item.buttons).map((button) => pick(button, ['type', 'text', ...(button.type === 'URL' ? ['url', 'example'] : button.type === 'PHONE_NUMBER' ? ['phone_number'] : [])])) };
      const example = pick((item.example || {}) as Row, item.type === 'HEADER' ? ['header_text'] : ['body_text']);
      return {
        ...pick(item, item.type === 'HEADER' ? ['type', 'text', 'format', 'media_url'] : ['type', 'text']),
        type: item.type, ...(item.type === 'BODY' ? { text: message(preview) } : {}),
        ...(Object.keys(example).length ? { example } : {}),
      };
    }),
  };
  const editableSuggestion = (item: Row) => pick(item, ['suggestionType', 'text', 'postbackData', ...(item.suggestionType === 'url_action' ? ['url'] : item.suggestionType === 'dialer_action' ? ['phoneNumber'] : [])]);
  return {
    ...pick(preview, ['template_name', 'template_type', 'template_category',
      ...(preview.template_type === 'carousel' ? ['height', 'width']
        : preview.template_type === 'richcard' ? ['card_title', 'card_description', 'media_url', 'orientation', 'height'] : ['text_message']),
      ...(preview.media_url === '' ? ['media_url'] : [])]),
    suggestions: rows(preview.suggestions).map(editableSuggestion),
    ...(preview.template_type === 'carousel' ? { carousel_cards: rows(preview.carousel_cards).map((card) => ({
      ...pick(card, ['cardTitle', 'cardDescription', 'mediaUrl', 'card_title', 'card_description', 'media_url']),
      suggestions: rows(card.suggestions).map(editableSuggestion),
    })) } : {}),
  };
}

function ButtonList({ buttons }: { buttons: Row[] }) {
  return <section aria-label="Buttons" data-testid="upload-buttons" className="space-y-2 border-t border-gray-200 pt-3">
    <h4 className="text-xs font-medium text-gray-600">Buttons</h4>
    {!buttons.length && <p className="text-xs text-gray-500">No buttons</p>}
    {buttons.map((button, index) => <div key={index} className="space-y-1 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
      <p dir="auto" className="font-medium">{actionLabel(button) || 'Unlabelled button'} <span className="text-xs font-normal text-gray-500">· {actionType(button)}</span></p>
      {!!button.url && <p className="break-all text-xs">Destination URL: {text(button.url)}</p>}
      {!!phone(button) && <p className="break-all text-xs">Phone: {phone(button)}</p>}
      {actionType(button) === 'QUICK_REPLY' || actionType(button) === 'reply' ? <p className="text-xs">Quick reply</p> : null}
      {!!button.postbackData && <p dir="auto" className="break-all text-xs">Postback data: {text(button.postbackData)}</p>}
      {samples(button.example).map((sample, sampleIndex) => <p key={sampleIndex} className="break-all text-xs">URL example: {sample}</p>)}
    </div>)}
  </section>;
}

export function UploadTemplateContent({ preview, channel }: { preview: TemplatePreview; channel: Channel }) {
  if (channel === 'whatsapp') return <div className="space-y-3">
    {['HEADER', 'BODY', 'FOOTER'].map((type) => {
      const item = component(preview, type);
      if (!item) return null;
      const example = item.example as Row | undefined;
      return <section key={type} data-testid={`upload-${type.toLowerCase()}`} className="space-y-1">
        <h4 className="text-xs font-medium text-gray-600">{type === 'BODY' ? 'Message' : type === 'HEADER' ? 'Header' : 'Footer'}{item.format && item.format !== 'TEXT' ? ` · ${item.format}` : ''}</h4>
        {item.text && <pre dir="auto" className="whitespace-pre-wrap break-words rounded-lg border border-gray-200 bg-white p-4 font-sans text-sm leading-relaxed">{item.text}</pre>}
        {!!item.media_url && <p className="break-all text-xs">Media URL: {text(item.media_url)}</p>}
        {!!item.thumbnail_url && <img src={text(item.thumbnail_url)} alt="Original header creative" className="max-h-48 rounded-lg object-contain" />}
        {samples(example?.header_handle).map((sample, index) => <p key={index} className="break-all text-xs">Source creative / media sample: {sample}</p>)}
        {samples(example?.header_text).map((sample, index) => <p key={index} dir="auto" className="text-xs">Header sample {index + 1}: {sample}</p>)}
        {Array.isArray(example?.body_text) && (example.body_text as unknown[]).map((set, index) => <p key={index} dir="auto" className="text-xs">Variable samples: {samples(set).join(' · ')}</p>)}
      </section>;
    })}
    <ButtonList buttons={rows(component(preview, 'BUTTONS')?.buttons)} />
  </div>;
  const kind = preview.template_type || 'text';
  const rcsBody = kind === 'richcard' ? preview.card_description ?? preview.template_message ?? preview.text_message : preview.text_message ?? preview.template_message;
  return <div className="space-y-3">
    {kind === 'richcard' && preview.card_title && <section><h4 className="text-xs font-medium text-gray-600">Title</h4><p dir="auto" className="font-medium">{preview.card_title}</p></section>}
    {kind !== 'carousel' && rcsBody && <section data-testid="upload-body"><h4 className="text-xs font-medium text-gray-600">Message</h4><pre dir="auto" className="whitespace-pre-wrap break-words rounded-lg border border-gray-200 bg-white p-4 font-sans text-sm leading-relaxed">{rcsBody}</pre></section>}
    {kind === 'richcard' && preview.media_url && <p className="break-all text-xs">Media URL: {preview.media_url}</p>}
    {kind === 'richcard' && !!(preview as TemplatePreview & Row).thumbnail_url && <img src={text((preview as TemplatePreview & Row).thumbnail_url)} alt="Original rich card creative" className="max-h-48 rounded-lg object-contain" />}
    <ButtonList buttons={rows(preview.suggestions)} />
    {kind === 'carousel' && rows(preview.carousel_cards).map((card, index) => <section key={index} className="space-y-2 rounded-xl border border-gray-200 p-4">
      <h4 className="text-xs font-medium text-gray-600">Card {index + 1}</h4>
      <p dir="auto" className="font-medium">{text(card.cardTitle || card.card_title || card.title)}</p>
      <pre dir="auto" className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">{text(card.cardDescription || card.card_description || card.description || card.text)}</pre>
      {!!(card.mediaUrl || card.media_url) && <p className="break-all text-xs">Media URL: {text(card.mediaUrl || card.media_url)}</p>}
      {!!card.thumbnail_url && <img src={text(card.thumbnail_url)} alt={`Original card ${index + 1} creative`} className="max-h-48 rounded-lg object-contain" />}
      <ButtonList buttons={rows(card.suggestions)} />
    </section>)}
  </div>;
}

export function UploadOriginalSource({ preview, channel }: { preview: TemplatePreview; channel: Channel }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-xs font-medium text-gray-600">Original source preview (unchanged)</summary>
    {open && <p dir="auto" className="mt-2 break-words text-xs text-gray-500">{[preview.source_file, preview.source_sheet, preview.source_cell, preview.source_ref].filter(Boolean).join(' · ')}</p>}
    {open && <div className="mt-3 space-y-2"><p className="break-words font-mono text-xs text-gray-500">{preview.template_name}</p><UploadTemplateContent preview={preview} channel={channel} /></div>}
  </details>;
}

function Field({ label, value, onChange, multiline = false, onBlur }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean; onBlur?: () => void }) {
  const className = 'mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500';
  return <label className="block text-xs text-gray-600">{label}{multiline
    ? <textarea aria-label={label} dir="auto" rows={4} value={value} onChange={(event) => onChange(event.target.value)} onBlur={onBlur} className={className} />
    : <input aria-label={label} dir="auto" value={value} onChange={(event) => onChange(event.target.value)} onBlur={onBlur} className={className} />}</label>;
}

function ButtonsEditor({ buttons, onChange, rcs = false }: { buttons: Row[]; onChange: (value: Row[]) => void; rcs?: boolean }) {
  const update = (index: number, patch: Row) => onChange(buttons.map((button, i) => i === index ? { ...button, ...patch } : button));
  return <section aria-label="Edit buttons" className="space-y-3 border-t border-gray-200 pt-3">
    <div className="flex items-center justify-between gap-3"><h4 className="text-xs font-medium text-gray-700">Buttons</h4><button type="button" disabled={buttons.length >= (rcs ? 11 : 10)} className="text-sm font-medium text-blue-700" onClick={() => onChange([...buttons, rcs ? { suggestionType: 'url_action', text: '', url: '' } : { type: 'URL', text: '', url: '' }])}>+ Add button</button></div>
    {buttons.map((button, index) => <fieldset key={index} className="space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
      <legend className="px-1 text-xs font-medium">Button {index + 1}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-gray-600">Action type<select aria-label="Action type" value={actionType(button)} className="mt-1 block w-full rounded-lg border border-gray-300 bg-white p-2 text-sm" onChange={(event) => {
          const next = { ...button, [rcs ? 'suggestionType' : 'type']: event.target.value };
          delete next.url; delete next.phone_number; delete next.phoneNumber; delete next.example;
          onChange(buttons.map((item, i) => i === index ? next : item));
        }}>
          <option value={rcs ? 'url_action' : 'URL'}>URL</option><option value={rcs ? 'reply' : 'QUICK_REPLY'}>Quick Reply</option><option value={rcs ? 'dialer_action' : 'PHONE_NUMBER'}>Phone Number</option>
        </select></label>
        <Field label="Button label" value={actionLabel(button)} onChange={(value) => update(index, { text: value })} />
      </div>
      {isUrlCta(actionType(button)) && <><Field label="Destination URL" value={text(button.url)} onChange={(value) => update(index, { url: value })} />
        {!rcs && <Field label="URL examples (one per line)" multiline value={samples(button.example).join('\n')} onChange={(value) => update(index, { example: value ? value.split('\n') : [] })} />}</>}
      {['PHONE_NUMBER', 'dialer_action'].includes(actionType(button)) && <Field label="Phone number" value={phone(button)} onChange={(value) => update(index, { [rcs ? 'phoneNumber' : 'phone_number']: value })} />}
      {rcs && <Field label="Postback data (optional)" value={text(button.postbackData)} onChange={(value) => update(index, { postbackData: value })} />}
      <button type="button" className="text-xs text-red-700 underline" onClick={() => onChange(buttons.filter((_, i) => i !== index))}>Remove button {index + 1}</button>
    </fieldset>)}
  </section>;
}

function validationError(preview: TemplatePreview, channel: Channel): string {
  if (channel === 'whatsapp' ? !/^att_[a-z0-9_]{1,508}$/.test(preview.template_name) : !/^[A-Za-z0-9_]{1,25}$/.test(preview.template_name)) return channel === 'whatsapp' ? 'Enter a name starting with att_ using lowercase letters, numbers and underscores (512 characters maximum).' : 'Enter a template name using letters, numbers and underscores (25 characters maximum).';
  const groups = channel === 'whatsapp' ? [rows(component(preview, 'BUTTONS')?.buttons)] : [rows(preview.suggestions), ...(preview.template_type === 'carousel' ? rows(preview.carousel_cards).map((card) => rows(card.suggestions)) : [])];
  if (channel === 'whatsapp') {
    if (!languages.includes(preview.language || '')) return 'Choose a supported language code: ' + languages.join(', ') + '.';
    if (!message(preview).trim() || message(preview).length > 4096) return 'Enter a message of 1–4096 characters.';
    const header = component(preview, 'HEADER');
    if ((header?.text?.length || 0) > 1024) return 'Header must be at most 1024 characters.';
    if (header?.media_url && !publicHttps(text(header.media_url))) return 'Enter a public HTTPS header media URL without credentials, or retain the original creative.';
    if (header?.format && header.format !== 'TEXT' && !header.media_url && !(header.thumbnail_url || header.media_file || samples((header.example as Row)?.header_handle).length)) return 'Choose a public HTTPS header media URL or remove the header (NONE).';
    for (const item of preview.components || []) {
      const example = item.example as Row | undefined;
      if ([...samples(example?.header_text), ...(Array.isArray(example?.body_text) ? example.body_text.flatMap(samples) : [])].some((sample) => sample.length > 2048)) return 'Variable samples must be at most 2048 characters.';
    }
  } else {
    if (!['text', 'richcard', 'carousel'].includes(preview.template_type || 'text')) return 'Choose text, richcard or carousel.';
    if (preview.template_type === 'carousel') {
      const cards = rows(preview.carousel_cards);
      if (cards.length < 2 || cards.length > 10) return 'A carousel must contain 2–10 cards.';
      if (cards.some((card) => !text(card.cardDescription ?? card.card_description).trim() || text(card.cardDescription ?? card.card_description).length > 2000 || text(card.cardTitle ?? card.card_title).length > 200)) return 'Every card needs a message (2000 characters maximum) and a title of at most 200 characters.';
      if (cards.some((card) => { const media = text(card.mediaUrl ?? card.media_url); return media && !publicHttps(media); })) return 'Enter a public HTTPS media URL for every replacement card creative.';
      if (cards.some((card) => (card.mediaUrl ?? card.media_url) === '')) return 'Every carousel card needs a creative. Choose a public HTTPS replacement or remove the card.';
    } else if (!(preview.template_type === 'richcard' ? preview.card_description : preview.text_message)?.trim()) return 'Enter a message for the selected template type.';
    if ([preview.text_message, preview.card_title, preview.card_description].some((value) => (value?.length || 0) > 4096)) return 'RCS text fields must be at most 4096 characters.';
    if (preview.media_url && !publicHttps(preview.media_url)) return 'Enter a public HTTPS media URL without credentials.';
    if (preview.template_type === 'richcard' && preview.media_url === '') return 'A rich card needs a creative. Choose a public HTTPS replacement or switch to text.';
  }
  for (const buttons of groups) {
    if (buttons.length > (channel === 'whatsapp' ? 10 : 11)) return 'Too many buttons: WhatsApp allows 10 and RCS allows 11 per message or card.';
    for (const button of buttons) {
      const allowed = channel === 'whatsapp' ? ['URL', 'QUICK_REPLY', 'PHONE_NUMBER'] : ['url_action', 'reply', 'dialer_action'];
      if (!allowed.includes(actionType(button))) return 'Choose a supported action type for every button.';
      if (!actionLabel(button).trim() || actionLabel(button).length > 25) return 'Enter a label of 1–25 characters for every button.';
      if (isUrlCta(actionType(button)) && !publicHttps(text(button.url))) return 'Enter a public HTTPS destination URL without credentials for every URL button.';
      if (['PHONE_NUMBER', 'dialer_action'].includes(actionType(button)) && !/^\+?[0-9]{3,15}$/.test(phone(button))) return 'Enter 3–15 digits, optionally starting with +, for every phone button.';
      if (samples(button.example).length > 20 || samples(button.example).some((sample) => sample.length > 2048)) return 'Enter at most 20 URL examples, each at most 2048 characters.';
      if (text(button.postbackData).length > 2048) return 'Postback data must be at most 2048 characters.';
    }
  }
  return '';
}

export function UploadTemplateEditor({ draft, channel, disabled, onChange, onSave, onCancel }: {
  draft: TemplatePreview; channel: Channel; disabled?: boolean;
  onChange: (value: TemplatePreview) => void; onSave: (value: TemplatePreview) => void; onCancel: () => void;
}) {
  const [error, setError] = useState('');
  const change = (patch: Partial<TemplatePreview & RcsLayout>) => { setError(''); onChange({ ...draft, ...patch }); };
  const updateComponent = (type: string, patch: Partial<Component>) => {
    const existing = component(draft, type);
    change({ components: existing ? draft.components!.map((item) => item === existing ? { ...item, ...patch } : item) : [...(draft.components || []), { type, ...patch }] });
  };
  const header = component(draft, 'HEADER');
  const body = component(draft, 'BODY');
  const updateExample = (type: string, key: string, value: unknown) => updateComponent(type, { example: { ...(component(draft, type)?.example as Row || {}), [key]: value } });
  const updateCard = (index: number, patch: Row) => change({ carousel_cards: rows(draft.carousel_cards).map((card, i) => i === index ? { ...card, ...patch } : card) });
  const layout = draft as TemplatePreview & RcsLayout;
  return <fieldset aria-label="Edit uploaded template" disabled={disabled} className="space-y-4 rounded-xl border border-blue-200 bg-gray-50/50 p-4">
    <Field label="Template name" value={draft.template_name} onChange={(value) => change({ template_name: value })} onBlur={channel === 'whatsapp' ? () => change({ template_name: normalizeNewTemplateName(draft.template_name) }) : undefined} />
    {channel === 'whatsapp' ? <>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-gray-600">Category<select aria-label="Category" value={draft.category || 'MARKETING'} onChange={(event) => change({ category: event.target.value })} className="mt-1 block w-full rounded-lg border border-gray-300 bg-white p-2 text-sm"><option>MARKETING</option><option>UTILITY</option><option>AUTHENTICATION</option></select></label>
        <Field label="Language code" value={draft.language || ''} onChange={(value) => change({ language: value })} />
      </div>
      <label className="block text-xs text-gray-600">Header format<select aria-label="Header format" value={header?.format || (header?.text ? 'TEXT' : 'NONE')} className="mt-1 block w-full rounded-lg border border-gray-300 bg-white p-2 text-sm" onChange={(event) => {
        if (event.target.value === 'NONE') change({ components: draft.components?.filter((item) => item.type !== 'HEADER') });
        else {
          const next = { type: 'HEADER', format: event.target.value, ...(event.target.value === 'TEXT' ? { text: '' } : {}) };
          change({ components: header ? draft.components?.map((item) => item === header ? next : item) : [next, ...(draft.components || [])] });
        }
      }}>{['NONE', 'TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT'].map((format) => <option key={format}>{format}</option>)}</select></label>
      {header && (header.format === 'TEXT' || !header.format) && <>
        <Field label="Header" value={header.text || ''} onChange={(value) => updateComponent('HEADER', { text: value })} />
        <Field label="Header variable samples (one per line)" multiline value={samples((header.example as Row)?.header_text).join('\n')} onChange={(value) => updateExample('HEADER', 'header_text', value ? value.split('\n') : [])} />
      </>}
      {header?.format && header.format !== 'TEXT' && <div className="space-y-2">
        <p className="text-xs text-gray-500">The original embedded creative is retained unless replaced. Select NONE above to remove the header and its creative.</p>
        {samples((header.example as Row)?.header_handle).map((sample, index) => <p key={index} className="break-all text-xs">Original creative reference: {sample}</p>)}
        <Field label="Header media URL" value={text(header.media_url)} onChange={(value) => {
          const next = { ...header };
          if (value) { next.media_url = value; delete next.thumbnail_url; } else delete next.media_url;
          change({ components: draft.components?.map((item) => item === header ? next : item) });
        }} />
      </div>}
      <Field label="Message" multiline value={message(draft)} onChange={(value) => change({ components: body
        ? draft.components?.filter((item) => item.type !== 'FOOTER').map((item) => item === body ? { ...item, text: value } : item)
        : [...(draft.components || []).filter((item) => item.type !== 'FOOTER'), { type: 'BODY', text: value }],
      })} />
      <p className="text-xs text-gray-500">Edit disclaimers and terms in Message, just as in Jira.</p>
      <section className="space-y-2"><h4 className="text-xs text-gray-600">Variable samples</h4>{(() => {
        const examples = (body?.example as Row)?.body_text;
        const sets = Array.isArray(examples) ? examples.map(samples) : [];
        const variables = [...new Set(message(draft).match(/\{\{\d+\}\}/g) || [])];
        if (!variables.length) return <p className="text-xs text-gray-500">No message variables</p>;
        const count = Math.max(1, sets.length);
        return Array.from({ length: count }, (_, setIndex) => <div key={setIndex} className="grid gap-2 sm:grid-cols-2">{variables.map((variable) => {
          const variableIndex = Number(variable.slice(2, -2)) - 1;
          return <Field key={variable} label={`Sample ${variable}${count > 1 ? ` (set ${setIndex + 1})` : ''}`} value={sets[setIndex]?.[variableIndex] || ''} onChange={(value) => {
            if (variableIndex < 0 || variableIndex >= 100) { setError('Use message variables {{1}} through {{100}}.'); return; }
            const next = Array.from({ length: count }, (_, index) => Array.from({ length: Math.max(variableIndex + 1, sets[index]?.length || 0) }, (_, sampleIndex) => sets[index]?.[sampleIndex] || ''));
            next[setIndex][variableIndex] = value;
            updateExample('BODY', 'body_text', next);
          }} />;
        })}</div>);
      })()}</section>
      <ButtonsEditor buttons={rows(component(draft, 'BUTTONS')?.buttons)} onChange={(buttons) => {
        if (!buttons.length) change({ components: draft.components?.filter((item) => item.type !== 'BUTTONS') });
        else updateComponent('BUTTONS', { buttons });
      }} />
    </> : <>
      <label className="block text-xs text-gray-600">Template type<select aria-label="Template type" value={draft.template_type || 'text'} onChange={(event) => {
        const type = event.target.value;
        const copy = draft.template_type === 'text' ? draft.text_message : draft.card_description;
        change({ template_type: type, text_message: type === 'text' ? copy || '' : undefined,
          card_description: type === 'richcard' ? copy || '' : undefined, template_message: undefined,
          ...(type !== 'carousel' ? { carousel_cards: undefined } : {}),
          ...(type === 'carousel' && layout.height === 'TALL' ? { height: 'MEDIUM' } : {}),
          ...(type !== 'richcard' ? { card_title: undefined, media_url: '', thumbnail_url: undefined } : {}) });
      }} className="mt-1 block w-full rounded-lg border border-gray-300 bg-white p-2 text-sm">{['text', 'richcard', 'carousel'].map((type) => <option key={type}>{type}</option>)}</select></label>
      {draft.template_type === 'richcard' && <Field label="Title" value={draft.card_title || ''} onChange={(value) => change({ card_title: value })} />}
      {draft.template_type !== 'carousel' && <Field label="Message" multiline value={(draft.template_type === 'text' ? draft.text_message : draft.card_description) ?? draft.template_message ?? ''} onChange={(value) => change(draft.template_type === 'text' || !draft.template_type ? { text_message: value, template_message: undefined } : { card_description: value, template_message: undefined })} />}
      {draft.template_type === 'richcard' && <>
        <Field label="Media URL" value={draft.media_url || ''} onChange={(value) => change({ media_url: value, thumbnail_url: undefined })} />
        <p className="text-xs text-gray-500">Keep the original creative, enter a public HTTPS replacement, or remove it explicitly.</p>
        <button type="button" className="text-xs text-red-700 underline" onClick={() => change({ media_url: '', thumbnail_url: undefined })}>Remove creative</button>
      </>}
      {draft.template_type !== 'text' && <div className="grid gap-3 sm:grid-cols-2">
          {([['orientation', 'Orientation', ['VERTICAL', 'HORIZONTAL']], ['height', 'Height', ['SHORT', 'MEDIUM', 'TALL']], ['width', 'Width', ['SMALL', 'MEDIUM']], ['template_category', 'Template category', ['TRANSACTIONAL', 'PROMOTIONAL']]] as const).filter(([key]) => draft.template_type === 'carousel' ? key !== 'orientation' : key !== 'width').map(([key, label, choices]) => <label key={key} className="block text-xs text-gray-600">{label}<select aria-label={label} value={layout[key] || ''} onChange={(event) => change({ [key]: event.target.value || undefined })} className="mt-1 block w-full rounded-lg border border-gray-300 bg-white p-2 text-sm"><option value="">Original / default</option>{choices.filter((choice) => key !== 'height' || draft.template_type !== 'carousel' || choice !== 'TALL').map((choice) => <option key={choice}>{choice}</option>)}</select></label>)}
      </div>}
      <ButtonsEditor rcs buttons={rows(draft.suggestions)} onChange={(suggestions) => change({ suggestions })} />
      {draft.template_type === 'carousel' && rows(draft.carousel_cards).map((card, index) => <fieldset key={index} className="space-y-3 rounded-xl border border-gray-200 p-4">
        <legend className="px-1 text-xs font-medium">Card {index + 1}</legend>
        <Field label="Card title" value={text(card.cardTitle ?? card.card_title)} onChange={(value) => updateCard(index, { [cardField(card, 'card_title', 'cardTitle')]: value })} />
        <Field label="Card message" multiline value={text(card.cardDescription ?? card.card_description)} onChange={(value) => updateCard(index, { [cardField(card, 'card_description', 'cardDescription')]: value })} />
        <Field label="Card media URL" value={text(card.mediaUrl ?? card.media_url)} onChange={(value) => updateCard(index, { [cardField(card, 'media_url', 'mediaUrl')]: value, thumbnail_url: undefined })} />
        <p className="text-xs text-gray-500">The original embedded card creative is retained unless replaced or removed.</p>
        <button type="button" className="text-xs text-red-700 underline" onClick={() => updateCard(index, { [cardField(card, 'media_url', 'mediaUrl')]: '', thumbnail_url: undefined })}>Remove card creative {index + 1}</button>
        <ButtonsEditor rcs buttons={rows(card.suggestions)} onChange={(suggestions) => updateCard(index, { suggestions })} />
        <button type="button" className="text-xs text-red-700 underline" onClick={() => change({ carousel_cards: rows(draft.carousel_cards).filter((_, i) => i !== index) })}>Remove card {index + 1}</button>
      </fieldset>)}
      {draft.template_type === 'carousel' && <button type="button" disabled={rows(draft.carousel_cards).length >= 10} className="workspace-button" onClick={() => change({ carousel_cards: [...rows(draft.carousel_cards), { card_title: '', card_description: '', suggestions: [] }] })}>+ Add card</button>}
    </>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="flex gap-2"><button type="button" className="workspace-button-primary" disabled={disabled} onClick={() => {
      const normalized = { ...draft, template_name: channel === 'whatsapp' ? normalizeNewTemplateName(draft.template_name) : draft.template_name,
        ...(channel === 'whatsapp' ? { components: draft.components?.filter((item) => item.type !== 'FOOTER').map((item) => item.type === 'BODY' ? { ...item, text: message(draft) } : item) } : {}) };
      const error = validationError(normalized, channel);
      if (error) { setError(error); return; }
      onSave(normalized);
    }}>Save</button><button type="button" className="workspace-button" onClick={() => { setError(''); onCancel(); }}>Cancel</button></div>
  </fieldset>;
}
