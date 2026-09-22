"""Confined replay of worker-authored commands; no unsandboxed fallback.

Only a bounded, link-free copy of the run and trusted system runtimes are visible.
The Director's environment, home, checkout, credential files and host processes
are not replay inputs. Outputs remain in the temporary replay copy.
"""
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile


class ReplayUnavailable(RuntimeError):
    """Replay could not be safely started; never evidence of a passing check."""


SYSTEM_RUNTIME = ('/usr/bin', '/usr/lib', '/usr/lib64', '/usr/share',
                  '/usr/local/bin', '/usr/local/lib', '/bin', '/sbin', '/lib', '/lib64')
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 10000


def environment(home, tmp):
    """No inherited variables, shell startup hooks, role env_keys or user PATH."""
    bins = [str(Path(sys.executable).resolve().parent), '/usr/local/bin', '/usr/bin', '/bin']
    if sys.platform == 'darwin':
        bins.append('/opt/homebrew/bin')
    return {'PATH': ':'.join(dict.fromkeys(bins)), 'HOME': str(home),
            'TMPDIR': str(tmp), 'TMP': str(tmp), 'TEMP': str(tmp),
            'LANG': 'C', 'LC_ALL': 'C', 'PYTHONNOUSERSITE': '1',
            'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null'}


def copy_run(source, destination):
    """Descriptor-relative traversal rejects symlink/hardlink and special files.

    It does not follow a worker-created link to a credential while preparing the
    sandbox. Changed files are rejected rather than silently replayed as a mixture.
    """
    total, count = 0, 0
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    if not nofollow:
        raise ReplayUnavailable('safe snapshot traversal is unsupported')
    def walk(fd, dst):
        nonlocal total, count
        for name in sorted(os.listdir(fd)):
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            count += 1
            if count > MAX_FILES:
                raise ReplayUnavailable('run exceeds replay snapshot entry limit')
            if stat.S_ISDIR(before.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=fd)
                try:
                    if os.fstat(child).st_ino != before.st_ino:
                        raise ReplayUnavailable('run changed during snapshot')
                    (dst / name).mkdir(mode=0o700)
                    walk(child, dst / name)
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
                child = os.open(name, os.O_RDONLY | nofollow | os.O_NONBLOCK, dir_fd=fd)
                try:
                    opened = os.fstat(child)
                    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_nlink)
                    if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
                        raise ReplayUnavailable('run changed during snapshot')
                    total += opened.st_size
                    if total > MAX_BYTES:
                        raise ReplayUnavailable('run exceeds replay snapshot byte limit')
                    remaining = opened.st_size
                    with (dst / name).open('xb') as output:
                        while remaining:
                            block = os.read(child, min(remaining, 1024 * 1024))
                            if not block:
                                raise ReplayUnavailable('run changed during snapshot')
                            output.write(block)
                            remaining -= len(block)
                        os.fchmod(output.fileno(), opened.st_mode & 0o777)
                    if identity(os.fstat(child)) != identity(opened):
                        raise ReplayUnavailable('run changed during snapshot')
                finally:
                    os.close(child)
            else:
                raise ReplayUnavailable('replay input contains a link or special file')
    destination.mkdir(mode=0o700)
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    try:
        walk(fd, destination)
    finally:
        os.close(fd)


def runtime_paths():
    paths = list(SYSTEM_RUNTIME)
    if sys.platform == 'darwin':
        paths += ['/System/Library', '/Library/Apple', '/opt/homebrew/bin',
                  '/opt/homebrew/lib', '/opt/homebrew/Cellar', '/opt/homebrew/opt']
    # An explicitly running interpreter is part of the trusted toolchain. Do not
    # broaden global prefixes into /usr (which would expose /usr/local/etc).
    for prefix in {sys.prefix, sys.base_prefix}:
        path = Path(prefix).resolve()
        if str(path) not in ('/usr', '/usr/local'):
            if path in (Path('/'), Path.home().resolve()):
                raise ReplayUnavailable('unsafe interpreter runtime prefix')
            paths.append(str(path))
    return list(dict.fromkeys(str(Path(p).resolve()) for p in paths if Path(p).exists()))


def command_line(stage, original, home, tmp, command):
    if sys.platform == 'linux':
        binary = shutil.which('bwrap', path='/usr/bin:/bin')
        if not binary:
            raise ReplayUnavailable('bubblewrap is required for replay on Linux')
        args = [binary, '--unshare-all', '--die-with-parent', '--new-session',
                '--cap-drop', 'ALL', '--proc', '/proc', '--dev', '/dev',
                '--tmpfs', '/tmp', '--dir', '/lab-home']
        # Preserve runtime symlinks such as /bin -> /usr/bin without mounting
        # either the host's /etc or the host's home/workspace.
        for path in runtime_paths():
            args += ['--ro-bind', path, path]
        for link in SYSTEM_RUNTIME:
            if Path(link).is_symlink():
                args += ['--symlink', os.readlink(link), link]
        if Path('/etc/ld.so.cache').is_file():
            args += ['--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache']
        args += ['--bind', str(stage), str(original), '--chdir', str(original),
                 '--', '/bin/sh', '-c', 'set -e\n' + command]
        return args, environment('/lab-home', '/tmp'), 'bubblewrap-v1'
    if sys.platform == 'darwin':
        binary = '/usr/bin/sandbox-exec'
        if not Path(binary).is_file():
            raise ReplayUnavailable('sandbox-exec is required for replay on macOS')
        # Literal JSON quoting also escapes paths safely in a Seatbelt profile.
        import json
        sub = lambda p: '(subpath ' + json.dumps(str(p)) + ')'
        profile = ['(version 1)', '(deny default)', '(allow process-fork)',
                   '(allow process-exec)', '(allow signal (target self))',
                   '(allow sysctl-read (sysctl-name "hw.machine") (sysctl-name "hw.ncpu")'
                   ' (sysctl-name "hw.memsize") (sysctl-name "hw.pagesize")'
                   ' (sysctl-name "hw.optional.arm64") (sysctl-name "kern.ostype")'
                   ' (sysctl-name "kern.osrelease") (sysctl-name "kern.osversion")'
                   ' (sysctl-name "kern.argmax"))', '(allow file-read-metadata)',
                   '(allow mach-lookup (global-name "com.apple.system.logger"))',
                   '(allow file-read* ' + ' '.join(sub(p) for p in runtime_paths()) + ')',
                   '(allow file-map-executable ' + ' '.join(sub(p) for p in runtime_paths() + [stage]) + ')',
                   '(allow file-read* file-write* ' + ' '.join(sub(p) for p in (stage,home,tmp)) + ')',
                   '(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
                   '(allow file-write* (literal "/dev/null"))']
        return [binary, '-p', '\n'.join(profile), '/bin/sh', '-c', 'set -e\n' + command], environment(home,tmp), 'seatbelt-v1'
    raise ReplayUnavailable('no supported replay confinement backend on this platform')


def execute(rundir, command, timeout):
    """Execute with actual OS confinement or fail closed. Never inherit secrets."""
    original = Path(rundir).absolute()
    with tempfile.TemporaryDirectory(prefix='lab-replay-') as directory:
        root = Path(directory).resolve()
        stage, home, tmp = root / 'run', root / 'home', root / 'tmp'
        home.mkdir(); tmp.mkdir()
        try:
            copy_run(original, stage)
            args, env, backend = command_line(stage, original, home, tmp, command)
        except (OSError, ValueError) as exc:
            raise ReplayUnavailable('replay snapshot or confinement setup failed') from exc
        with subprocess.Popen(args, cwd=stage, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, close_fds=True, start_new_session=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr), backend
