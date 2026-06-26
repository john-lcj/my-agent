"""内置职场模板库 —— 一句话出成品的常用办公任务模板。

这些模板用稳定 id 种进 template_store(用户的「提示词模板」库),
用户在输入框一键插入、填几个空,Captain 就用对应 skill + 文档生成器出成品文件。
只在首次种入(seed_once),之后用户的增删改不被覆盖。
"""
from __future__ import annotations

BUILTIN_OFFICE_TEMPLATES = [
    {
        "id": "builtin-weekly-report",
        "title": "周报 → Word",
        "category": "职场",
        "content": (
            "帮我写本周周报,保存成 产物/周报.docx(用 docx_writer)。\n"
            "本周我做的事:【在这里列几条】\n"
            "下周计划:【可选】\n"
            "要求:成果导向、尽量量化(数字/百分比),把风险或卡点前置说明,结构清晰。"
        ),
    },
    {
        "id": "builtin-meeting-notes",
        "title": "会议纪要 → Word + 待办",
        "category": "职场",
        "content": (
            "把下面这段会议讨论整理成结构化会议纪要,保存成 产物/会议纪要.docx(用 docx_writer):\n"
            "【粘贴会议讨论/录音转写】\n"
            "要求:分『议题—决议—行动项』三部分;行动项写清『谁、做什么、截止时间』,"
            "最后再单独列一份待办清单方便我跟进。"
        ),
    },
    {
        "id": "builtin-report-ppt",
        "title": "项目汇报 → PPT",
        "category": "职场",
        "content": (
            "帮我做一份项目汇报 PPT,保存成 产物/项目汇报.pptx(用 pptx_writer)。\n"
            "项目:【名称】 背景/目标:【...】 当前进展:【...】 下一步:【...】 风险:【...】\n"
            "要求:封面 + 背景目标 + 进展 + 计划 + 风险 + 结尾,每页要点精炼不堆字。"
        ),
    },
    {
        "id": "builtin-business-email",
        "title": "商务邮件",
        "category": "职场",
        "content": (
            "帮我起草一封商务邮件。\n"
            "收件人/关系:【如客户、上级、供应商】 目的:【要对方做什么/告知什么】 关键信息:【...】\n"
            "要求:称呼得体、开门见山、措辞专业礼貌、结尾有明确的下一步或诉求;给中英双版可选。"
        ),
    },
    {
        "id": "builtin-monthly-summary",
        "title": "月度总结 → Word",
        "category": "职场",
        "content": (
            "帮我写月度工作总结,保存成 产物/月度总结.docx(用 docx_writer)。\n"
            "本月重点:【...】 关键成果(量化):【...】 不足与改进:【...】 下月目标:【...】\n"
            "要求:成果导向、数据说话、客观复盘,结构清晰。"
        ),
    },
    {
        "id": "builtin-data-table",
        "title": "数据整理 → Excel",
        "category": "职场",
        "content": (
            "把下面的数据整理成规范的 Excel 表,保存成 产物/数据.xlsx(用 xlsx_writer):\n"
            "【粘贴数据,或描述要哪些列、几行】\n"
            "要求:首行表头、按需排序、必要时加合计行;列名清晰。"
        ),
    },
    {
        "id": "builtin-notice",
        "title": "通知/公告",
        "category": "职场",
        "content": (
            "帮我写一份正式通知/公告。\n"
            "事由:【...】 对象:【全体/某部门】 时间地点:【...】 要求/注意事项:【...】\n"
            "要求:标题规范、正文简洁明确、落款留位,语气正式。"
        ),
    },
    {
        "id": "builtin-leave-request",
        "title": "请假/申请",
        "category": "职场",
        "content": (
            "帮我写一份请假/申请。\n"
            "类型:【请假/调休/报销/采购等】 事由:【...】 时间/金额:【...】 交接安排:【可选】\n"
            "要求:简短、礼貌、信息齐全,方便审批。"
        ),
    },
]
