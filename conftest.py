"""pytest 用の入口。検査の正は unittest で、pytest は依存にしない。

単独の checkout でも、親の子や孫として埋め込まれていても、import する根の場所は
onto_path が決める。モジュールを持たない根は、使うコマンドが解決する。
見つからないときや import に失敗したときは、トレースバックではなく一行で止める。
"""
from pathlib import Path

import pytest

import onto_path

# 裸の pytest が、隣の checkout や build をこのリポジトリの検査として集めない。
collect_ignore = ["ONTO", "TaxOntOy", "TopOntoLogy", "too", "tol", "otl", "build"]


def activate(anchor=None):
    """import が要る根だけを入れ、失敗したら UsageError にする。"""
    if anchor is None:
        anchor = Path(__file__)
    names = onto_path.import_roots()
    if not names:
        return {}
    try:
        return onto_path.bind(anchor, names=names)
    except Exception as error:
        raise pytest.UsageError(str(error)) from None


activate()
