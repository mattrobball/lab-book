# Confined replay in alpha.2

**Linux replay is verified by the native repair suite. macOS replay currently fails closed at shell startup and is not a working, verified path.** This change confines worker-authored validation commands, not every coding-agent launcher or the interactive Director.

## Inputs and results

The gate makes a bounded private copy of the returned run: at most 10,000 entries and 256 MiB. Descriptor-relative traversal refuses links, special files and detected concurrent changes without following a link into credential files. Only regular files/directories, a fresh private home/tmp, and selected read-only system/interpreter runtimes become replay inputs. Verifiers must bring self-contained inputs. Outputs stay in the disposable copy, not the accepted source.

The environment is constructed from scratch, without inherited model/database keys, user PATH, shell startup hooks, user Python paths, Git credential configuration or role env_keys. On the verified Linux path, Bubblewrap isolates filesystem, processes and network, drops capabilities and confines children. Native tests use dummy secrets and positive packet-file controls, with denied host credentials, process-environment and network probes. Timeout handling terminates the replay process group and never records a replay pass.

Missing, host-denied or unsupported confinement never falls back to an unrestricted shell. A worker PASS that does not replay is recorded UNDECIDED with the failure evidence retained. This is not a mathematical refutation. Correct the execution environment and dispatch a fresh check rather than rewriting filed evidence.

## Linux setup

Install Bubblewrap with permission to create user/mount/PID/network namespaces. Some Ubuntu hosts require an administrator-approved AppArmor profile for `/usr/bin/bwrap`. The kit's `integration/prepare-linux-replay.sh` is guarded for disposable GitHub Linux runners and supplies a scoped executable profile; it does not disable AppArmor or the system-wide namespace restriction. Production setup is an administrator action. Runtime replay does not change host policy.

## Outstanding macOS compatibility

The native Seatbelt implementation uses `/usr/bin/sandbox-exec` with a deny-default policy. The shell exits with signal 6 before the positive replay/timeout controls complete. The macOS job reports two failures among seven replay tests and a separate upgraded-canary failure; it remains visible in CI. The intended host-process-information denial probe cannot yet complete inside a successfully started replay. Do not treat these partial controls as a verified macOS sandbox. No unrestricted fallback was applied.

## Trust boundary

The OS, sandbox implementation and selected system/interpreter runtime directories are trusted. Do not place credentials in those runtime directories or in returned packets. An interpreter environment containing secrets is not a safe runtime to expose. Network-dependent, externally located or oversized verifiers need self-contained inputs or a separately designed execution environment, not a whole-host mount.

Worker launch still has its existing environment allowlist. It is not filesystem isolation from a hostile coding agent running as the Director's OS user. Keep that boundary distinct from the repaired replay path. No real credentials are used in the tests and no paid calls are enabled by this change.
