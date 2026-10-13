export function newRcsTemplateName(
  base: string,
  existingNames: ReadonlySet<string>,
  variant: 'rcs' | 'rcs_manual' = 'rcs',
): string {
  const clean = base.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '');
  for (let sequence = 1; ; sequence += 1) {
    const suffix = `_${variant}_${sequence}`;
    const prefix = clean.slice(0, 25 - suffix.length).replace(/_+$/g, '');
    const candidate = `${prefix}${suffix}`;
    if (!existingNames.has(candidate)) return candidate;
  }
}
