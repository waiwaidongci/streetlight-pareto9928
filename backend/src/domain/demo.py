"""临汀市虚拟路灯台账与已归并的暗区事件。"""


_SITES = (
    ("滨河片区", "柳汀大道北段", 32, (14, 14, 15, 16, 17, 18, 19, 20)),
    ("老城片区", "东门巷", 5, (14, 16, 17, 19, 20)),
    ("滨河片区", "汀桥路公交站段", 24, (15, 17, 18, 20)),
    ("滨河片区", "长堤辅道", 3, (16, 20)),
    ("老城片区", "西仓里路口", 2, (19,)),
    ("滨河片区", "渡口支路", 9, ()),
    ("滨河片区", "桐浦堤下通道", 6, ()),
    ("老城片区", "埠头街南段", 14, ()),
    ("老城片区", "石平码头广场路", 11, ()),
    ("老城片区", "钟楼西街", 17, ()),
)


def demo_rows() -> list[dict]:
    rows = []
    for number, (district, site, fixtures, days) in enumerate(_SITES, start=1):
        site_id = f"LH-{number:02d}"
        rows.append({
            "record_type": "灯组台账", "site_id": site_id, "district": district,
            "site_name": site, "fixture_count": fixtures, "incident_id": None, "report_date": None,
        })
        for sequence, day in enumerate(days, start=1):
            rows.append({
                "record_type": "暗区工单", "site_id": site_id, "district": None,
                "site_name": None, "fixture_count": None,
                "incident_id": f"LT-2611{day}-{number:02d}-{sequence:02d}",
                "report_date": f"2026-11-{day}",
            })
    return rows
