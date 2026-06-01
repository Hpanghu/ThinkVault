"""
测试：硬件检测工具
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from thinkvault.utils.hardware import detect_hardware, MODEL_TIER_RECOMMENDATIONS


def test_detect_basic():
    """基本硬件检测"""
    profile = detect_hardware()

    assert profile.cpu_count > 0
    assert profile.total_ram_gb > 0
    assert profile.available_ram_gb > 0
    print(f"[PASS] 硬件检测: CPU={profile.cpu_count}核, RAM={profile.total_ram_gb}GB, GPU={profile.gpu_name or '无'}")


def test_model_recommendation():
    """模型推荐逻辑"""
    profile = detect_hardware()
    tier = profile.recommended_model_tier
    assert tier in ["light", "medium", "high", "ultra"]
    print(f"[PASS] 模型推荐档位: {tier}")

    spec = profile.recommended_model_spec
    assert "params" in spec
    assert "quant" in spec
    print(f"       推荐规格: {spec['params']} {spec['quant']}")


def test_recommendation_table():
    """推荐表完整性"""
    for tier in ["light", "medium", "high", "ultra"]:
        assert tier in MODEL_TIER_RECOMMENDATIONS
        assert len(MODEL_TIER_RECOMMENDATIONS[tier]["models"]) > 0
        for model in MODEL_TIER_RECOMMENDATIONS[tier]["models"]:
            assert "name" in model
            assert "url" in model
            assert "ollama.com" in model["url"]
    print(f"[PASS] 推荐表完整性: 4 个档位, 各含 {[len(MODEL_TIER_RECOMMENDATIONS[t]['models']) for t in ['light','medium','high','ultra']]}")


if __name__ == "__main__":
    print("=" * 50)
    test_detect_basic()
    test_model_recommendation()
    test_recommendation_table()
    print("=" * 50)
    print("硬件检测测试完成")
