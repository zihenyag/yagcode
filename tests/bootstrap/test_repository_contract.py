"""Repository metadata contract for (stdlib-only collection)."""

import copy
import json
import pathlib
import tomllib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUIRED_PATHS = {
    "package-lock.json",
    "src/yagcode/py.typed",
    "tests/bootstrap/test_node_runners.mjs",
    "scripts/run-python.mjs",
    "scripts/test-all.mjs",
}


def repository_contract_errors(package: dict, pyproject: dict, paths: set[str], npmrc: str, lock: object) -> list[str]:
    """Pure in-memory oracle, independent from repository I/O."""
    errors: list[str] = []
    expected_scripts = {
        "test:all": "node scripts/test-all.mjs",
        "test:runners": "node --test tests/bootstrap/test_node_runners.mjs",
    }
    for key, value in expected_scripts.items():
        if package.get("scripts", {}).get(key) != value:
            errors.append(f"scripts.{key}")
    if package.get("engines", {}).get("node") != ">=22.14 <23":
        errors.append("engines.node")
    if pyproject.get("project", {}).get("requires-python") != ">=3.12,<3.13":
        errors.append("project.requires-python")
    if pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts") != "-ra --strict-markers":
        errors.append("pytest.addopts")
    if pyproject.get("tool", {}).get("mypy", {}).get("files") != ["src/yagcode"]:
        errors.append("mypy.files")
    if npmrc != "engine-strict=true\n":
        errors.append(".npmrc")
    for path in REQUIRED_PATHS:
        if path not in paths:
            errors.append(path)
    if not isinstance(lock, dict):
        return ["package-lock.invalid-top-level"]
    if lock.get("lockfileVersion") != 3:
        errors.append("package-lock.lockfileVersion")
    packages = lock.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    if not isinstance(root_package, dict):
        errors.append("package-lock.packages-root")
    else:
        for key in ("name", "version", "workspaces"):
            if root_package.get(key) != package.get(key):
                errors.append(f"package-lock.packages-root.{key}")
        if root_package.get("engines", {}).get("node") != package.get("engines", {}).get("node"):
            errors.append("package-lock.packages-root.engines.node")
    return errors


def constant_success_contract_errors(package: dict, pyproject: dict, paths: set[str], npmrc: str, lock: object) -> list[str]:
    """Deliberately weak mutation used to prove the oracle rejects broken metadata."""
    del package, pyproject, paths, npmrc, lock
    return []


class RepositoryContractTest(unittest.TestCase):
    def test_owned_repository_contract_oracle(self) -> None:
        package = {
            "name": "yagcode",
            "version": "0.1.0",
            "workspaces": ["apps/*", "packages/*"],
            "engines": {"node": ">=22.14 <23"},
            "scripts": {
                "test:all": "node scripts/test-all.mjs",
                "test:runners": "node --test tests/bootstrap/test_node_runners.mjs",
            },
        }
        pyproject = {
            "project": {"requires-python": ">=3.12,<3.13"},
            "tool": {"pytest": {"ini_options": {"addopts": "-ra --strict-markers"}}, "mypy": {"files": ["src/yagcode"]}},
        }
        paths = {
            "package-lock.json",
            "src/yagcode/py.typed",
            "tests/bootstrap/test_node_runners.mjs",
            "scripts/run-python.mjs",
            "scripts/test-all.mjs",
        }
        lock = {
            "lockfileVersion": 3,
            "packages": {"": {"name": "yagcode", "version": "0.1.0", "workspaces": ["apps/*", "packages/*"], "engines": {"node": ">=22.14 <23"}}},
        }
        self.assertEqual(repository_contract_errors(package, pyproject, paths, "engine-strict=true\n", lock), [])
        self.assertEqual(
            repository_contract_errors(package, pyproject, paths, "engine-strict=true\n", []),
            ["package-lock.invalid-top-level"],
        )
        self.assertIn(
            "package-lock.packages-root",
            repository_contract_errors(
                package, pyproject, paths, "engine-strict=true\n", {"lockfileVersion": 3, "packages": []}
            ),
        )

        mutations = (
            ("scripts.test:all", lambda p, q, r, n, lock_data: p["scripts"].pop("test:all")),
            ("scripts.test:runners", lambda p, q, r, n, lock_data: p["scripts"].pop("test:runners")),
            ("engines.node", lambda p, q, r, n, lock_data: p["engines"].pop("node")),
            ("project.requires-python", lambda p, q, r, n, lock_data: q["project"].pop("requires-python")),
            ("pytest.addopts", lambda p, q, r, n, lock_data: q["tool"]["pytest"]["ini_options"].pop("addopts")),
            ("mypy.files", lambda p, q, r, n, lock_data: q["tool"]["mypy"].pop("files")),
            (".npmrc", lambda p, q, r, n, lock_data: n.update(value="")),
            ("package-lock.json", lambda p, q, r, n, lock_data: r.remove("package-lock.json")),
            ("package-lock.lockfileVersion", lambda p, q, r, n, lock_data: lock_data.update(lockfileVersion=2)),
            ("package-lock.packages-root", lambda p, q, r, n, lock_data: lock_data.update(packages=[])),
            ("package-lock.packages-root.name", lambda p, q, r, n, lock_data: lock_data["packages"][""].pop("name")),
            ("package-lock.packages-root.version", lambda p, q, r, n, lock_data: lock_data["packages"][""].pop("version")),
            ("package-lock.packages-root.workspaces", lambda p, q, r, n, lock_data: lock_data["packages"][""].pop("workspaces")),
            ("package-lock.packages-root.engines.node", lambda p, q, r, n, lock_data: lock_data["packages"][""]["engines"].pop("node")),
            ("src/yagcode/py.typed", lambda p, q, r, n, lock_data: r.remove("src/yagcode/py.typed")),
            ("tests/bootstrap/test_node_runners.mjs", lambda p, q, r, n, lock_data: r.remove("tests/bootstrap/test_node_runners.mjs")),
            ("scripts/run-python.mjs", lambda p, q, r, n, lock_data: r.remove("scripts/run-python.mjs")),
            ("scripts/test-all.mjs", lambda p, q, r, n, lock_data: r.remove("scripts/test-all.mjs")),
        )
        for expected, mutate in mutations:
            broken_package, broken_pyproject, broken_paths, broken_lock = copy.deepcopy(package), copy.deepcopy(pyproject), set(paths), copy.deepcopy(lock)
            npmrc = {"value": "engine-strict=true\n"}
            mutate(broken_package, broken_pyproject, broken_paths, npmrc, broken_lock)
            self.assertIn(expected, repository_contract_errors(broken_package, broken_pyproject, broken_paths, npmrc["value"], broken_lock))

        broken_package, broken_pyproject, broken_paths = copy.deepcopy(package), copy.deepcopy(pyproject), set(paths)
        broken_package["scripts"].pop("test:all")
        self.assertEqual(
            constant_success_contract_errors(broken_package, broken_pyproject, broken_paths, "engine-strict=true\n", lock),
            [],
        )
        self.assertIn(
            "scripts.test:all",
            repository_contract_errors(broken_package, broken_pyproject, broken_paths, "engine-strict=true\n", lock),
        )

    def test_repository_contract(self) -> None:
        package_file = ROOT / "package.json"
        pyproject_file = ROOT / "pyproject.toml"
        npmrc_file = ROOT / ".npmrc"
        lock_file = ROOT / "package-lock.json"
        if not package_file.exists() or not pyproject_file.exists() or not npmrc_file.exists():
            self.fail("REPOSITORY_CONTRACT_FILES_MISSING")
        if not lock_file.exists():
            self.fail("PACKAGE_LOCK_MISSING")
        package = json.loads(package_file.read_text(encoding="utf-8"))
        pyproject = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
        try:
            lock = json.loads(lock_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.fail("PACKAGE_LOCK_INVALID_JSON")
        paths = {path for path in REQUIRED_PATHS if (ROOT / path).is_file()}
        self.assertEqual(repository_contract_errors(package, pyproject, paths, npmrc_file.read_text(encoding="utf-8"), lock), [])
