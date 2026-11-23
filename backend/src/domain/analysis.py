"""台账关联、灯组集中度测算和夜巡分流。"""

from collections import Counter
from datetime import date
from fractions import Fraction
from itertools import accumulate

from .spec import SPEC


_REGISTER, _INCIDENT = SPEC["fields"][0]["options"]
_DISPATCH, _OBSERVE, _ARCHIVE = SPEC["modes"]
_SITE_COLUMNS = (
    ("site_id", "灯组编号"), ("district", "片区"), ("site_name", "台账点位"),
    ("fixture_count", "在册灯具数"), ("incident_count", "工单数"),
)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空，请填写文本。")
    return value.strip()


def _date(value, label):
    if isinstance(value, str):
        try:
            if date.fromisoformat(value).isoformat() == value:
                return value
        except ValueError:
            pass
    raise ValueError(f"{label}须使用有效的 YYYY-MM-DD 日期。")


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def validate_rows(rows):
    """校验全量台账和工单，返回去除空字段的独立记录。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("灯组与工单明细为空，请导入灯组台账。")

    sites = set()
    incident_ids = set()
    incidents = []
    records = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条记录格式有误。")
        kind = row.get("record_type")
        site_id = _text(row.get("site_id"), f"第 {index} 条记录的灯组编号").upper()
        record = {"record_type": kind, "site_id": site_id}
        if kind == _REGISTER:
            if site_id in sites:
                raise ValueError(f"灯组编号「{site_id}」在台账中重复。")
            if any(not _blank(row.get(key)) for key in ("incident_id", "report_date")):
                raise ValueError(f"灯组「{site_id}」的台账行须留空工单号和报修日期。")
            fixtures = row.get("fixture_count")
            if type(fixtures) is not int or fixtures < 1:
                raise ValueError(f"灯组「{site_id}」的在册灯具数须为正整数。")
            record.update(
                district=_text(row.get("district"), f"灯组「{site_id}」的台账片区"),
                site_name=_text(row.get("site_name"), f"灯组「{site_id}」的台账点位"),
                fixture_count=fixtures,
            )
            sites.add(site_id)
        elif kind == _INCIDENT:
            incident_id = _text(row.get("incident_id"), f"第 {index} 条记录的暗区工单号").upper()
            if incident_id in incident_ids:
                raise ValueError(f"暗区工单号「{incident_id}」重复。")
            if any(not _blank(row.get(key)) for key in ("district", "site_name", "fixture_count")):
                raise ValueError(f"工单「{incident_id}」的工单行须留空片区、点位和灯具数。")
            record.update(
                incident_id=incident_id,
                report_date=_date(row.get("report_date"), f"工单「{incident_id}」的报修日期"),
            )
            incident_ids.add(incident_id)
            incidents.append(record)
        else:
            raise ValueError(f"第 {index} 条记录的记录类型须为「{_REGISTER}」或「{_INCIDENT}」。")
        records.append(record)

    if not sites:
        raise ValueError("灯组台账为空，请为在册灯组提供台账行。")
    for incident in incidents:
        if incident["site_id"] not in sites:
            raise ValueError(f"工单「{incident['incident_id']}」未匹配灯组「{incident['site_id']}」，请补录或更正台账。")
    return records


def _parameters(params):
    if not isinstance(params, dict):
        raise ValueError("集中度测算参数格式有误。")
    options = {}
    for field in SPEC["params"]:
        key, label, kind = field["key"], field["label"], field["type"]
        value = params.get(key, field["default"])
        if kind in ("int", "number"):
            types = (int,) if kind == "int" else (int, float)
            if type(value) not in types or not field["min"] <= value <= field["max"]:
                raise ValueError(f"「{label}」须在 {field['min']} 至 {field['max']} 之间，并符合字段类型。")
        elif _blank(value):
            value = ""
        elif kind == "date":
            value = _date(value, label)
        else:
            value = _text(value, label)
        options[key] = value
    if options["end_date"] and options["start_date"] > options["end_date"]:
        raise ValueError("报修起日须早于或等于报修止日。")
    return options


def _table(title, columns, rows):
    return {"title": title, "columns": [{"key": key, "label": label} for key, label in columns], "rows": rows}


def _curve(title, counts, total):
    points = []
    if total:
        cumulative = list(accumulate(counts, initial=0))
        for percent in range(0, 101, 5):
            rank, fraction = divmod(percent * len(counts), 100)
            # Interpolate within the rank so the shared line chart has evenly spaced x values.
            value = 100 * cumulative[rank]
            if fraction:
                value += fraction * counts[rank]
            points.append({"label": f"{percent}%", "value": round(value / total, 6)})
    return {"title": title, "kind": "line", "series": points}


def _triage(ranked, min_incidents, min_rate):
    queue = []
    threshold = Fraction(str(min_rate))
    for site in ranked:
        count = site["incident_count"]
        rate = Fraction(100 * count, site["fixture_count"])
        if count >= min_incidents and rate >= threshold:
            priority, action = 0, _DISPATCH
            next_step = "对照本组工单，夜间逐盏核查并回填灯杆编号和熄灯时段。"
        elif count:
            priority, action = 1, _OBSERVE
            deficit = f"距起派单数还差 {min_incidents - count} 单" if count < min_incidents else "每百盏报修数未达门槛"
            next_step = f"{deficit}，下个周期用新增工单复核。"
        else:
            priority, action = 2, _ARCHIVE
            next_step = "保留在册点位，纳入下一周期分母。"
        key = (priority, -rate, -count, site["site_id"])
        queue.append((key, {**site, "rate_per_100": round(float(rate), 2), "action": action, "next_step": next_step}))
    return [site for _, site in sorted(queue)]


def analyze(rows, normalized_params):
    records = validate_rows(rows)
    options = _parameters(normalized_params)
    district, start, end = (options[key] for key in ("district_scope", "start_date", "end_date"))
    sites = {
        row["site_id"]: row for row in records
        if row["record_type"] == _REGISTER and (not district or row["district"] == district)
    }
    if not sites:
        raise ValueError(f"台账中没有「{district}」的灯组，请检查片区名称。")
    incidents = sorted(
        (row for row in records if row["record_type"] == _INCIDENT and row["site_id"] in sites
         and (not start or row["report_date"] >= start) and (not end or row["report_date"] <= end)),
        key=lambda row: (row["report_date"], row["incident_id"]),
    )
    counts = Counter(row["site_id"] for row in incidents)
    ranked = sorted(sites.values(), key=lambda site: (-counts[site["site_id"]], site["site_id"]))
    ranked = [
        {**{key: site[key] for key, _ in _SITE_COLUMNS[:-1]}, "incident_count": counts[site["site_id"]]}
        for site in ranked
    ]
    descending = [site["incident_count"] for site in ranked]
    ascending = descending[::-1]
    n, total = len(ranked), len(incidents)
    zero_count = n - len(counts)
    top_percent = options["top_percent"]
    top_count = (n * top_percent + 99) // 100
    top_incidents = sum(descending[:top_count])
    gini = top_share = None
    if total:
        numerator = sum((2 * rank - n - 1) * count for rank, count in enumerate(ascending, start=1))
        gini = round(numerator / (n * total), 6)
        top_share = round(100 * top_incidents / total, 6)

    pareto = [
        {**site, "rank": rank, "cumulative_count": cumulative,
         "cumulative_share_pct": round(100 * cumulative / total, 6) if total else None,
         "in_top": "是" if rank <= top_count else "否"}
        for rank, (site, cumulative) in enumerate(zip(ranked, accumulate(descending)), start=1)
    ]
    queue = _triage(ranked, options["min_incidents"], options["min_rate"])
    dispatch_count = sum(site["action"] == _DISPATCH for site in queue)
    trace = [
        {"incident_id": row["incident_id"], "report_date": row["report_date"], "site_id": row["site_id"],
         "site_name": sites[row["site_id"]]["site_name"]}
        for row in incidents
    ]
    if dispatch_count:
        first = queue[0]
        next_step = f"优先将灯组 {first['site_id']}「{first['site_name']}」及对应工单交给夜巡，再登记现场结果。"
    elif total:
        next_step = "本期点位均未同时达到两个夜巡门槛。保留有工单的点位，待下期工单汇入后复核。"
    else:
        next_step = "本期无报修工单。按台账归档，并在下一周期复核新增工单。"

    return {
        "state": "warning" if dispatch_count else "ok",
        "headline": f"{total} 张暗区工单分布在 {len(counts)}/{n} 个灯组，建议夜巡 {dispatch_count} 组。",
        "note": (f"{district or '全部片区'} · 报修起日 {start or '不限'} · 报修止日 {end or '不限'}。"
                 f"零报修灯组 {zero_count} 组，均计入灯组数。"),
        "metrics": [
            {"label": "在册灯组", "value": n, "detail": f"在册灯具 {sum(site['fixture_count'] for site in ranked)} 盏"},
            {"label": "纳入工单", "value": total, "detail": f"涉及 {len(counts)} 个灯组"},
            {"label": "零报修灯组", "value": zero_count, "detail": f"占在册灯组 {zero_count / n:.1%}"},
            {"label": "基尼系数", "value": gini, "detail": "按各灯组工单数测算" if total else "总工单数为零，基尼未定义"},
            {"label": "头部工单份额（%）", "value": top_share, "detail": f"头部 {top_percent}% 取 {top_count} 组，共 {top_incidents} 单"},
            {"label": "建议夜巡", "value": dispatch_count, "detail": f"至少 {options['min_incidents']} 单且每百盏至少 {options['min_rate']:g} 单"},
        ],
        "tables": [
            _table("灯组工单帕累托排名", (("rank", "排名"),) + _SITE_COLUMNS + (
                ("cumulative_count", "累计工单数"), ("cumulative_share_pct", "累计工单占比（%）"), ("in_top", "头部灯组"),
            ), pareto),
            _table("灯组夜巡分流", _SITE_COLUMNS + (
                ("rate_per_100", "每百盏报修数"), ("action", "建议处置"), ("next_step", "交接事项"),
            ), queue),
            _table("纳入工单明细", (
                ("incident_id", "暗区工单号"), ("report_date", "报修日期"), ("site_id", "灯组编号"), ("site_name", "台账点位"),
            ), trace),
        ],
        "charts": [
            _curve("洛伦兹曲线 · 累计工单占比（%）", ascending, total),
            _curve("帕累托曲线 · 累计工单占比（%）", descending, total),
        ],
        "sections": [{"title": "夜巡交接与复核", "text": next_step}],
    }
