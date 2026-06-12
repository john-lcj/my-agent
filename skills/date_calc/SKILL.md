---
name: date_calc
description: 日期计算:加减天数、查星期几、两个日期相差多少天
trigger: 日期 几天 星期 相差 倒计时 截止
risk: READ
---

# date_calc

做日期运算时使用,免去手动数日历。

输入参数:
- `op`(string):`add` 加减天数 / `weekday` 查星期几 / `diff` 两日期相差 / `today` 今天。
- `date`(string,可选):基准日期 `YYYY-MM-DD`,默认今天。
- `days`(integer,`add` 用):加(正)或减(负)的天数。
- `to`(string,`diff` 用):目标日期 `YYYY-MM-DD`,默认今天。
