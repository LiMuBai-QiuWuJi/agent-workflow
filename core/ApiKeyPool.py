import os
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(os.path.dirname(script_dir),".env")
print("加载 '.env' ",end="")
print(f"{load_dotenv(env_path)}")

class ApiKeyPool:
    """API Key 池：首次调用 get_key 时扫描 .env 与环境变量中所有含 API_KEY 的条目，
    键名统一大写建索引；之后一律走内存，不再读文件。"""

    _pool: dict[str, str] | None = None   # {大写键名: 值}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._pool is not None:
            return
        from dotenv import dotenv_values
        entries: dict[str, str] = {}
        if os.path.exists(env_path):
            entries.update(dotenv_values(env_path))   # .env 打底
        for name, value in os.environ.items():         # 环境变量覆盖同名项
            if value:
                entries[name] = value
        cls._pool = {
            name.upper(): value
            for name, value in entries.items()
            if "API_KEY" in name.upper() and value
        }

    @classmethod
    def get_key(cls, key_name: str = "") -> str:
        cls._ensure_loaded()
        query = key_name.strip().upper()
        if query:
            if query in cls._pool:                     # ① 全名命中（大小写不敏感）
                return cls._pool[query]
            matches = [(k, v) for k, v in cls._pool.items() if query in k]  # ② 模糊包含
            if len(matches) == 1:
                return matches[0][1]
            if not matches:
                raise KeyError(f"未找到含 {key_name!r} 的 API_KEY（池中现有：{list(cls._pool)}）")
            raise KeyError(f"{key_name!r} 匹配到多个 {[k for k, _ in matches]}，请写更完整的 key_name")
        if len(cls._pool) == 1:                        # ③ 空参且池中只有一个
            return next(iter(cls._pool.values()))
        raise ValueError(f"池中有 {len(cls._pool)} 个 key，请指定 key_name：{list(cls._pool)}")