from datetime import datetime
from hashlib import sha256
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.json'
settings = json.loads(CONFIG.read_bytes()) if CONFIG.is_file() else {}
EXE = Path(settings.get('antigravity') or Path(os.environ['LOCALAPPDATA']) / 'Programs/antigravity/Antigravity.exe')
ARCHIVE = EXE.parent / 'resources/app.asar'
PATCHER = ROOT / 'patcher'
NODE = Path(settings.get('node') or shutil.which('node') or Path(os.environ['ProgramFiles']) / 'nodejs/node.exe')
BASE_RELEASE = 'v3.3.65'
BASE_VERSION = '2.35.2'
BASE_DICT = ROOT / 'translations/zh-CN-2.35.2-v3.3.65.json'
STATE = ROOT / 'state.json'
LOG = ROOT / 'watch.log'
CHECK_INTERVAL = 5
RETRY_INTERVAL = 1800
CREATE_NO_WINDOW = 0x08000000


def run(args, timeout=120):
    result = subprocess.run(
        [str(arg) for arg in args], capture_output=True, encoding='utf-8',
        errors='replace', timeout=timeout, creationflags=CREATE_NO_WINDOW,
        env=dict(os.environ, PATH=str(NODE.parent) + os.pathsep + os.environ.get('PATH', '')),
    )
    if result.returncode:
        output = (result.stderr + '\n' + result.stdout).strip()
        raise RuntimeError(output[-1800:] or f'Exit code {result.returncode}: {args[0]}')
    return result.stdout


def report(message):
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.replace(ROOT / 'watch.previous.log')
    with LOG.open('a', encoding='utf-8') as log:
        log.write(f'{datetime.now().isoformat(timespec="seconds")} {message}\n')


def signature(path):
    with path.open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def write_file(path, contents):
    pending = path.with_name(path.name + '.tmp')
    pending.write_bytes(contents)
    pending.replace(path)


def save_state(state):
    write_file(STATE, (json.dumps(state, ensure_ascii=False, indent=2) + '\n').encode())


def product_version():
    path = str(EXE).replace("'", "''")
    raw = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
               f"(Get-Item -LiteralPath '{path}').VersionInfo.ProductVersion"], 15)
    match = re.search(r'\b\d+\.\d+\.\d+\b', raw)
    if not match:
        raise RuntimeError('Could not read installed Antigravity version')
    return match.group()


def app_running():
    processes = run(['tasklist.exe', '/FI', 'IMAGENAME eq Antigravity.exe', '/FO', 'CSV', '/NH'], 10)
    return any(line.casefold().startswith('"antigravity.exe",') for line in processes.splitlines())


def web_bytes(url, limit):
    request = Request(url, headers={'User-Agent': 'Local-Antigravity-Localization'})
    with urlopen(request, timeout=8) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise RuntimeError('Upstream file exceeds size limit')
    return result


def dictionary_for(version):
    if version == BASE_VERSION:
        return BASE_RELEASE, BASE_DICT.read_bytes(), True

    # Community releases only contribute translation data to the reviewed local patcher.
    try:
        tags_url = 'https://api.github.com/repos/yiheng8023/antigravity-chinese/tags?per_page=16'
        tags = json.loads(web_bytes(tags_url, 128_000))
        for item in tags[:12]:
            tag = item['name']
            commit = item['commit']['sha']
            if not re.fullmatch(r'v\d+\.\d+\.\d+', tag) or not re.fullmatch(r'[0-9a-f]{40}', commit):
                continue
            remote = f'https://raw.githubusercontent.com/yiheng8023/antigravity-chinese/{commit}'
            readme = web_bytes(remote + '/README.md', 250_000).decode('utf-8')
            if not re.search(r'维护目标为\s*\*\*Antigravity App\s+' + re.escape(version) + r'(?![\d.])', readme):
                continue
            data = web_bytes(remote + '/dict/zh-CN.json', 2_000_000)
            if not isinstance(json.loads(data), dict):
                raise ValueError('Invalid translation dictionary')
            return tag, data, True
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        report(f'{version} could not look up matching translations: {error}')
    return BASE_RELEASE, BASE_DICT.read_bytes(), False


def prepare(version, original, target, data):
    with tempfile.TemporaryDirectory(prefix='staging-', dir=ROOT) as directory:
        stage = Path(directory).resolve()
        assert stage.parent == ROOT and stage.name.startswith('staging-')
        copy = stage / 'app.asar'
        shutil.copy2(original, copy)
        unpacked = ARCHIVE.with_name('app.asar.unpacked')
        if unpacked.is_dir():
            shutil.copytree(unpacked, stage / unpacked.name)
        write_file(PATCHER / 'dict/zh-CN.json', data)
        run([NODE, PATCHER / 'cli.js', 'install', '--path', copy])
        original_asar = stage / 'app.asar.bak'
        # A patched input without an upstream base cannot be safely replaced.
        if not original_asar.is_file() or signature(original_asar) != signature(original):
            raise RuntimeError('Could not confirm the unmodified source archive')
        run([NODE, ROOT / 'verify.js', original_asar, copy])
        write_file(target, copy.read_bytes())


class Watcher:
    def __init__(self):
        self.files = None
        self.retry_after = 0
        self.result = None
        self.message = None

    def log_once(self, message):
        if self.message != message:
            report(message)
            self.message = message

    def check(self):
        if not EXE.is_file() or not ARCHIVE.is_file():
            self.log_once('Waiting for Antigravity installation files')
            return
        files = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in (EXE, ARCHIVE))
        if files != self.files:
            self.files = files
            self.retry_after = 0
            self.result = None
        elif self.result is not None:
            return
        if time.monotonic() < self.retry_after:
            return

        version = product_version()
        installed_hash = signature(ARCHIVE)
        state = json.loads(STATE.read_bytes()) if STATE.is_file() else {}
        known = state.get('version') == version and state.get('patched_hash') == installed_hash
        if known and state['matched_release']:
            self.result = True
            return
        if known:
            original = ROOT / 'backups' / f"{version}-{state['original_hash']}.asar"
            if not original.is_file() or signature(original) != state['original_hash']:
                raise RuntimeError('Missing original for the installed fallback patch')
        else:
            original = ARCHIVE

        original_hash = signature(original)
        release, dictionary, matched = dictionary_for(version)
        if known and not matched:
            self.retry_after = time.monotonic() + RETRY_INTERVAL
            return
        key = f'{version}-{original_hash[:20]}-{sha256(dictionary).hexdigest()[:12]}'
        candidate = ROOT / f'candidate-{key}.asar'
        if not candidate.is_file():
            prepare(version, original, candidate, dictionary)
            self.log_once(f'{version} validated {release} (upstream match: {matched})')
        if app_running():
            self.log_once(f'{version} {release} staged; waiting for the desktop to exit')
            # Reuse this release decision while waiting for the user to finish.
            self.pending = (version, installed_hash, original_hash, candidate, release, matched)
            return
        self.install(version, installed_hash, original_hash, candidate, release, matched)

    def install(self, version, installed_hash, original_hash, candidate, release, matched):
        if app_running() or signature(ARCHIVE) != installed_hash or product_version() != version:
            return
        backup_dir = ROOT / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f'{version}-{original_hash}.asar'
        if not backup.exists():
            if installed_hash != original_hash:
                raise RuntimeError('Cannot save the original before replacement')
            write_file(backup, ARCHIVE.read_bytes())
        if signature(backup) != original_hash:
            raise RuntimeError('Rollback copy did not verify')
        pending = ARCHIVE.with_name('app.asar.localization-pending')
        write_file(pending, candidate.read_bytes())
        if app_running() or signature(ARCHIVE) != installed_hash:
            return
        patched_hash = signature(pending)
        new_state = dict(version=version, release=release, matched_release=matched,
                         original_hash=original_hash, patched_hash=patched_hash)
        pending.replace(ARCHIVE)
        save_state(new_state)
        self.pending = None
        candidate.unlink(missing_ok=True)
        self.log_once(f'{version} installed {release}; backup: {backup.name}')
        self.files = None

    def tick(self):
        pending = getattr(self, 'pending', None)
        if pending:
            if app_running():
                return
            self.pending = None
            self.install(*pending)
            return
        self.check()


def validate_installation():
    for expected in (EXE, ARCHIVE, NODE, NODE.with_name('npx.cmd'), BASE_DICT,
                     PATCHER / 'node_modules/.bin/asar.cmd'):
        if not expected.is_file():
            raise FileNotFoundError(expected)
    if not isinstance(json.loads(BASE_DICT.read_bytes()), dict):
        raise ValueError('Invalid baseline dictionary')
    run([NODE, '--check', ROOT / 'verify.js'], 15)
    print('Watcher installation verified.')


def restore_original():
    if app_running():
        raise RuntimeError('Quit Antigravity from the system tray first.')
    if not STATE.is_file():
        raise RuntimeError('No patch from this watcher is available to restore.')
    installed = json.loads(STATE.read_bytes())
    version = installed['version']
    original_hash = installed['original_hash']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[0-9a-f]{64}', original_hash):
        raise RuntimeError('Invalid backup metadata.')
    if version != product_version() or signature(ARCHIVE) != installed['patched_hash']:
        raise RuntimeError('The current app does not match the watcher’s patch.')
    backup = ROOT / 'backups' / f'{version}-{original_hash}.asar'
    contents = backup.read_bytes()
    if sha256(contents).hexdigest() != original_hash:
        raise RuntimeError('The original archive did not verify.')
    pending = ARCHIVE.with_name('app.asar.localization-pending')
    write_file(pending, contents)
    if app_running() or signature(ARCHIVE) != installed['patched_hash']:
        raise RuntimeError('Antigravity was opened or updated during restore.')
    pending.replace(ARCHIVE)
    report(f'{version} restored from backup')
    print(f'Restored the original Antigravity {version} archive.')


def main():
    if '--validate' in sys.argv:
        validate_installation()
        return
    watcher = Watcher()
    with (ROOT / 'watch.lock').open('a+b') as guard:
        guard.seek(0)
        try:
            msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if '--restore' in sys.argv:
                raise RuntimeError('The watcher is still running.')
            return
        if '--restore' in sys.argv:
            restore_original()
            return
        report(f'Watcher started, pid={os.getpid()}')
        while True:
            try:
                watcher.tick()
            except Exception as error:
                report(f'{type(error).__name__}: {error}')
                watcher.retry_after = time.monotonic() + RETRY_INTERVAL
            if '--once' in sys.argv:
                return
            time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
