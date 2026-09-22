#!/usr/bin/env bash
# Fixture provisioning ONLY. Runtime replay never edits host security settings.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux ]] || {
  echo 'This provisioning script is only for disposable GitHub Linux runners.' >&2; exit 2;
}
sudo apt-get update -qq
sudo apt-get install -y bubblewrap
# Ubuntu's default unprivileged-userns restrictions need a named executable
# profile. Permit namespaces for /usr/bin/bwrap; do not disable AppArmor or the
# system-wide restriction. Bubblewrap still builds its private mount/PID/network
# namespaces and drops capabilities for every replayed command.
if [[ -r /sys/module/apparmor/parameters/enabled ]] && grep -q '^Y' /sys/module/apparmor/parameters/enabled; then
  sudo tee /etc/apparmor.d/bwrap >/dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
PROFILE
  sudo apparmor_parser -r /etc/apparmor.d/bwrap
fi
bwrap --version
bwrap --unshare-all --die-with-parent --new-session --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --proc /proc --dev /dev /bin/true
