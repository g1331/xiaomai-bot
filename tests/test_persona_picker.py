"""_pick_bf1_persona 同名多账号消歧测试

回归保护：EA 允许多账号共用同一 displayName(本次事故中 "Sipne" 同时落到真号
1008491571150 和不玩 BF1 的空号 1004344969376)，原实现盲取 candidates[0] 把
空号写进 vip 表，导致 -checkvip 永远 -32856 玩家不存在。修复要求按 BF1 生涯
时长 timePlayed 区分真号。
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

bf_utils = pytest.importorskip(
    "utils.bf1.bf_utils",
    reason="bf_utils 依赖未装齐(uv sync 后再跑)",
)


class _FakeApi:
    """detailedStatsByPersonaId 的最小桩，按 pid 查表回填 timePlayed"""

    def __init__(self, times: dict[str, int]):
        self._times = times

    async def detailedStatsByPersonaId(self, pid):
        return {"result": {"basicStats": {"timePlayed": self._times.get(str(pid), 0)}}}


class _FakeBF1DA:
    api: _FakeApi | None = None

    @classmethod
    async def get_api_instance(cls):
        return cls.api


def test_single_candidate_skips_api(monkeypatch):
    """单候选不应调用 EA 接口(零开销路径)"""
    sentinel = _FakeApi({})

    async def _boom():
        raise AssertionError("不该被调到")

    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = sentinel
    sentinel.detailedStatsByPersonaId = lambda pid: _boom()  # type: ignore[assignment]

    only = {"personaId": 42, "displayName": "X"}
    assert asyncio.run(bf_utils._pick_bf1_persona([only])) is only


def test_multi_candidate_picks_player_with_playtime(monkeypatch):
    """同名多账号必须挑出 timePlayed > 0 的真号(本次事故的核心回归点)"""
    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _FakeApi(
        {"1008491571150": 3_257_572, "1004344969376": 0}  # 904h vs 0
    )
    void = {"personaId": 1004344969376, "displayName": "Sipne"}
    real = {"personaId": 1008491571150, "displayName": "Sipne"}
    chosen = asyncio.run(bf_utils._pick_bf1_persona([void, real]))
    assert chosen is real, "应当挑出有 BF1 生涯时长的真号"


def test_multi_candidate_all_zero_returns_first(monkeypatch):
    """全 0 / 全无生涯时退回首个，保持解析不阻断"""
    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _FakeApi({})
    a = {"personaId": 1, "displayName": "X"}
    b = {"personaId": 2, "displayName": "X"}
    assert asyncio.run(bf_utils._pick_bf1_persona([a, b])) is a


def test_multi_candidate_api_error_falls_back_to_first(monkeypatch):
    """EA 抽风时不阻断(异常→视作 0→退回首个)"""

    class _BrokenApi:
        async def detailedStatsByPersonaId(self, pid):
            raise RuntimeError("EA down")

    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _BrokenApi()  # type: ignore[assignment]
    a = {"personaId": 1, "displayName": "X"}
    b = {"personaId": 2, "displayName": "X"}
    assert asyncio.run(bf_utils._pick_bf1_persona([a, b])) is a


# ---- _gate_bf1_player：服管路径"非 BF1 玩家"硬拦截 ----


def _dict_for(pid: int, name: str = "Sipne") -> dict:
    return {"personas": {"persona": [{"personaId": pid, "displayName": name}]}}


def test_gate_off_returns_dict_unchanged(monkeypatch):
    """require_bf1_player=False 时直接放行，不调 API"""
    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _FakeApi({})
    d = _dict_for(1004344969376)
    assert asyncio.run(bf_utils._gate_bf1_player("Sipne", d, False)) is d


def test_gate_on_rejects_zero_playtime(monkeypatch):
    """空号(timePlayed=0) 必须被服管路径拦截，返回字符串而非 dict"""
    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _FakeApi({"1004344969376": 0})
    d = _dict_for(1004344969376)
    result = asyncio.run(bf_utils._gate_bf1_player("Sipne", d, True))
    assert isinstance(result, str), "0 时长账号必须被拦"
    assert "1004344969376" in result and "不是 BF1 玩家" in result


def test_gate_on_passes_real_player(monkeypatch):
    """真号(timePlayed>0) 放行返回原 dict"""
    monkeypatch.setattr(bf_utils, "BF1DA", _FakeBF1DA)
    _FakeBF1DA.api = _FakeApi({"1008491571150": 3_257_572})
    d = _dict_for(1008491571150)
    assert asyncio.run(bf_utils._gate_bf1_player("Sipne", d, True)) is d
