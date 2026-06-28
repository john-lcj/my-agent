"""captain activate / captain license 命令行工具。

用法:
  captain activate CAPT-PRO-XXXX-XXXX-XXXX
  captain activate CAPT-PRO-XXXX-XXXX-XXXX --email you@example.com
  captain license         # 查看当前授权状态
"""
from __future__ import annotations
import sys


def cmd_activate(args: list[str]) -> None:
    if not args:
        print("用法: captain activate <授权码> [--email <邮箱>]")
        sys.exit(1)
    key = args[0]
    email = ""
    if "--email" in args:
        idx = args.index("--email")
        if idx + 1 < len(args):
            email = args[idx + 1]

    from license_client.client import activate
    print(f"正在激活 {key} ...")
    status = activate(key, email)
    if status.valid:
        print(f"✅ 激活成功！套餐: {status.plan.upper()}"
              + (f"，有效期剩余 {status.days_left()} 天" if status.days_left() is not None else ""))
    else:
        print(f"❌ 激活失败: {status.error}")
        sys.exit(1)


def cmd_license_status() -> None:
    from license_client.client import check_license
    status = check_license()
    print(f"套餐:   {status.plan.upper()}")
    print(f"有效:   {'是' if status.valid else '否'}")
    if status.days_left() is not None:
        print(f"剩余:   {status.days_left()} 天")
    if status.offline:
        print("模式:   离线缓存")
    if status.error:
        print(f"提示:   {status.error}")


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("用法: captain activate <授权码>  |  captain license")
        return
    sub = argv[0].lower()
    if sub == "activate":
        cmd_activate(argv[1:])
    elif sub in ("license", "status"):
        cmd_license_status()
    else:
        print(f"未知子命令: {sub}")
        sys.exit(1)


if __name__ == "__main__":
    main()
