"""macOS ``sandbox-exec`` backend; absence or a failed canary is fail closed."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import os
import secrets
from pathlib import Path

from .base import (
    ProcessHandle,
    ProcessRequest,
    ReconciliationResult,
    SandboxAttestation,
    SandboxScope,
    ScopeSnapshot,
    TerminationResult,
    attest_snapshot,
    attestation_is_current,
    capture_scope_snapshot,
    minimal_environment,
    scope_failure_hash,
)
from .process_tree import reconcile_process, terminate_process_tree


def _quoted(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _strict_ancestor_literals(roots: tuple[Path, ...], protected_root: Path) -> tuple[Path, ...]:
    """Permit directory traversal only, never recursive reads of an ancestor."""
    ancestors: set[Path] = set()
    for root in roots:
        current = root.parent
        while True:
            if current == protected_root or current.is_relative_to(protected_root):
                raise ValueError("SANDBOX_RUNTIME_OVERLAPS_PROTECTED")
            ancestors.add(current)
            if current.parent == current:
                break
            current = current.parent
    return tuple(sorted(ancestors, key=str))


class MacOSSandboxRunner:
    """Generate a deny-by-default profile and bind each launch to its attestation."""

    def __init__(self) -> None:
        self._attestations: dict[str, tuple[ScopeSnapshot, SandboxAttestation]] = {}

    @staticmethod
    def _runtime_roots(scope: SandboxScope | ScopeSnapshot) -> tuple[Path, ...]:
        if isinstance(scope, ScopeSnapshot):
            return scope.readonly_runtime_roots
        defaults = (Path("/usr"), Path("/System"), Path("/opt/homebrew"), Path(sys.prefix))
        return tuple(root for root in (*defaults, *scope.readonly_runtime_roots) if root.is_dir())

    def _profile(self, scope: SandboxScope | ScopeSnapshot) -> str:
        read_roots = " ".join(f"(subpath {_quoted(root)})" for root in self._runtime_roots(scope))
        literal_ancestors = _strict_ancestor_literals(
            (*self._runtime_roots(scope), scope.shadow_root, scope.temporary_root), scope.protected_root
        )
        write_roots = " ".join(
            f"(subpath {_quoted(root)})" for root in (scope.shadow_root, scope.temporary_root)
        )
        return "\n".join(
            (
                "(version 1)",
                "(deny default)",
                "(allow process-exec)",
                "(allow process-fork)",
                # CPython's Darwin runtime reads kernel facts and contacts the
                # preferences daemon during interpreter bootstrap.  These are
                # explicit local IPC/read permissions, not network access.
                "(allow sysctl-read)",
                '(allow mach-lookup (global-name "com.apple.cfprefsd.daemon"))',
                # ``subpath`` does not grant traversal/read-data on its root.
                # CPython needs only the root directory itself to discover the
                # already-whitelisted runtime trees; this is not a recursive
                # filesystem permission.
                *(f"(allow file-read* (literal {_quoted(root)}))" for root in literal_ancestors),
                f"(allow file-read* {read_roots})",
                f"(allow file-read* (subpath {_quoted(scope.shadow_root)}))",
                f"(allow file-read* (subpath {_quoted(scope.temporary_root)}))",
                f"(allow file-write* {write_roots})",
            )
        )

    def _run(
        self, scope: SandboxScope | ScopeSnapshot, executable: str, argv: tuple[str, ...]
    ) -> subprocess.CompletedProcess[str]:
        sandbox_exec = shutil.which("sandbox-exec", path="/usr/bin:/bin")
        if sandbox_exec != "/usr/bin/sandbox-exec":
            raise RuntimeError("SANDBOX_EXEC_UNAVAILABLE")
        return subprocess.run(
            [sandbox_exec, "-p", self._profile(scope), executable, *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            start_new_session=True,
            cwd=scope.shadow_root,
            env=minimal_environment(),
        )

    def self_test(self, scope: SandboxScope) -> SandboxAttestation:
        try:
            effective_scope = SandboxScope(
                scope.shadow_root,
                scope.temporary_root,
                scope.protected_root,
                readonly_runtime_roots=self._runtime_roots(scope),
            )
            snapshot = capture_scope_snapshot(effective_scope)
        except (OSError, ValueError):
            return SandboxAttestation(scope_failure_hash(scope), False, "SANDBOX_SCOPE_INVALID", "macos")
        scope_hash = snapshot.scope_hash
        if sys.platform != "darwin":
            return SandboxAttestation(scope_hash, False, "UNSUPPORTED_SANDBOX_PLATFORM", "macos")
        if shutil.which("sandbox-exec", path="/usr/bin:/bin") != "/usr/bin/sandbox-exec":
            return SandboxAttestation(scope_hash, False, "SANDBOX_EXEC_UNAVAILABLE", "macos")
        challenge = secrets.token_hex(16)
        canary = snapshot.protected_root / f".yagcode-self-test-canary-{challenge}"
        stolen = snapshot.protected_root / f".yagcode-self-test-stolen-{challenge}"
        receipt_path = snapshot.shadow_root / f".yagcode-attestation-{challenge}"
        try:
            descriptor = os.open(canary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"must-remain-unreadable")
        except OSError:
            return SandboxAttestation(scope_hash, False, "SANDBOX_CANARY_UNAVAILABLE", "macos", snapshot)
        listener: socket.socket | None = None
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.setblocking(False)
            host, port = listener.getsockname()
        except OSError:
            if listener is not None:
                listener.close()
            canary.unlink(missing_ok=True)
            stolen.unlink(missing_ok=True)
            receipt_path.unlink(missing_ok=True)
            return SandboxAttestation(scope_hash, False, "SANDBOX_CANARY_UNAVAILABLE", "macos")
        code = (
            "from pathlib import Path; import socket, subprocess, sys\n"
            f"shadow=Path({str(snapshot.shadow_root)!r}); protected=Path({str(snapshot.protected_root)!r}); canary=Path({str(canary)!r}); stolen=Path({str(stolen)!r})\n"
            "receipt=Path(sys.argv[1]); challenge=sys.argv[2]\n"
            "checks=[]\n"
            "try: canary.read_bytes(); checks.append(False)\n"
            "except OSError: checks.append(True)\n"
            "try: stolen.write_bytes(b'x'); checks.append(False)\n"
            "except OSError: checks.append(True)\n"
            "try: socket.create_connection((sys.argv[3], int(sys.argv[4])), timeout=1).close(); checks.append(False)\n"
            "except OSError: checks.append(True)\n"
            "child='from pathlib import Path; import sys; p=Path(sys.argv[1]);\\ntry: p.read_bytes(); raise SystemExit(9)\\nexcept OSError: raise SystemExit(0)'\n"
            "checks.append(subprocess.run([sys.executable, '-c', child, str(canary)]).returncode == 0)\n"
            "receipt.write_text(challenge + ':' + ','.join(map(str, checks)))\n"
            "raise SystemExit(0 if all(checks) else 7)\n"
        )
        try:
            receipt_path.unlink(missing_ok=True)
            result = self._run(snapshot, sys.executable, ("-c", code, str(receipt_path), challenge, host, str(port)))
            try:
                connection, _ = listener.accept()
            except BlockingIOError:
                network_connected = False
            else:
                connection.close()
                network_connected = True
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return SandboxAttestation(scope_hash, False, "SANDBOX_CANARY_UNAVAILABLE", "macos")
        finally:
            listener.close()
            canary.unlink(missing_ok=True)
            stolen.unlink(missing_ok=True)
            try:
                receipt = receipt_path.read_text(encoding="utf-8")
            except OSError:
                receipt = ""
            receipt_path.unlink(missing_ok=True)
        verified = not network_connected and result.returncode == 0 and receipt == f"{challenge}:True,True,True,True"
        attestation = (
            attest_snapshot(snapshot, backend="macos")
            if verified
            else SandboxAttestation(scope_hash, False, "SANDBOX_CANARY_FAILED", "macos", snapshot)
        )
        if verified:
            self._attestations[scope_hash] = (snapshot, attestation)
        return attestation

    def start(self, request: ProcessRequest, attestation: SandboxAttestation) -> ProcessHandle:
        recorded = self._attestations.get(attestation.scope_hash)
        if not attestation_is_current(attestation) or recorded is None or recorded[1] != attestation:
            return ProcessHandle(False, "SANDBOX_UNAVAILABLE")
        snapshot = attestation.snapshot
        if snapshot is None:
            return ProcessHandle(False, "SANDBOX_UNAVAILABLE")
        if not Path(request.executable).is_file():
            return ProcessHandle(False, "SANDBOX_EXECUTABLE_INVALID")
        sandbox_exec = shutil.which("sandbox-exec", path="/usr/bin:/bin")
        if sandbox_exec != "/usr/bin/sandbox-exec":
            return ProcessHandle(False, "SANDBOX_UNAVAILABLE")
        try:
            process = subprocess.Popen(
                [sandbox_exec, "-p", self._profile(recorded[0]), request.executable, *request.argv],
                shell=False,
                start_new_session=True,
                cwd=snapshot.shadow_root,
                env=minimal_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return ProcessHandle(False, "SANDBOX_START_FAILED")
        return ProcessHandle(True, "PROCESS_STARTED", process.pid, process)

    def terminate_tree(self, handle: ProcessHandle) -> TerminationResult:
        return terminate_process_tree(handle)

    def reconcile(self, handle: ProcessHandle) -> ReconciliationResult:
        return reconcile_process(handle)


__all__ = ["MacOSSandboxRunner"]
