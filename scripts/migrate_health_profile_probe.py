"""健康档案定制问题迁移兼容入口。

custom_questions JSON 已废弃，数据统一迁移到 health_profile 行；
本文件保留旧命令入口，实际执行 scripts/migrate_health_profile_entries.py。

用法：
    python scripts/migrate_health_profile_probe.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_health_profile_entries import main


if __name__ == "__main__":
    main()
