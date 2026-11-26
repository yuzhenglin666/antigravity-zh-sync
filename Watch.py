from contextlib import contextmanager
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
PENDING_STATUS = ROOT / 'pending.json'
CHECK_REQUEST = ROOT / 'check-now.request'
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


@contextmanager
def status_lock():
    # Windows readers can block rename and deletion, even for an atomic write.
    with (ROOT / 'status.lock').open('a+b') as guard:
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_LOCK, 1)
        yield


def report(message):
    with status_lock():
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


def read_state(path):
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}


def save_state(path, state):
    write_file(path, (json.dumps(state, ensure_ascii=False, indent=2) + '\n').encode())


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


def watched_files():
    files = []
    for path in (EXE, ARCHIVE):
        stat = path.stat()
        files.append((stat.st_mtime_ns, stat.st_size))
    return tuple(files)


def notify(event):
    if not settings.get('notifications', True):
        return
    try:
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(ROOT / 'Notify.ps1'), '-Event', event],
            creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        report(f'Windows notification unavailable: {error}')


def localization_status(*, task_active=True):
    if not EXE.is_file() or not ARCHIVE.is_file():
        return {'status': 'client_files_missing'}
    version = product_version()
    current = signature(ARCHIVE)
    installed = read_state(STATE)
    pending = read_state(PENDING_STATUS)
    result = dict(version=version, client_running=app_running(), status='awaiting_check',
                  notifications=settings.get('notifications', True))
    if installed.get('version') == version and installed.get('patched_hash') == current:
        result['installed_release'] = installed['release']
        result['status'] = 'installed' if installed['matched_release'] else 'fallback_installed'
    candidate = pending.get('candidate')
    if (pending.get('version') == version and pending.get('source_hash') == current
            and candidate and (ROOT / Path(candidate).name).is_file()):
        result['pending_release'] = pending['release']
        result['pending_matched_release'] = pending['matched_release']
        if task_active:
            result['status'] = 'waiting_for_exit' if result['client_running'] else 'ready_to_apply'
        else:
            result['status'] = 'staged_inactive'
    try:
        events = LOG.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        events = []
    result['last_event'] = next((line for line in reversed(events)
                                 if re.match(r'\d{4}-\d{2}-\d{2}T', line)), None)
    return result


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
        self.pending = None

    def log_once(self, message):
        if self.message != message:
            report(message)
            self.message = message

    def check(self):
        if not EXE.is_file() or not ARCHIVE.is_file():
            self.log_once('Waiting for Antigravity installation files')
            return
        files = watched_files()
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
        state = read_state(STATE)
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
        if not matched and self.pending:
            pending_version, pending_source, _, pending_candidate, _, pending_matched = self.pending
            if (pending_matched and pending_version == version and pending_source == installed_hash
                    and pending_candidate.is_file()):
                return
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
            pending_status = dict(version=version, source_hash=installed_hash,
                                  release=release, matched_release=matched, candidate=candidate.name)
            if read_state(PENDING_STATUS) != pending_status:
                with status_lock():
                    save_state(PENDING_STATUS, pending_status)
                notify('ready')
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
        patched_hash = signature(pending)
        new_state = dict(version=version, release=release, matched_release=matched,
                         original_hash=original_hash, patched_hash=patched_hash)
        with status_lock():
            if product_version() != version or signature(ARCHIVE) != installed_hash or app_running():
                return
            pending.replace(ARCHIVE)
            save_state(STATE, new_state)
            PENDING_STATUS.unlink(missing_ok=True)
        self.pending = None
        candidate.unlink(missing_ok=True)
        self.log_once(f'{version} installed {release}; backup: {backup.name}')
        notify('installed')
        self.files = None

    def tick(self):
        check_requested = False
        try:
            CHECK_REQUEST.unlink()
        except (FileNotFoundError, PermissionError):
            pass
        else:
            self.retry_after = 0
            self.result = None
            check_requested = True
        if self.pending:
            try:
                same_source = watched_files() == self.files
            except FileNotFoundError:
                same_source = False
            if not same_source:
                with status_lock():
                    PENDING_STATUS.unlink(missing_ok=True)
                self.pending = None
            elif not check_requested:
                if not app_running():
                    pending = self.pending
                    self.pending = None
                    self.install(*pending)
                return
        self.check()


def validate_installation():
    for expected in (EXE, ARCHIVE, NODE, NODE.with_name('npx.cmd'), BASE_DICT,
                     ROOT / 'Notify.ps1', PATCHER / 'node_modules/.bin/asar.cmd'):
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
    with status_lock():
        if product_version() != version or signature(ARCHIVE) != installed['patched_hash'] or app_running():
            raise RuntimeError('Antigravity was opened or updated during restore.')
        pending.replace(ARCHIVE)
    report(f'{version} restored from backup')
    print(f'Restored the original Antigravity {version} archive.')


def main():
    if '--validate' in sys.argv:
        validate_installation()
        return
    if '--status' in sys.argv:
        # ASCII JSON works in both Windows PowerShell and PowerShell 7.
        with status_lock():
            status = localization_status(task_active='--task-inactive' not in sys.argv)
        print(json.dumps(status, indent=2))
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
