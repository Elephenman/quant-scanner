"""
因子自动发现和注册
只需在 factors/ 目录下新建 .py 文件，继承 FactorBase，重启即可自动加载
"""

import importlib
import os
from factors.base import FactorBase, FactorRegistry


def discover_factors():
    """自动发现 factors/ 目录下所有因子模块并注册"""
    factors_dir = os.path.dirname(__file__)
    loaded = []

    for filename in os.listdir(factors_dir):
        if filename.startswith("_") or not filename.endswith(".py"):
            continue
        module_name = filename[:-3]
        try:
            module = importlib.import_module(f"factors.{module_name}")
            # 找到模块中所有 FactorBase 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, FactorBase)
                        and attr is not FactorBase
                        and attr.name):
                    instance = attr()
                    FactorRegistry.register(instance)
                    loaded.append(instance.name)
        except Exception as e:
            print(f"[WARN] 加载因子 {module_name} 失败: {e}")

    return loaded


def get_all_factors():
    """获取所有已注册因子"""
    return FactorRegistry.all_factors()


def get_factors_by_category():
    """按分类获取因子"""
    return FactorRegistry.by_category()


if __name__ == "__main__":
    loaded = discover_factors()
    print(f"已加载 {len(loaded)} 个因子: {loaded}")
    for name, factor in FactorRegistry.all_factors().items():
        print(f"  {name} ({factor.category.value}) - {factor.description}")
