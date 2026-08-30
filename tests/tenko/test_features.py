from __future__ import annotations

from dataclasses import dataclass

from tenko.host.features import FeatureService


@dataclass
class Owner:
    name: str
    display_name: str = "演示插件"


def test_feature_group_switch_round_trip(tmp_path) -> None:
    state_path = tmp_path / "features.json"
    service = FeatureService(state_path)

    assert service.is_enabled("demo", "40001")
    assert service.disable("demo", "40001") is False
    assert not service.is_enabled("demo", "40001")
    assert service.is_enabled("demo", "40002")

    restored = FeatureService(state_path)
    assert not restored.is_enabled("demo", "40001")
    assert restored.is_enabled("demo", "40002")

    restored.enable("demo", "40001")
    assert FeatureService(state_path).is_enabled("demo", "40001")


def test_feature_maintenance_overrides_group_state(tmp_path) -> None:
    service = FeatureService(tmp_path / "features.json")
    service.disable("demo", "40001")
    service.set_maintenance("demo", True)

    assert not service.is_enabled("demo", "40001")
    assert not service.is_enabled("demo", "40002")

    service.set_maintenance("demo", False)
    assert not service.is_enabled("demo", "40001")
    assert service.is_enabled("demo", "40002")
