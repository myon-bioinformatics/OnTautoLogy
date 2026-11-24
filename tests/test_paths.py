"""checkout の解決順。配置は一時ディレクトリで、実在の隣の checkout は見ない。"""
import dis
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import onto_path  # noqa: E402

ROOT_ENVS = (onto_path.ONTO_ENV, onto_path.TAXONTOY_ENV, onto_path.TOPONTOLOGY_ENV)
MARKER = onto_path.ONTO_MARKER
STUB = "value = 1\n"
_JUMP_PREFIXES = (
    "POP_JUMP_IF_",
    "POP_JUMP_FORWARD_IF_",
    "POP_JUMP_BACKWARD_IF_",
    "JUMP_IF_",
)
_UNTRACED_OPS = {"CACHE", "END_FOR", "EXTENDED_ARG", "RESUME"}


def _conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(_JUMP_PREFIXES)


def _touch(path, text="marker\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_path_mutant(old, new):
    """実体の onto_path.py を一箇所だけ変えて実行する。"""
    source = Path(onto_path.__file__).read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise AssertionError(f"mutant anchor count {source.count(old)} for {old!r}")
    spec = importlib.util.spec_from_loader("onto_path_mutant", loader=None)
    module = importlib.util.module_from_spec(spec)
    filename = str(Path(tempfile.mkdtemp(prefix="onto-mutant-")) / "onto_path_mutant.py")
    exec(compile(source.replace(old, new, 1), filename, "exec"), module.__dict__)
    return module


class PathCase(unittest.TestCase):
    def setUp(self):
        self._saved_env = {name: os.environ.get(name) for name in ROOT_ENVS}
        for name in ROOT_ENVS:
            os.environ.pop(name, None)
        self._saved_modules = {
            name: sys.modules.get(name) for name in ("knowledgegraph", "pytest")
        }
        self._saved_path = list(sys.path)
        onto_path.RESOLVED.clear()

    def tearDown(self):
        sys.path[:] = self._saved_path
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        onto_path.RESOLVED.clear()


class LayoutTests(PathCase):
    def test_constants_keep_the_existing_environment_names(self):
        self.assertEqual(onto_path.OTL_ROOTS_ENV, "OTL_ROOTS")
        self.assertEqual(onto_path.OTL_GIT_REPO_ENV, "OTL_GIT_REPO")
        self.assertEqual(onto_path.OTL_GIT_REF_ENV, "OTL_GIT_REF")
        self.assertEqual(onto_path.OTL_GIT_SHA_ENV, "OTL_GIT_SHA")
        self.assertEqual(onto_path.OTL_LIVE_ENV, "OTL_LIVE")
        self.assertEqual(onto_path.OTL_EXPORT_DIR_ENV, "OTL_EXPORT_DIR")
        self.assertEqual(onto_path.import_roots(), ("ONTO",))
        self.assertNotIn("pytest", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_anchor_may_be_a_file_a_directory_or_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            tool = _touch(folder / "app" / "tool.py", "")
            self.assertEqual(onto_path._anchor_dir(tool), tool.parent.resolve())
            self.assertEqual(onto_path._anchor_dir(tool.parent), tool.parent.resolve())
        self.assertEqual(onto_path._anchor_dir(None), Path(onto_path.__file__).resolve().parent)

    def test_explicit_beats_env_and_env_beats_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            explicit = _touch(folder / "explicit" / MARKER, STUB).parent
            via_env = _touch(folder / "from-env" / MARKER, STUB).parent
            sibling = _touch(folder / "ONTO" / MARKER, STUB).parent
            anchor = _touch(folder / "app" / "tool.py", "")
            os.environ[onto_path.ONTO_ENV] = str(via_env)
            self.assertEqual(onto_path.resolve_root("ONTO", explicit, anchor=anchor), explicit.resolve())
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=anchor), via_env.resolve())
            os.environ.pop(onto_path.ONTO_ENV)
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=anchor), sibling.resolve())
            self.assertEqual(
                onto_path.marker_file("ONTO", anchor=anchor),
                sibling.resolve() / MARKER,
            )

    def test_blank_explicit_does_not_fall_through_and_blank_env_does(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sibling = _touch(folder / "ONTO" / MARKER, STUB).parent
            via_env = _touch(folder / "from-env" / MARKER, STUB).parent
            anchor = _touch(folder / "app" / "tool.py", "")
            os.environ[onto_path.ONTO_ENV] = str(via_env)
            for blank in ("", "   "):
                with self.assertRaises(onto_path.RootError) as raised:
                    onto_path.resolve_root("ONTO", blank, anchor=anchor)
                self.assertIn(onto_path.ONTO_ENV, str(raised.exception))
            os.environ[onto_path.ONTO_ENV] = "   "
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=anchor), sibling.resolve())
            os.environ.pop(onto_path.ONTO_ENV)
            self.assertEqual(onto_path.resolve_root("ONTO", None, anchor=anchor), sibling.resolve())

    def test_bad_env_does_not_infer_and_names_the_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            _touch(folder / "ONTO" / MARKER, STUB)
            empty = folder / "empty"
            empty.mkdir()
            anchor = _touch(folder / "app" / "tool.py", "")
            os.environ[onto_path.ONTO_ENV] = str(empty)
            with self.assertRaises(onto_path.RootError) as raised:
                onto_path.resolve_root("ONTO", anchor=anchor)
            message = str(raised.exception)
            self.assertIn(onto_path.ONTO_ENV, message)
            self.assertIn(str(empty.resolve()), message)
            self.assertIn(MARKER, message)

    def test_an_unexpected_lookup_error_is_not_swallowed(self):
        original = onto_path.ROOTS

        class Boom(dict):
            def __getitem__(self, key):
                raise ValueError("lookup")

        onto_path.ROOTS = Boom()
        try:
            with self.assertRaises(ValueError):
                onto_path._spec("ONTO")
        finally:
            onto_path.ROOTS = original

    def test_missing_checkout_names_the_env_var(self):
        with self.assertRaises(onto_path.RootError) as raised:
            onto_path.resolve_root("ONTO", anchor="/")
        self.assertIn(onto_path.ONTO_ENV, str(raised.exception))
        self.assertIn("見つからない", str(raised.exception))
        with self.assertRaises(onto_path.RootError) as unknown:
            onto_path.resolve_root("missing")
        self.assertIn("ONTO", str(unknown.exception))
        self.assertIn("TaxOntOy", str(unknown.exception))
        self.assertIsNone(onto_path.infer_checkout("ONTO", MARKER, anchor="/"))
        self.assertIsNone(onto_path.infer_checkout(".", "onto-path-absent-marker.py", anchor="/"))

    def test_child_grandchild_and_the_dot_dirname(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = _touch(folder / "ONTO" / MARKER, STUB).parent
            nested = _touch(folder / "ONTO" / "pkg" / "tool.py", "")
            deep = _touch(folder / "a" / "b" / "c" / "tool.py", "")
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=nested), onto.resolve())
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=deep), onto.resolve())
            marked = _touch(folder / "pkg" / MARKER, STUB).parent
            tool = _touch(folder / "pkg" / "tool.py", "")
            self.assertEqual(onto_path.infer_checkout(".", MARKER, anchor=tool), marked.resolve())
            unmarked = _touch(folder / "plain" / "tool.py", "")
            parent_marker = _touch(folder / MARKER, STUB)
            self.assertEqual(
                onto_path.infer_checkout(".", MARKER, anchor=unmarked),
                parent_marker.parent.resolve(),
            )

    def test_a_nested_copy_is_found_when_there_is_no_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            nested = _touch(folder / "app" / "ONTO" / MARKER, STUB).parent
            anchor = _touch(folder / "app" / "tool.py", "")
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=anchor), nested.resolve())

    def test_sibling_beats_a_nested_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sibling = _touch(folder / "ONTO" / MARKER, STUB).parent
            _touch(folder / "app" / "ONTO" / MARKER, STUB)
            anchor = _touch(folder / "app" / "tool.py", "")
            self.assertEqual(onto_path.resolve_root("ONTO", anchor=anchor), sibling.resolve())

    def test_a_directory_marker_is_not_a_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = folder / "ONTO"
            (onto / MARKER).mkdir(parents=True)
            anchor = _touch(folder / "app" / "tool.py", "")
            found = onto_path.infer_checkout("ONTO", MARKER, anchor=anchor)
            self.assertNotEqual(found, onto.resolve())

    def test_tilde_in_an_explicit_root_is_expanded(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            onto = _touch(home / "ONTO" / MARKER, STUB).parent
            anchor = _touch(Path(directory) / "tool.py", "")
            with patch.dict(os.environ, {"HOME": str(home)}):
                self.assertEqual(
                    onto_path.resolve_root("ONTO", "~/ONTO", anchor=anchor),
                    onto.resolve(),
                )

    def test_optional_roots_are_not_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = _touch(folder / "ONTO" / MARKER, STUB).parent
            tax = _touch(folder / "TaxOntOy" / onto_path.TAXONTOY_MARKER, "{}\n").parent
            tol = _touch(folder / "TopOntoLogy" / onto_path.TOPONTOLOGY_MARKER, "").parent
            other = _touch(folder / "other-tax" / onto_path.TAXONTOY_MARKER, "{}\n").parent
            anchor = _touch(folder / "app" / "tool.py", "")
            sys.modules.pop("knowledgegraph", None)
            found = onto_path.bind(anchor, names=("TaxOntOy", "TopOntoLogy"))
            self.assertEqual(found["TaxOntOy"], tax.resolve())
            self.assertEqual(found["TopOntoLogy"], tol.resolve())
            self.assertNotIn("knowledgegraph", sys.modules)
            self.assertNotIn(str(onto.resolve()), sys.path)
            self.assertEqual(os.environ[onto_path.TAXONTOY_ENV], str(tax.resolve()))
            os.environ[onto_path.TAXONTOY_ENV] = str(tax.resolve())
            onto_path.bind(anchor, {"TaxOntOy": other}, names=("TaxOntOy",))
            self.assertEqual(os.environ[onto_path.TAXONTOY_ENV], str(tax.resolve()))

    def test_bind_installs_onto_and_checks_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = _touch(folder / "ONTO" / MARKER, STUB).parent
            anchor = _touch(folder / "app" / "tool.py", "")
            sys.modules.pop("knowledgegraph", None)
            found = onto_path.bind(anchor, {"ONTO": str(onto)}, names=("ONTO",))
            self.assertEqual(found["ONTO"], onto.resolve())
            self.assertEqual(sys.path[0], str(onto.resolve()))
            self.assertEqual(Path(sys.modules["knowledgegraph"].__file__).resolve().parent, onto.resolve())
            again = onto_path.bind(anchor, {"ONTO": onto}, names=("ONTO",))
            self.assertEqual(again["ONTO"], onto.resolve())
            self.assertEqual(sys.path[0], str(onto.resolve()))
            self.assertEqual(onto_path.RESOLVED["ONTO"], onto.resolve())
            wrong = types.ModuleType("knowledgegraph")
            wrong.__file__ = str(folder / "other" / MARKER)
            sys.modules["knowledgegraph"] = wrong
            with self.assertRaises(onto_path.RootError) as raised:
                onto_path.verify_origin(onto, ("knowledgegraph",), onto_path.ONTO_ENV)
            self.assertIn(onto_path.ONTO_ENV, str(raised.exception))
            self.assertIn("knowledgegraph=", str(raised.exception))
            nameless = types.ModuleType("knowledgegraph")
            sys.modules["knowledgegraph"] = nameless
            with self.assertRaises(onto_path.RootError) as missing_file:
                onto_path.verify_origin(onto, ("knowledgegraph",), onto_path.ONTO_ENV)
            self.assertIn("(なし)", str(missing_file.exception))
            self.assertEqual(onto_path.verify_origin(onto, (), onto_path.ONTO_ENV), onto.resolve())
            tax = _touch(folder / "TaxOntOy" / onto_path.TAXONTOY_MARKER, "{}\n").parent
            tol = _touch(folder / "TopOntoLogy" / onto_path.TOPONTOLOGY_MARKER, "").parent
            sys.modules.pop("knowledgegraph", None)
            every = onto_path.bind(anchor)
            self.assertEqual(set(every), {"ONTO", "TaxOntOy", "TopOntoLogy"})
            self.assertEqual(every["TaxOntOy"], tax.resolve())
            self.assertEqual(every["TopOntoLogy"], tol.resolve())

    def test_import_failure_is_the_exception_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = _touch(folder / "ONTO" / MARKER, "raise RuntimeError('壊れた')\n").parent
            anchor = _touch(folder / "app" / "tool.py", "")
            sys.modules.pop("knowledgegraph", None)
            with self.assertRaises(RuntimeError) as raised:
                onto_path.bind(anchor, {"ONTO": onto}, names=("ONTO",))
            self.assertEqual(str(raised.exception), "壊れた")


class FlagTests(PathCase):
    def test_equals_form_keeps_the_following_argument(self):
        found = onto_path.explicit_from_argv([
            "--onto-root=/onto",
            "audit",
            "--taxontoy-root=/tax",
            "--topontology-root",
            "/tol",
        ])
        self.assertEqual(found, {
            "ONTO": "/onto",
            "TaxOntOy": "/tax",
            "TopOntoLogy": "/tol",
        })

    def test_last_duplicate_wins_and_stop_and_missing_value(self):
        self.assertEqual(
            onto_path.explicit_from_argv([])["ONTO"],
            None,
        )
        found = onto_path.explicit_from_argv([
            "--onto-root", "/first",
            "--onto-root=/second",
            "--",
            "--taxontoy-root", "/ignored",
        ])
        self.assertEqual(found["ONTO"], "/second")
        self.assertIsNone(found["TaxOntOy"])
        with self.assertRaises(onto_path.RootError) as raised:
            onto_path.explicit_from_argv(["--topontology-root"])
        self.assertIn("--topontology-root", str(raised.exception))
        self.assertIn(onto_path.TOPONTOLOGY_ENV, str(raised.exception))
        with self.assertRaises(onto_path.RootError):
            onto_path.explicit_from_argv(["keep", "--onto-root"])


class MutationTests(PathCase):
    def test_skipping_the_argument_after_equals_is_killed(self):
        mutant = load_path_mutant(
            "                index += 1\n"
            "                handled = True\n",
            "                index += 2\n"
            "                handled = True\n",
        )
        argv = ["--onto-root=/first", "--onto-root", "/second"]
        self.assertEqual(onto_path.explicit_from_argv(argv)["ONTO"], "/second")
        self.assertEqual(mutant.explicit_from_argv(argv)["ONTO"], "/first")

    def test_equals_form_marking_itself_unhandled_is_killed(self):
        mutant = load_path_mutant(
            "                index += 1\n"
            "                handled = True\n",
            "                index += 1\n"
            "                handled = False\n",
        )
        argv = ["--onto-root=/first", "--onto-root", "/second"]
        self.assertEqual(onto_path.explicit_from_argv(argv)["ONTO"], "/second")
        self.assertEqual(mutant.explicit_from_argv(argv)["ONTO"], "/first")

    def test_ignoring_the_equals_form_is_killed(self):
        mutant = load_path_mutant(
            "            if token.startswith(prefix):\n",
            "            if False and token.startswith(prefix):\n",
        )
        argv = ["--onto-root=/onto", "audit"]
        self.assertEqual(onto_path.explicit_from_argv(argv)["ONTO"], "/onto")
        self.assertIsNone(mutant.explicit_from_argv(argv)["ONTO"])


def _pytest_stub():
    stub = types.ModuleType("pytest")
    stub.UsageError = type("UsageError", (Exception,), {})
    return stub


def _load_conftest():
    previous = sys.modules.get("pytest")
    sys.modules["pytest"] = _pytest_stub()
    module = types.ModuleType("conftest_under_test")
    module.__file__ = str(ROOT / "conftest.py")
    code = compile((ROOT / "conftest.py").read_text(encoding="utf-8"), module.__file__, "exec")
    try:
        exec(code, module.__dict__)
    except Exception:
        if previous is None:
            sys.modules.pop("pytest", None)
        else:
            sys.modules["pytest"] = previous
        raise
    return module


class ConftestTests(PathCase):
    def test_unresolved_root_is_a_usage_error_without_a_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ[onto_path.ONTO_ENV] = directory
            with self.assertRaises(Exception) as raised:
                _load_conftest()
        error = raised.exception
        self.assertEqual(type(error).__name__, "UsageError")
        self.assertIsNone(error.__cause__)
        self.assertIn(onto_path.ONTO_ENV, str(error))
        self.assertIn("見つからない", str(error))
        self.assertNotIn("Traceback", str(error))

    def test_activate_binds_only_import_roots_and_reports_import_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            onto = _touch(folder / "ONTO" / MARKER, STUB).parent
            os.environ[onto_path.ONTO_ENV] = str(onto)
            module = _load_conftest()
            self.assertEqual(
                module.collect_ignore,
                ["ONTO", "TaxOntOy", "TopOntoLogy", "too", "tol", "otl", "build"],
            )
            self.assertEqual(module.activate(folder / "tool.py")["ONTO"], onto.resolve())
            with patch.object(onto_path, "import_roots", return_value=()):
                self.assertEqual(module.activate(), {})
            broken = _touch(folder / "broken" / MARKER, "raise RuntimeError('壊れた')\n").parent
            os.environ[onto_path.ONTO_ENV] = str(broken)
            sys.modules.pop("knowledgegraph", None)
            with self.assertRaises(module.pytest.UsageError) as raised:
                module.activate(folder / "tool.py")
            self.assertEqual(str(raised.exception), "壊れた")
            self.assertIsNone(raised.exception.__cause__)
            with patch.object(onto_path, "bind", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    module.activate(folder / "tool.py")


def _static_arcs(code):
    arcs = set()
    blocks = []

    def walk(block):
        blocks.append(block)
        for const in block.co_consts:
            if hasattr(const, "co_code"):
                walk(const)

    walk(code)
    for block in blocks:
        insns = [ins for ins in dis.get_instructions(block) if ins.opname not in {"CACHE", "EXTENDED_ARG"}]
        ident = f"{block.co_firstlineno}:{block.co_qualname}"
        for index, ins in enumerate(insns):
            if not _conditional(ins.opname):
                continue
            fall = next(item.offset for item in insns[index + 1:] if item.opname not in _UNTRACED_OPS)
            target = next(item.offset for item in insns if item.offset >= ins.argval and item.opname not in _UNTRACED_OPS)
            arcs.add((ident, ins.offset, fall))
            arcs.add((ident, ins.offset, target))
    return arcs


_WRAPPER = r"""
import dis, functools, os, runpy, sys
from pathlib import Path
realpath = functools.lru_cache(maxsize=None)(os.path.realpath)  # ⚡ one realpath per file, not one per traced call (the hook runs on every call of every test)
script, dest, targets = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [script, *sys.argv[4:]]
wanted = {os.path.realpath(item) for item in targets.split(",")}
lines, arcs, pending = {}, {}, {}
prefixes = ("POP_JUMP_IF_", "POP_JUMP_FORWARD_IF_", "POP_JUMP_BACKWARD_IF_", "JUMP_IF_")

def conditional(opname):
    return opname == "FOR_ITER" or opname.startswith(prefixes)

def qual(code):
    return f"{code.co_firstlineno}:{code.co_qualname}"

def hook(frame, event, arg):
    filename = realpath(frame.f_code.co_filename)
    if filename not in wanted:
        return None
    frame.f_trace_opcodes = True
    bucket_lines = lines.setdefault(filename, set())
    bucket_arcs = arcs.setdefault(filename, set())
    if event == "line":
        bucket_lines.add(frame.f_lineno)
    elif event == "opcode":
        code = frame.f_code
        key = id(frame)
        offset = frame.f_lasti
        prev = pending.get(key)
        if prev is not None:
            bucket_arcs.add((prev[0], prev[1], offset))
            del pending[key]
        real = offset
        name = dis.opname[code.co_code[real]]
        while name == "EXTENDED_ARG":
            real += 2
            name = dis.opname[code.co_code[real]]
        if conditional(name):
            pending[key] = (qual(code), real, filename)
    elif event == "return":
        pending.pop(id(frame), None)
    return hook

sys.settrace(hook)
status = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    sys.settrace(None)
    body = []
    for filename in sorted(wanted):
        body.append("FILE")
        body.append(filename)
        body.append("LINES")
        body.extend(str(number) for number in sorted(lines.get(filename, ())))
        body.append("ARCS")
        body.extend(
            f"{ident}\t{src}\t{dst}" for ident, src, dst in sorted(arcs.get(filename, ()))
        )
    Path(dest).write_text("\n".join(body) + "\n", encoding="utf-8")
raise SystemExit(status)
"""

_DRIVER = r"""
import os, sys, unittest
from pathlib import Path
root = Path(os.environ["OTL_PATH_REPO"])
sys.path[:0] = [str(root), str(root / "tests")]
os.environ["OTL_PATH_COVERAGE_CHILD"] = "1"
for key in ("ONTO_ROOT", "TAXONTOY_ROOT", "TOPONTOLOGY_ROOT", "PYTHONPATH"):
    os.environ.pop(key, None)
import test_paths
loader = unittest.defaultTestLoader
suite = unittest.TestSuite()
for name in ("LayoutTests", "FlagTests", "MutationTests", "ConftestTests"):
    suite.addTests(loader.loadTestsFromTestCase(getattr(test_paths, name)))
result = unittest.TextTestRunner(verbosity=0).run(suite)
import onto_path
builtin_tuple = tuple
onto_path.tuple = lambda items: builtin_tuple(items)
onto_path.import_roots()
del onto_path.tuple
raise SystemExit(0 if result.wasSuccessful() else 1)
"""


def _executable_lines(source, filename):
    compiled = compile(source, filename, "exec")
    found = set()

    def walk(block):
        for _start, _end, lineno in block.co_lines():
            if lineno:
                found.add(lineno)
        for const in block.co_consts:
            if hasattr(const, "co_lines"):
                walk(const)

    walk(compiled)
    return compiled, found


class ZCoverageTests(unittest.TestCase):
    def test_statements_and_branches_are_fully_executed(self):
        if os.environ.get("OTL_PATH_COVERAGE_CHILD"):
            return
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            driver = folder / "driver.py"
            dest = folder / "cover.txt"
            driver.write_text(_DRIVER, encoding="utf-8")
            targets = [
                str((ROOT / "onto_path.py").resolve()),
                str((ROOT / "conftest.py").resolve()),
            ]
            env = os.environ.copy()
            env["OTL_PATH_REPO"] = str(ROOT)
            env.pop("PYTHONPATH", None)
            child = subprocess.run(
                [sys.executable, "-S", "-c", _WRAPPER, str(driver), str(dest), ",".join(targets)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            recorded = {}
            current = None
            section = None
            for line in dest.read_text(encoding="utf-8").splitlines():
                if line == "FILE":
                    current = None
                    section = "FILE"
                    continue
                if line in {"LINES", "ARCS"}:
                    section = line
                    continue
                if section == "FILE":
                    current = line
                    recorded[current] = {"lines": set(), "arcs": set()}
                elif section == "LINES":
                    recorded[current]["lines"].add(int(line))
                elif section == "ARCS":
                    ident, src, dst = line.split("\t")
                    recorded[current]["arcs"].add((ident, int(src), int(dst)))
            report = []
            for path in targets:
                source = Path(path).read_text(encoding="utf-8")
                total = len(source.splitlines())
                compiled, executable = _executable_lines(source, path)
                seen_lines = recorded.get(path, {}).get("lines", set())
                executed = executable & seen_lines
                excluded = set(range(1, total + 1)) - executable
                unexecuted = executable - seen_lines
                self.assertEqual(len(executed) + len(excluded) + len(unexecuted), total)
                arcs = _static_arcs(compiled)
                seen_arcs = recorded.get(path, {}).get("arcs", set())
                executed_arcs = arcs & seen_arcs
                unexecuted_arcs = arcs - seen_arcs
                self.assertEqual(len(executed_arcs) + len(unexecuted_arcs), len(arcs))
                report.append(
                    f"{Path(path).name} statements executed={len(executed)} excluded={len(excluded)} "
                    f"unexecuted={len(unexecuted)} total={total} "
                    f"branches executed={len(executed_arcs)} unexecuted={len(unexecuted_arcs)} total={len(arcs)}"
                )
                if unexecuted or unexecuted_arcs:
                    lines = source.splitlines()
                    preview = "\n".join(f"{number}: {lines[number - 1]}" for number in sorted(unexecuted))
                    arc_preview = "\n".join(repr(item) for item in sorted(unexecuted_arcs)[:60])
                    self.fail(
                        f"{path}\nunexecuted lines {len(unexecuted)}\n{preview}\n"
                        f"unexecuted branches {len(unexecuted_arcs)}\n{arc_preview}"
                    )
            sys.stderr.write("\n".join(report) + "\n")


if __name__ == "__main__":
    unittest.main()
