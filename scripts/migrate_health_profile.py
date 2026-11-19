"""健康档案表迁移兼容入口。

新库与旧库都统一走 scripts/migrate_health_profile_entries.py：
- 空库：创建行式 health_profile；
- 旧 1:1 JSON 库：自动迁移成行式；
- 已迁移库：幂等跳过。

用法：
    python scripts/migrate_health_profile.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_health_profile_entries import main


if __name__ == "__main__":
    main()
