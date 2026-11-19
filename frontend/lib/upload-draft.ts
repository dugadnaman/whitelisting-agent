// File bytes belong in IndexedDB, never in the JSON tab-state cache.
export type UploadDraftScope = { userId: string; tenant: string; account: string; channel: string };
export function uploadDraftScope(scope: UploadDraftScope): string {
  if (Object.values(scope).some((value) => !value) || scope.account === 'all') throw new Error('Choose an authenticated upload destination.');
  return JSON.stringify([scope.userId, scope.tenant, scope.account, scope.channel]);
}

type StoredUpload<T = unknown> = { id: string; blob: Blob; name: string; type: string; lastModified: number; review?: T };
let pending: Promise<unknown> = Promise.resolve();
let generation = 0;

function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>, version = generation): Promise<T> {
  const operation = pending.catch(() => {}).then(() => {
    if (version !== generation) throw new Error('The upload destination changed or the draft was discarded.');
    const { promise, resolve, reject } = Promise.withResolvers<T>();
    if (typeof indexedDB === 'undefined') { reject(new Error('Browser file storage is unavailable.')); return promise; }
    const opening = indexedDB.open('karix-upload-drafts', 1);
    let blocked = false;
    opening.onupgradeneeded = () => opening.result.createObjectStore('files');
    opening.onerror = () => reject(opening.error || new Error('Could not open browser file storage.'));
    opening.onblocked = () => { blocked = true; reject(new Error('Browser file storage is blocked by another tab.')); };
    opening.onsuccess = () => {
      const db = opening.result;
      if (blocked || version !== generation) { db.close(); reject(new Error('The upload destination changed or the draft was discarded.')); return; }
      db.onversionchange = () => db.close();
      try {
        const tx = db.transaction('files', mode);
        const request = action(tx.objectStore('files'));
        tx.oncomplete = () => { db.close(); resolve(request.result); };
        tx.onabort = tx.onerror = () => { db.close(); reject(tx.error || new Error('Browser file storage failed.')); };
      } catch (error) { db.close(); reject(error); }
    };
    return promise;
  });
  pending = operation;
  return operation;
}

export async function saveUploadDraft(scope: string, file: File, id: string = crypto.randomUUID()): Promise<string> {
  const version = generation;
  const stored: StoredUpload = { id, blob: file, name: file.name, type: file.type, lastModified: file.lastModified };
  await transaction('readwrite', (store) => store.put(stored, scope), version);
  if (version !== generation) throw new Error('The upload destination changed.');
  return id;
}

export async function loadUploadDraft<T>(scope: string, id: string): Promise<{ file: File; review?: T } | null> {
  const version = generation;
  const stored = await transaction<StoredUpload<T> | undefined>('readonly', (store) => store.get(scope), version);
  if (version !== generation || !stored || stored.id !== id) return null;
  if (!(stored.blob instanceof Blob) || !stored.name || typeof stored.lastModified !== 'number') throw new Error('The saved upload is damaged. Select the original file again.');
  return { file: new File([stored.blob], stored.name, { type: stored.type, lastModified: stored.lastModified }), review: stored.review };
}

/** Update only the review belonging to these exact bytes, never a newer selection. */
export async function saveUploadReview<T>(scope: string, id: string, review: T): Promise<boolean> {
  const version = generation;
  const stored = await transaction<StoredUpload | undefined>('readwrite', (store) => {
    const request = store.get(scope);
    request.onsuccess = () => {
      if (request.result?.id === id) store.put({ ...request.result, review }, scope);
    };
    return request;
  }, version);
  return version === generation && stored?.id === id;
}

export function clearUploadDrafts(): Promise<unknown> {
  generation++;
  return transaction('readwrite', (store) => store.clear());
}
