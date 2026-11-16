"""Tests for Phase 2 concept similarity, genus/differentia definitions, roundtrip checks, and Redis test helpers."""
from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ontautology as ot  # noqa: E402
from redis_helper import FakeRedis, RedisError, RedisTestClient, open_test_redis  # noqa: E402

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples/concepts-20261115.json"
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "ontautology.py"


def _load_example():
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


class ConceptDefinitionTests(unittest.TestCase):
    def test_six_example_pairs_derive_genus_differentia_and_unique_roundtrip(self):
        corpus = _load_example()
        defined = ot.define_concepts(corpus)
        self.assertEqual(defined["similar_pairs"], 6)
        self.assertEqual(defined["unknown"], [])
        concepts = defined["concepts"]
        expected_genus = {
            "ギター": ["フレット", "ボディ", "弦楽器", "撥弦", "楽器"],
            "ピカチュウ": ["でんきタイプ", "ねずみ分類", "ポケモン"],
            "鮭": ["サケ属", "サケ科", "遡河回遊魚", "食用", "魚類"],
            "iPhone": ["アプリ実行環境", "スマートフォン", "タッチパネル", "モバイル通信"],
            "エナジードリンク": ["カフェイン含有", "覚醒目的", "飲料"],
            "マリオ": ["オーバーオール", "ゲームキャラクター", "人間", "任天堂", "帽子", "配管工"],
        }
        for name, genus in expected_genus.items():
            with self.subTest(concept=name):
                entry = concepts[name]
                self.assertEqual(entry["status"], "unique")
                self.assertEqual(entry["basis"], "derived")
                self.assertEqual(entry["genus"]["all_common"], genus)
                self.assertEqual(entry["definition"]["roundtrip"], {"verdict": "unique", "matched": [name]})
                self.assertTrue(entry["definition"]["differentia"])

    def test_counterexample_breaks_roundtrip_and_forces_stronger_differentia(self):
        corpus = _load_example()
        before = ot.define_concepts(corpus, ["ギター"])["concepts"]["ギター"]
        self.assertIn(["6弦標準"], before["differentia"]["minimal_keys"])

        # Add a counterexample (Aoi-style): a 6-string bass shares 6弦標準 with ギター.
        with_counter = copy.deepcopy(corpus)
        with_counter["similar"].append({"left": "ギター", "right": "6弦ベース", "basis": "observed"})
        with_counter["concepts"]["6弦ベース"] = ["楽器", "弦楽器", "撥弦", "フレット", "ボディ", "6弦標準", "低音主体"]

        rt = ot.roundtrip_elements(with_counter, ["6弦標準"])
        self.assertEqual(rt["verdict"], "collides")
        self.assertEqual(rt["matched"], ["6弦ベース", "ギター"])

        after = ot.define_concepts(with_counter, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(after["status"], "unique")
        self.assertNotIn(["6弦標準"], after["differentia"]["minimal_keys"])
        self.assertEqual(after["differentia"]["minimal_keys"], [["中高音主体"]])

    def test_subset_elements_report_unavoidable_collision_and_stay_hypothesis(self):
        corpus = _load_example()
        corpus["similar"].append(["ギター", "楽器の何か"])
        corpus["concepts"]["楽器の何か"] = ["楽器", "弦楽器", "撥弦"]
        entry = ot.define_concepts(corpus, ["楽器の何か"])["concepts"]["楽器の何か"]
        self.assertEqual(entry["status"], "collides")
        self.assertEqual(entry["basis"], "hypothesis")
        self.assertEqual(entry["differentia"]["unavoidable_collisions"], ["ギター", "ベース"])
        self.assertEqual(entry["definition"]["roundtrip"]["verdict"], "collides")

    def test_unobserved_similar_peer_or_hypothesis_link_prevents_derived_promotion(self):
        corpus = {
            "similar": [{"left": "ギター", "right": "ウクレレ", "basis": "observed"}],
            "concepts": {"ギター": ["楽器", "弦楽器", "6弦標準"]},
        }
        entry = ot.define_concepts(corpus, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(entry["status"], "incomplete")
        self.assertEqual(entry["basis"], "hypothesis")
        self.assertEqual(entry["unobserved_similar"], ["ウクレレ"])
        self.assertIsNone(ot.define_concepts(corpus, ["ウクレレ"])["concepts"]["ウクレレ"]["elements"])

        guess_only = {
            "similar": [{"left": "ギター", "right": "ベース", "basis": "hypothesis"}],
            "concepts": {"ギター": ["楽器", "6弦"], "ベース": ["楽器", "4弦"]},
        }
        guessed = ot.define_concepts(guess_only, ["ギター"])["concepts"]["ギター"]
        self.assertEqual(guessed["status"], "unique")
        self.assertEqual(guessed["basis"], "hypothesis")

    def test_core_graph_projection_supports_check_reach_why_and_ladder(self):
        corpus = _load_example()
        projected = ot.concept_edges(corpus)
        nodes = [n["id"] for n in projected["nodes"]]
        edges = projected["edges"]
        self.assertEqual(ot.check(edges, nodes), [])
        reached = ot.reach(edges, ["elem:カフェイン含有"])
        self.assertEqual({r["node"] for r in reached["rows"]}, {"concept:エナジードリンク", "concept:コーヒー"})
        why = ot.why(edges, "concept:ギター", depth=1)
        self.assertTrue(any(r["edge"]["kind"] == "similarTo" and r["edge"]["source"] == "concept:ベース" for r in why["rows"]))
        counts = ot.ladder(edges)["basis"]
        self.assertGreater(counts["observed"], 0)
        self.assertGreater(counts["derived"], 0)


class ConceptCliTests(unittest.TestCase):
    def run_cli(self, *args, data=None, seed="1"):
        return subprocess.run(
            [sys.executable, "-S", str(SCRIPT_PATH), *args],
            input=None if data is None else data.encode("utf-8"),
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )

    def test_define_and_roundtrip_cli_exit_codes_and_determinism(self):
        corpus = _load_example()
        p_ok = self.run_cli("roundtrip", str(EXAMPLE_PATH), "カフェイン含有", "炭酸", "飲料")
        self.assertEqual(p_ok.returncode, 0, p_ok.stderr)
        self.assertEqual(json.loads(p_ok.stdout)["matched"], ["エナジードリンク"])

        p_col = self.run_cli("roundtrip", str(EXAMPLE_PATH), "カフェイン含有", "飲料")
        self.assertEqual(p_col.returncode, 2, p_col.stderr)
        self.assertEqual(json.loads(p_col.stdout)["verdict"], "collides")

        p_empty = self.run_cli("roundtrip", str(EXAMPLE_PATH), "存在しない要素")
        self.assertEqual(p_empty.returncode, 2, p_empty.stderr)
        self.assertEqual(json.loads(p_empty.stdout)["verdict"], "empty")

        p_unknown = self.run_cli("define", str(EXAMPLE_PATH), "未知の単語")
        self.assertEqual(p_unknown.returncode, 2, p_unknown.stderr)
        self.assertEqual(json.loads(p_unknown.stdout)["unknown"], ["未知の単語"])

        reversed_corpus = {
            "schema": corpus["schema"],
            "similar": list(reversed(corpus["similar"])),
            "concepts": {k: list(reversed(v)) for k, v in reversed(list(corpus["concepts"].items()))},
        }
        out_a = self.run_cli("define", "-", data=json.dumps(corpus, ensure_ascii=False), seed="1")
        out_b = self.run_cli("define", "-", data=json.dumps(reversed_corpus, ensure_ascii=False), seed="99")
        self.assertEqual(out_a.returncode, 0, out_a.stderr)
        self.assertEqual(out_b.returncode, 0, out_b.stderr)
        self.assertEqual(out_a.stdout, out_b.stdout)

    def test_core_cli_commands_read_concept_corpus_directly(self):
        p = self.run_cli("reach", str(EXAMPLE_PATH), "elem:カフェイン含有")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual({r["node"] for r in json.loads(p.stdout)["rows"]},
                         {"concept:エナジードリンク", "concept:コーヒー"})


def _start_mock_resp_server():
    """Minimal in-process RESP2 server backed by FakeRedis to verify RedisTestClient over TCP."""
    store = FakeRedis()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def read_line(conn, buf):
        while b"\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            buf.extend(chunk)
        idx = buf.find(b"\r\n")
        line = bytes(buf[:idx])
        del buf[: idx + 2]
        return line

    def read_command(conn, buf):
        header = read_line(conn, buf)
        if header is None:
            return None
        if not header.startswith(b"*"):
            raise ValueError("expected array")
        argc = int(header[1:])
        args = []
        for _ in range(argc):
            size_line = read_line(conn, buf)
            size = int(size_line[1:])
            while len(buf) < size + 2:
                chunk = conn.recv(4096)
                if not chunk:
                    raise EOFError("truncated bulk")
                buf.extend(chunk)
            args.append(bytes(buf[:size]).decode("utf-8"))
            del buf[: size + 2]
        return args

    def encode_reply(value):
        if isinstance(value, Exception):
            return f"-ERR {value}\r\n".encode("utf-8")
        if value is None:
            return b"$-1\r\n"
        if isinstance(value, int):
            return f":{value}\r\n".encode("ascii")
        if isinstance(value, str):
            raw = value.encode("utf-8")
            return f"${len(raw)}\r\n".encode("ascii") + raw + b"\r\n"
        if isinstance(value, (list, set, tuple)):
            items = list(value)
            return b"".join([f"*{len(items)}\r\n".encode("ascii")] + [encode_reply(str(x)) for x in items])
        raise TypeError(type(value))

    def handle(conn):
        buf = bytearray()
        with conn:
            while not stop.is_set():
                args = read_command(conn, buf)
                if args is None:
                    break
                cmd = args[0].upper()
                if cmd == "PING":
                    conn.sendall(b"+PONG\r\n")
                elif cmd == "SELECT":
                    conn.sendall(b"+OK\r\n")
                elif cmd == "FLUSHDB":
                    store.flushdb()
                    conn.sendall(b"+OK\r\n")
                elif cmd == "SADD":
                    conn.sendall(encode_reply(store.sadd(args[1], *args[2:])))
                elif cmd == "SMEMBERS":
                    conn.sendall(encode_reply(sorted(store.smembers(args[1]))))
                elif cmd == "SINTER":
                    conn.sendall(encode_reply(sorted(store.sinter(*args[1:]))))
                elif cmd == "SDIFF":
                    conn.sendall(encode_reply(sorted(store.sdiff(args[1], *args[2:]))))
                elif cmd == "SET":
                    store.set(args[1], args[2])
                    conn.sendall(b"+OK\r\n")
                elif cmd == "GET":
                    conn.sendall(encode_reply(store.get(args[1])))
                elif cmd == "HSET":
                    conn.sendall(encode_reply(store.hset(args[1], args[2], args[3])))
                elif cmd == "HGETALL":
                    flat = [kv for pair in sorted(store.hgetall(args[1]).items()) for kv in pair]
                    conn.sendall(encode_reply(flat))
                else:
                    conn.sendall(encode_reply(ValueError(f"unsupported command {cmd}")))

    def serve():
        while not stop.is_set():
            try:
                srv.settimeout(0.2)
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, stop, srv


class RedisTestHelperTests(unittest.TestCase):
    def test_resp_client_works_over_tcp_with_utf8_japanese(self):
        port, stop, srv = _start_mock_resp_server()
        try:
            with RedisTestClient.from_url(f"redis://127.0.0.1:{port}/2") as r:
                self.assertTrue(r.ping())
                r.flushdb()
                self.assertEqual(r.sadd("elem:ギター", "楽器", "弦楽器", "6弦標準"), 3)
                self.assertEqual(r.sadd("elem:ベース", "楽器", "弦楽器", "4弦標準"), 3)
                self.assertEqual(r.sinter("elem:ギター", "elem:ベース"), {"楽器", "弦楽器"})
                self.assertEqual(r.sdiff("elem:ギター", "elem:ベース"), {"6弦標準"})
                r.set("cache:key", "値")
                self.assertEqual(r.get("cache:key"), "値")
                self.assertIsNone(r.get("cache:missing"))
                r.hset("roundtrip:cache", "ギター", "unique")
                self.assertEqual(r.hgetall("roundtrip:cache"), {"ギター": "unique"})
                with self.assertRaises(RedisError):
                    r.command("UNKNOWNCMD")
        finally:
            stop.set()
            srv.close()

    def _run_redis_oracle_and_cache(self, client):
        corpus = _load_example()
        defined = ot.define_concepts(corpus)["concepts"]
        client.flushdb()
        for name, elems in corpus["concepts"].items():
            client.sadd(f"otl:elem:{name}", *elems)
        # 1. Verify Redis SINTER / SDIFF agrees with define_concepts() genus & differentia.
        for pair in corpus["similar"]:
            left, right = pair["left"], pair["right"]
            common = client.sinter(f"otl:elem:{left}", f"otl:elem:{right}")
            diff_left = client.sdiff(f"otl:elem:{left}", f"otl:elem:{right}")
            self.assertEqual(sorted(common), defined[left]["genus"]["by_similar"][right]["common"])
            self.assertEqual(sorted(diff_left), defined[left]["differentia"]["vs_similar"][right]["only_target"])
        # 2. Cache roundtrip answers in a Redis hash and confirm replay agrees.
        for name, info in defined.items():
            query = info["definition"]["elements"]
            rt = ot.roundtrip_elements(corpus, query)
            client.hset("otl:roundtrip", "+".join(query), json.dumps(rt, ensure_ascii=False))
        cached = client.hgetall("otl:roundtrip")
        self.assertEqual(len(cached), len(corpus["concepts"]))
        for payload in cached.values():
            self.assertEqual(json.loads(payload)["verdict"], "unique")

    def test_redis_oracle_and_roundtrip_cache_default_helper(self):
        client, _ = open_test_redis()
        with client:
            self._run_redis_oracle_and_cache(client)

    @unittest.skipUnless(os.environ.get("REDIS_URL"), "Set REDIS_URL to run against a live Redis server")
    def test_live_redis_oracle_and_roundtrip_cache(self):
        with RedisTestClient.from_url(os.environ["REDIS_URL"]) as client:
            self.assertTrue(client.ping())
            self._run_redis_oracle_and_cache(client)


if __name__ == "__main__":
    unittest.main()
