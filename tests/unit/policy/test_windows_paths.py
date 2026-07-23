"""Windows relative-handle traversal contract, executable with a strict fake."""

from __future__ import annotations

import importlib

import pytest


def test_windows_no_reparse_traversal_checks_each_component_and_closes_on_alias() -> None:
    try:
        production = importlib.import_module("yagcode.policy.windows_paths")
    except ModuleNotFoundError as error:
        pytest.fail(f"WINDOWS_PATH_CONTRACT_MISSING:{error.name}")

    class FakeOps:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def open_root(self, root: str) -> str:
            self.calls.append("root")
            return "root"

        def open_relative_no_reparse(self, parent: str, component: str, directory: bool) -> str:
            self.calls.append(f"open:{parent}:{component}:{directory}")
            if component == "alias":
                raise production.WindowsPathError("WINDOWS_REPARSE_POINT_REJECTED")
            return component

        def identity(self, handle: str) -> object:
            self.calls.append(f"id:{handle}")
            return production.WindowsFileIdentity("volume", handle, 0)

        def content_hash(self, handle: str) -> str:
            self.calls.append(f"hash:{handle}")
            return "hash"

        def write_relative_no_reparse(
            self, parent: str, basename: str, expected: object, expected_hash: str | None, content: bytes
        ) -> None:
            raise AssertionError("not used")

        def close(self, handle: str) -> None:
            self.calls.append(f"close:{handle}")

    ops = FakeOps()
    resolver = production.WindowsNoReparseResolver(ops)
    target = resolver.resolve_for_write("root", ("safe", "file"))
    assert target.basename == "file"
    assert ops.calls == ["root", "id:root", "open:root:safe:True", "id:safe", "open:safe:file:False", "id:file", "hash:file", "close:file", "close:safe", "close:root"]

    ops = FakeOps()
    with pytest.raises(production.WindowsPathError, match="WINDOWS_REPARSE_POINT_REJECTED"):
        production.WindowsNoReparseResolver(ops).resolve_for_write("root", ("alias", "file"))
    assert ops.calls[-1] == "close:root"


def test_windows_dispatcher_reopens_handles_and_rejects_replaced_parent() -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")

    class FakeOps:
        def __init__(self) -> None:
            self.identities = {
                "root": production.WindowsFileIdentity("volume", "root", 0),
                "safe": production.WindowsFileIdentity("volume", "safe-before", 0),
                "target": production.WindowsFileIdentity("volume", "target", 0),
            }
            self.writes: list[tuple[str, bytes]] = []

        def open_root(self, root: str) -> str:
            return "root"

        def open_relative_no_reparse(self, parent: str, component: str, directory: bool) -> str:
            return component

        def identity(self, handle: str) -> object:
            return self.identities[handle]

        def content_hash(self, handle: str) -> str:
            return "hash"

        def write_relative_no_reparse(
            self, parent: str, basename: str, expected: object, expected_hash: str | None, content: bytes
        ) -> None:
            self.writes.append((basename, content))

        def close(self, handle: str) -> None:
            pass

    ops = FakeOps()
    target = production.WindowsNoReparseResolver(ops).resolve_for_write("root", ("safe", "target"))
    ops.identities["safe"] = production.WindowsFileIdentity("volume", "safe-after", 0)

    assert production.WindowsSecurePathDispatcher(ops).write(target, b"blocked") == "STALE_TARGET"
    assert ops.writes == []


def test_windows_dispatcher_rejects_same_identity_content_mutation_before_write() -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")

    class FakeOps:
        def __init__(self) -> None:
            self.identity_value = production.WindowsFileIdentity("volume", "file", 0)
            self.content = "before"
            self.writes = 0

        def open_root(self, root: str) -> str:
            return "root"

        def open_relative_no_reparse(self, parent: str, component: str, directory: bool) -> str:
            return component

        def identity(self, handle: str) -> object:
            return self.identity_value

        def content_hash(self, handle: str) -> str:
            return self.content

        def write_relative_no_reparse(
            self, parent: str, basename: str, expected: object, expected_hash: str | None, content: bytes
        ) -> None:
            if expected_hash != self.content:
                raise production.WindowsPathError("WINDOWS_PATH_CONTENT_STALE")
            self.writes += 1

        def close(self, handle: str) -> None:
            pass

    ops = FakeOps()
    target = production.WindowsNoReparseResolver(ops).resolve_for_write("root", ("target",))
    ops.content = "changed-with-same-file-id"

    assert production.WindowsSecurePathDispatcher(ops).write(target, b"new") == "STALE_TARGET"
    assert ops.writes == 0


def test_nt_relative_open_requests_read_data_only_for_existing_file_targets() -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")
    ops = object.__new__(production.NtCreateFileRelativeOps)
    calls: list[tuple[str, int | None, bool]] = []

    def fake_open(name: str, parent: int | None, directory: bool, *, desired_access: int | None = None, disposition: int | None = None) -> int:
        calls.append((name, desired_access, directory))
        return 1

    ops._open = fake_open
    ops.open_relative_no_reparse(9, "file", False)
    ops.open_relative_no_reparse(9, "directory", True)

    assert calls == [
        ("file", ops._SYNCHRONIZE | ops._FILE_READ_ATTRIBUTES | ops._FILE_READ_DATA, False),
        ("directory", ops._SYNCHRONIZE | ops._FILE_READ_ATTRIBUTES, True),
    ]


def test_nt_file_standard_info_abi_and_object_attributes_pointer_are_win64_safe() -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")
    unicode, _buffer = production.NtCreateFileRelativeOps._unicode("x")
    attributes = production.NtCreateFileRelativeOps._attributes(unicode, 123)
    root_attributes = production.NtCreateFileRelativeOps._attributes(unicode, None, dont_reparse=False)

    assert production.NtCreateFileRelativeOps._FILE_STANDARD_INFO == 1
    assert attributes.RootDirectory == 123
    assert attributes.ObjectName
    assert attributes.Attributes & production.NtCreateFileRelativeOps._OBJ_DONT_REPARSE
    assert not root_attributes.Attributes & production.NtCreateFileRelativeOps._OBJ_DONT_REPARSE


def test_nt_native_path_uses_nt_namespace_not_win32_extended_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")
    monkeypatch.setattr(production.os.path, "abspath", lambda value: value)
    monkeypatch.setattr(production.os.path, "isabs", lambda value: value.startswith(("C:\\", "\\\\")))

    assert production.NtCreateFileRelativeOps._native_path("C:\\root") == "\\??\\C:\\root"
    assert production.NtCreateFileRelativeOps._native_path("\\\\server\\share") == "\\??\\UNC\\server\\share"


def test_windows_resolver_rejects_hardlink_alias_before_any_write() -> None:
    production = importlib.import_module("yagcode.policy.windows_paths")

    class FakeOps:
        def open_root(self, root: str) -> str:
            return "root"

        def open_relative_no_reparse(self, parent: str, component: str, directory: bool) -> str:
            return component

        def identity(self, handle: str) -> object:
            links = 2 if handle == "alias" else 1
            return production.WindowsFileIdentity("volume", handle, 0, links)

        def content_hash(self, handle: str) -> str:
            return "external-content"

        def write_relative_no_reparse(
            self, parent: str, basename: str, expected: object, expected_hash: str | None, content: bytes
        ) -> None:
            raise AssertionError("hardlink alias must not be written")

        def close(self, handle: str) -> None:
            pass

    with pytest.raises(production.WindowsPathError, match="WINDOWS_HARDLINK_REJECTED"):
        production.WindowsNoReparseResolver(FakeOps()).resolve_for_write("root", ("alias",))
