const asar = require('./patcher/node_modules/@electron/asar');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const [before, after] = process.argv.slice(2);
const entries = archive => asar.listPackage(archive).map(p => p.slice(1)).sort();
const originals = entries(before);
if (JSON.stringify(originals) !== JSON.stringify(entries(after))) {
  throw new Error('Archive entries differ');
}
const allowed = new Set([
  'dist/preload.js', 'dist/main.js', 'dist/menu.js', 'dist/ipcHandlers.js',
  'dist/ideInstall/wizardHtml.js', 'dist/updater.js', 'dist/tray.js',
  'dist/wsl.js', 'dist/provisionSplash.js'
]);
let verifiedPreload = false;
for (const entry of originals) {
  const normalized = entry.replaceAll('\\', '/');
  const old = asar.statFile(before, entry);
  const current = asar.statFile(after, entry);
  if ('size' in old && Boolean(old.unpacked) !== Boolean(current.unpacked)) throw new Error('Changed unpack status: ' + entry);
  if (old.integrity?.hash === current.integrity?.hash) continue;
  if (!allowed.has(normalized)) throw new Error('Unexpected change: ' + entry);
  const content = asar.extractFile(after, entry);
  const checked = spawnSync(process.execPath, ['--check'], { input: content, encoding: 'utf8' });
  if (checked.status !== 0) throw new Error(checked.stderr || 'Syntax check failed: ' + entry);
  if (normalized === 'dist/preload.js') {
    const prior = asar.extractFile(before, entry);
    if (!content.subarray(0, prior.length).equals(prior)) throw new Error('Original preload altered');
    if (!content.includes('Antigravity Chinese Localization Injection Start')) {
      throw new Error('Localization missing');
    }
    verifiedPreload = true;
  }
}
if (!verifiedPreload) throw new Error('Preload was not patched');
