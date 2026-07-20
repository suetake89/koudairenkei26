from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import pulp
except ImportError:  # pragma: no cover
    pulp = None


DAYS_PER_WEEK = 7
START_HOUR = 8
END_HOUR = 22
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]
UNIT_OPTIONS = {
    "1時間": 60,
    "30分": 30,
    "20分": 20,
    "15分": 15,
    "10分": 10,
    "5分": 5,
}
SUBJECTS = ["国語", "英語", "数学", "社会", "理科"]
SUBJECT_CLASS = {
    "数学": "subj-math",
    "英語": "subj-english",
    "国語": "subj-japanese",
    "理科": "subj-science",
    "社会": "subj-social",
}
STATUS_LABELS = {
    "Optimal": "最適解",
    "Infeasible": "実行不可能",
    "Not Solved": "未解決",
    "Unbounded": "上限なし",
    "Undefined": "未定義",
}
STEP_KEYS = [
    "required_study",
    "motivation",
    "week",
    "subjects",
]


def reset_steps_after(step_key: str) -> None:
    start = STEP_KEYS.index(step_key) + 1
    for key in STEP_KEYS[start:]:
        st.session_state[f"toggle_{key}"] = False


@dataclass(frozen=True)
class FormulaBlock:
    key: str
    priority: int
    label: str
    requires: tuple[str, ...]
    formulas: tuple[str, ...]
    description: str


FORMULA_BLOCKS = {
    "allocation": FormulaBlock(
        key="allocation",
        priority=1,
        label="勉強・休憩・自由時間",
        requires=(),
        description="固定予定以外の時間では、勉強か休憩のどちらかを選ぶ。",
        formulas=(
            r"T=\{1,\ldots,28\}",
            r"A_t\in\{0,1\}",
            r"Z_t,R_t\in\{0,1\}",
            r"Z_t+R_t=A_t\quad(t\in T)",
            r"\max\sum_{t\in T}Z_t",
        ),
    ),
    "required_study": FormulaBlock(
        key="required_study",
        priority=2,
        label="勉強時間の下限・上限",
        requires=("allocation",),
        description="勉強時間が少なすぎず、多すぎないようにする。",
        formulas=(
            r"H^{\min}\le\sum_{t\in T}Z_t\le H^{\max}",
        ),
    ),
    "motivation": FormulaBlock(
        key="motivation",
        priority=3,
        label="モチベーション",
        requires=("allocation",),
        description="勉強すると下がり、休憩すると回復する状態を入れる。",
        formulas=(
            r"M_t\in[0,100]",
            r"M_1=100",
            r"M_{t+1}=\min\{100,\ M_t-aZ_t+bR_t+G_t\}",
            r"W_t=M_tZ_t",
            r"\max\sum_{t\in T}W_t",
        ),
    ),
    "week": FormulaBlock(
        key="week",
        priority=4,
        label="7日間化",
        requires=("allocation",),
        description="1日モデルを月曜から日曜までの週間計画に広げる。",
        formulas=(
            r"D=\{1,\ldots,7\}",
            r"Z_{dt}+R_{dt}=A_{dt}\quad(d\in D,t\in T)",
            r"\sum_{d\in D}\sum_{t\in T}Z_{dt}\ge H",
        ),
    ),
    "subjects": FormulaBlock(
        key="subjects",
        priority=5,
        label="科目・科目別最低時間",
        requires=("week",),
        description="勉強する時間に5科目のうち1つを割り当て、科目ごとの最低勉強時間を満たす。",
        formulas=(
            r"K=\{\text{数学},\text{英語},\text{国語},\text{理科},\text{社会}\}",
            r"X_{dtj}\in\{0,1\}\quad(d\in D,t\in T,j\in K)",
            r"\sum_{j\in K}X_{dtj}=Z_{dt}\quad(d\in D,t\in T)",
            r"\sum_{d\in D}\sum_{t\in T}X_{dtj}\ge H_j\quad(j\in K)",
        ),
    ),
}


def slots_per_day(slot_minutes: int) -> int:
    return (END_HOUR - START_HOUR) * 60 // slot_minutes


def time_to_slot(hour: int, minute: int, slot_minutes: int) -> int:
    return ((hour - START_HOUR) * 60 + minute) // slot_minutes


def slot_to_time(slot: int, slot_minutes: int) -> str:
    minutes = START_HOUR * 60 + slot * slot_minutes
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def default_fixed_grid(slot_minutes: int) -> list[list[bool]]:
    slots = slots_per_day(slot_minutes)
    grid = [[False] * slots for _ in range(DAYS_PER_WEEK)]
    for day_index in range(DAYS_PER_WEEK):
        for slot in default_fixed_slots(day_index, slot_minutes):
            grid[day_index][slot] = True
    return grid


def default_fixed_slots(day_index: int, slot_minutes: int) -> set[int]:
    fixed = set()
    weekday = day_index % 7
    if weekday < 5:
        fixed.update(range(time_to_slot(8, 30, slot_minutes), time_to_slot(15, 30, slot_minutes)))
    fixed.update(range(time_to_slot(18, 0, slot_minutes), time_to_slot(19, 0, slot_minutes)))
    return fixed


def fixed_slots(day_index: int, slot_minutes: int, params: dict[str, float] | None = None) -> set[int]:
    if params and params.get("fixed_grid") is not None:
        grid = params["fixed_grid"]
        if day_index < len(grid):
            return {i for i, is_fixed in enumerate(grid[day_index]) if is_fixed}
    return default_fixed_slots(day_index, slot_minutes)


def detect_fixed_blocks(fixed_grid: list[list[bool]], slot_minutes: int) -> list[dict]:
    blocks = []
    for day_index, row in enumerate(fixed_grid):
        start = None
        for slot, is_fixed in enumerate(row + [False]):
            if is_fixed and start is None:
                start = slot
            elif not is_fixed and start is not None:
                end = slot - 1
                block_id = f"{day_index}:{start}:{end}"
                blocks.append(
                    {
                        "id": block_id,
                        "day": day_index,
                        "weekday": WEEKDAYS[day_index],
                        "start": start,
                        "end": end,
                        "label": f"{WEEKDAYS[day_index]} {slot_to_time(start, slot_minutes)}-{slot_to_time(end + 1, slot_minutes)}",
                    }
                )
                start = None
    return blocks


def recovery_slots(day_index: int, params: dict[str, float], enabled: set[str]) -> dict[int, float]:
    if "motivation" not in enabled:
        return {}
    slot_minutes = int(params["slot_minutes"])
    recovery = {}
    block_recoveries = params.get("block_recoveries") or {}
    for block in detect_fixed_blocks(params.get("fixed_grid") or default_fixed_grid(slot_minutes), slot_minutes):
        if block["day"] == day_index:
            recovery[block["end"]] = block_recoveries.get(block["id"], 0)
    return recovery


def resolve_enabled(raw_enabled: dict[str, bool]) -> set[str]:
    enabled = {"allocation"}
    for key, is_on in raw_enabled.items():
        if is_on:
            enabled.add(key)
    changed = True
    while changed:
        changed = False
        for key in list(enabled):
            for dep in FORMULA_BLOCKS[key].requires:
                if dep not in enabled:
                    enabled.add(dep)
                    changed = True
    return enabled


def build_sample_schedule(enabled: set[str], params: dict[str, float] | None = None) -> list[dict]:
    params = params or {"slot_minutes": 30}
    slot_minutes = int(params["slot_minutes"])
    slots = slots_per_day(slot_minutes)
    days = DAYS_PER_WEEK if "week" in enabled else 1
    rows = []
    for d in range(days):
        states = ["rest"] * slots
        subjects = [None] * slots
        for t in fixed_slots(d, slot_minutes, params):
            states[t] = "fixed"
        if d % 7 < 5:
            pattern = [
                (time_to_slot(8, 0, slot_minutes), time_to_slot(8, 30, slot_minutes) - 1),
                (time_to_slot(15, 30, slot_minutes), time_to_slot(17, 0, slot_minutes) - 1),
                (time_to_slot(19, 0, slot_minutes), time_to_slot(20, 30, slot_minutes) - 1),
            ]
        else:
            pattern = [
                (time_to_slot(9, 0, slot_minutes), time_to_slot(11, 0, slot_minutes) - 1),
                (time_to_slot(13, 0, slot_minutes), time_to_slot(15, 0, slot_minutes) - 1),
                (time_to_slot(19, 0, slot_minutes), time_to_slot(20, 30, slot_minutes) - 1),
            ]
        for idx, (start, end) in enumerate(pattern):
            for t in range(start, end + 1):
                if states[t] != "fixed":
                    states[t] = "study"
                    subjects[t] = SUBJECTS[(d + idx) % len(SUBJECTS)] if "subjects" in enabled else None
        rows.append({"day": d + 1, "weekday": WEEKDAYS[d % 7], "states": states, "subjects": subjects})
    return rows


def solve_schedule(enabled: set[str], params: dict[str, float]) -> tuple[list[dict], str]:
    slot_minutes = int(params["slot_minutes"])
    slots = slots_per_day(slot_minutes)
    if pulp is None:
        return build_sample_schedule(enabled, params), "PuLP が見つからないため、サンプル表示に切り替えました。"

    days = DAYS_PER_WEEK if "week" in enabled else 1
    model = pulp.LpProblem("study_planning", pulp.LpMaximize)
    z = pulp.LpVariable.dicts("Z", (range(days), range(slots)), 0, 1, cat="Binary")
    r = pulp.LpVariable.dicts("R", (range(days), range(slots)), 0, 1, cat="Binary")

    m = w = None
    if "motivation" in enabled:
        m = pulp.LpVariable.dicts("M", (range(days), range(slots)), 0, 100, cat="Continuous")
        w = pulp.LpVariable.dicts("W", (range(days), range(slots)), 0, 100, cat="Continuous")
    x = None
    if "subjects" in enabled:
        x = pulp.LpVariable.dicts("X", (range(days), range(slots), SUBJECTS), 0, 1, cat="Binary")

    for d in range(days):
        fixed = fixed_slots(d, slot_minutes, params)
        for t in range(slots):
            available = 0 if t in fixed else 1
            model += z[d][t] + r[d][t] == available

            if x is not None:
                model += pulp.lpSum(x[d][t][j] for j in SUBJECTS) == z[d][t]

            if w is not None and m is not None:
                model += w[d][t] <= m[d][t]
                model += w[d][t] <= 100 * z[d][t]
                model += w[d][t] >= m[d][t] - 100 * (1 - z[d][t])

        if m is not None:
            model += m[d][0] == 100

            recoveries = recovery_slots(d, params, enabled)
            for t in range(slots - 1):
                raw = m[d][t] - params["a"] * z[d][t] + params["b"] * r[d][t] + recoveries.get(t, 0)
                model += m[d][t + 1] <= raw

    max_available = sum(slots - len(fixed_slots(d, slot_minutes, params)) for d in range(days))
    if "required_study" in enabled and params["h_min"] > max_available:
        max_hours = max_available * slot_minutes / 60
        requested_hours = params["h_min"] * slot_minutes / 60
        return (
            build_sample_schedule(enabled, params),
            f"PuLP の解が不可能です。勉強時間の下限が {requested_hours:.1f} 時間ですが、固定予定を除いた自由時間は最大 {max_hours:.1f} 時間です。",
        )

    if "required_study" in enabled:
        study_total = pulp.lpSum(z[d][t] for d in range(days) for t in range(slots))
        model += study_total >= params["h_min"]
        model += study_total <= min(params["h_max"], max_available)

    if x is not None and "subjects" in enabled:
        for subject in SUBJECTS:
            required = params["subject_hours"][subject]
            model += pulp.lpSum(x[d][t][subject] for d in range(days) for t in range(slots)) >= required

    if w is not None:
        objective = pulp.lpSum(w[d][t] for d in range(days) for t in range(slots))
    else:
        objective = pulp.lpSum(z[d][t] for d in range(days) for t in range(slots))

    if x is not None:
        for d in range(days):
            for t in range(slots):
                hour = START_HOUR + (t * slot_minutes) / 60
                if hour >= 19:
                    objective += 2 * x[d][t]["社会"] + 2 * x[d][t]["国語"]
                if 15 <= hour < 18:
                    objective += 2 * x[d][t]["数学"] + 1 * x[d][t]["英語"]
    objective += 0.001 * pulp.lpSum(r[d][t] for d in range(days) for t in range(slots))
    model += objective

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=int(params.get("time_limit", 10)), gapRel=0.03)
    status = model.solve(solver)
    status_name = pulp.LpStatus[status]
    if status_name != "Optimal":
        label = STATUS_LABELS.get(status_name, status_name)
        return build_sample_schedule(enabled, params), f"PuLP の解が「{label}」だったため、サンプル表示に切り替えました。"

    rows = []
    for d in range(days):
        states = []
        subjects = []
        fixed = fixed_slots(d, slot_minutes, params)
        for t in range(slots):
            if t in fixed:
                states.append("fixed")
                subjects.append(None)
            elif pulp.value(z[d][t]) and pulp.value(z[d][t]) > 0.5:
                states.append("study")
                if x is not None:
                    chosen = max(SUBJECTS, key=lambda j: pulp.value(x[d][t][j]) or 0)
                    subjects.append(chosen)
                else:
                    subjects.append(None)
            else:
                states.append("rest")
                subjects.append(None)
        rows.append({
            "day": d + 1,
            "weekday": WEEKDAYS[d % 7],
            "states": states,
            "subjects": subjects,
        })
    return rows, "PuLP: 最適解が得られました。"


def count_study(schedule: list[dict]) -> int:
    return sum(row["states"].count("study") for row in schedule)


def count_subjects(schedule: list[dict]) -> dict[str, int]:
    counts = {subject: 0 for subject in SUBJECTS}
    for row in schedule:
        for subject in row.get("subjects", []):
            if subject in counts:
                counts[subject] += 1
    return counts


def render_formula_block(block: FormulaBlock) -> None:
    with st.expander(f"{block.priority}. {block.label}", expanded=True):
        st.caption(block.description)
        for formula in block.formulas:
            st.latex(formula)


FormulaLine = tuple[str, str]


def current_model_formulas(enabled: set[str]) -> list[tuple[str, list[FormulaLine]]]:
    is_week = "week" in enabled
    has_motivation = "motivation" in enabled
    has_subjects = "subjects" in enabled

    time_set = r"D=\{1,\ldots,7\},\quad T=\{1,\ldots,|T|\}" if is_week else r"T=\{1,\ldots,|T|\}"
    idx = r"d\in D,\ t\in T" if is_week else r"t\in T"
    z = "Z_{dt}" if is_week else "Z_t"
    r_var = "R_{dt}" if is_week else "R_t"
    a = "A_{dt}" if is_week else "A_t"
    m = "M_{dt}" if is_week else "M_t"
    w = "W_{dt}" if is_week else "W_t"
    g = "G_{dt}" if is_week else "G_t"
    next_m = "M_{d,t+1}" if is_week else "M_{t+1}"
    sum_t_z = r"\sum_{d\in D}\sum_{t\in T}Z_{dt}" if is_week else r"\sum_{t\in T}Z_t"
    sum_t_w = r"\sum_{d\in D}\sum_{t\in T}W_{dt}" if is_week else r"\sum_{t\in T}W_t"

    variables: list[FormulaLine] = [
        (time_set, "計画で使う日と時刻の範囲。"),
        (rf"A_{{{'dt' if is_week else 't'}}}\in\{{0,1\}}", "その時間が自由時間なら1、固定予定なら0。"),
        (rf"{z},{r_var}\in\{{0,1\}}\quad({idx})", "勉強するか、休憩するかを表す0-1変数。"),
    ]
    if has_motivation:
        variables.extend([
            (rf"{m}\in[0,100]\quad({idx})", "その時間のモチベーション。"),
            (rf"{w}\ge0\quad({idx})", "モチベーションを考慮した勉強の評価値。"),
        ])
    if has_subjects:
        variables.extend([
            (r"K=\{\text{国語},\text{英語},\text{数学},\text{社会},\text{理科}\}", "扱う科目の集合。"),
            (r"X_{dtj}\in\{0,1\}\quad(d\in D,\ t\in T,\ j\in K)", "その時間に科目jを勉強するなら1。"),
        ])

    objective = [
        (rf"\max\ {sum_t_w}", "モチベーションが高い時間の勉強を高く評価する。")
        if has_motivation
        else (rf"\max\ {sum_t_z}", "勉強コマ数をできるだけ多くする。")
    ]

    constraints: list[tuple[str, list[FormulaLine]]] = []
    constraints.append((
        "制約1：自由時間の割当て",
        [(rf"{z}+{r_var}={a}\quad({idx})", "自由時間なら勉強か休憩、固定予定ならどちらもできない。")],
    ))
    if "required_study" in enabled:
        constraints.append((
            "制約2：勉強時間の下限・上限",
            [(rf"H^{{\min}}\le {sum_t_z}\le H^{{\max}}", "勉強時間が少なすぎず、多すぎないようにする。")],
        ))
    if has_motivation:
        initial = r"M_{d,1}=100\quad(d\in D)" if is_week else r"M_1=100"
        constraints.append((
            "制約3：モチベーション",
            [
                (initial, "最初のモチベーションを100から始める。"),
                (rf"{next_m}=\min\{{100,\ {m}-a{z}+b{r_var}+{g}\}}", "勉強で下がり、休憩や固定予定後の回復で上がる。"),
                (rf"{w}={m}{z}\quad({idx})", "勉強しない時間の評価は0、勉強する時間はモチベーション分だけ評価する。"),
            ],
        ))
    if is_week:
        constraints.append((
            "制約4：7日間化",
            [(r"d\in D=\{1,\ldots,7\}", "1日モデルを月曜から日曜までに広げる。")],
        ))
    if has_subjects:
        constraints.append((
            "制約5：科目・科目別最低時間",
            [
                (r"\sum_{j\in K}X_{dtj}=Z_{dt}\quad(d\in D,\ t\in T)", "勉強する時間には、必ず1つの科目を選ぶ。"),
                (r"\sum_{d\in D}\sum_{t\in T}X_{dtj}\ge H_j\quad(j\in K)", "各科目で最低限必要な勉強コマ数を満たす。"),
            ],
        ))

    execution_notes: list[tuple[str, list[FormulaLine]]] = []
    if has_motivation:
        execution_notes.append((
            "実行上の数式の補足1",
            [
                (rf"{w}={m}{z}\quad({idx})", "PuLPではこの掛け算を直接使わず、以下の3つの線形制約に分割する。"),
                (rf"0\le {w}\quad({idx})", "評価値は負にならないようにする。"),
                (
                    rf"{w}\le {m}\quad({idx})",
                    rf"{z}=0 のときは強い制限にならない。{z}=1 のときは評価値がモチベーションを超えないようにする。",
                ),
                (
                    rf"{w}\le 100{z}\quad({idx})",
                    rf"{z}=0 のとき {w} ≤ 0 なので、0 ≤ {w} と合わせて {w}=0 になる。{z}=1 のときは {w} ≤ 100 だけになる。",
                ),
                (
                    rf"{w}\ge {m}-100(1-{z})\quad({idx})",
                    rf"{z}=0 のときは強い制限にならない。{z}=1 のとき {w} ≥ {m} となり、{w} ≤ {m} と合わせて {w}={m} になる。",
                ),
            ],
        ))
        execution_notes.append((
            "実行上の数式の補足2",
            [
                (
                    rf"{next_m}\le\min\{{100,\ {m}-a{z}+b{r_var}+{g}\}}",
                    "PuLPではこのminを直接使わず、以下の2つの上限制約に分割する。",
                ),
                (rf"{next_m}\le 100", "1つ目の上限制約。モチベーションの上限を100にする。"),
                (
                    rf"{next_m}\le {m}-a{z}+b{r_var}+{g}",
                    "2つ目の上限制約。勉強・休憩・固定予定後の回復による変化を表す。",
                ),
            ],
        ))

    return [("変数", variables), ("目的関数", objective), *constraints, *execution_notes]


def render_current_model_formulas(enabled: set[str]) -> None:
    for title, formula_lines in current_model_formulas(enabled):
        with st.expander(title, expanded=True):
            for formula, explanation in formula_lines:
                st.latex(formula)
                st.caption(explanation)


def render_schedule(schedule: list[dict], show_subjects: bool, slot_minutes: int) -> None:
    slots = slots_per_day(slot_minutes)
    min_cell_width = 18 if slots <= 28 else 10 if slots <= 84 else 5
    css = """
    <style>
      .schedule-wrap { display: grid; gap: 7px; margin-top: 0.5rem; }
      .schedule-row { display: grid; grid-template-columns: 64px 1fr; gap: 8px; align-items: center; }
      .schedule-label { color: #666; font-variant-numeric: tabular-nums; white-space: nowrap; }
      .schedule-track { display: grid; grid-template-columns: repeat(VAR_SLOTS, minmax(VAR_CELL_WIDTHpx, 1fr)); gap: 2px; }
      .schedule-cell { height: 20px; border-radius: 3px; background: #f0b88f; }
      .schedule-cell.study { background: #58aaf5; }
      .schedule-cell.fixed { background: #d9d9d9; }
      .schedule-cell.subj-math { background: #4f8ef7; }
      .schedule-cell.subj-english { background: #48a868; }
      .schedule-cell.subj-japanese { background: #b277d2; }
      .schedule-cell.subj-science { background: #f2a541; }
      .schedule-cell.subj-social { background: #d65f5f; }
      .legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 8px 0 2px; color: #666; }
      .legend-item { display: inline-flex; align-items: center; gap: 6px; }
      .swatch { width: 16px; height: 12px; border-radius: 2px; display: inline-block; }
      .swatch.study { background: #58aaf5; }
      .swatch.rest { background: #f0b88f; }
      .swatch.fixed { background: #d9d9d9; }
      .swatch.subj-math { background: #4f8ef7; }
      .swatch.subj-english { background: #48a868; }
      .swatch.subj-japanese { background: #b277d2; }
      .swatch.subj-science { background: #f2a541; }
      .swatch.subj-social { background: #d65f5f; }
      .axis-row { display: grid; grid-template-columns: 64px 1fr; gap: 8px; align-items: center; color: #666; }
      .axis-track { display: grid; grid-template-columns: repeat(7, 1fr); font-variant-numeric: tabular-nums; }
    </style>
    """.replace("VAR_SLOTS", str(slots)).replace("VAR_CELL_WIDTH", str(min_cell_width))
    html = [css, '<div class="schedule-wrap">']
    html.append(
        '<div class="axis-row"><div>時刻</div><div class="axis-track">'
        "<span>8</span><span>10</span><span>12</span><span>14</span>"
        "<span>16</span><span>18</span><span>20</span>"
        "</div></div>"
    )
    for row in schedule:
        label = "1日" if len(schedule) == 1 else f"D{row['day']}({row['weekday']})"
        cells = []
        for state, subject in zip(row["states"], row.get("subjects", [None] * slots)):
            klass = state
            if show_subjects and subject:
                klass = f"study {SUBJECT_CLASS[subject]}"
            cells.append(f'<span class="schedule-cell {klass}"></span>')
        html.append(f'<div class="schedule-row"><div class="schedule-label">{label}</div><div class="schedule-track">{"".join(cells)}</div></div>')
    html.append("</div>")
    html.append(
        '<div class="legend">'
        '<span class="legend-item"><span class="swatch rest"></span>休憩</span>'
        '<span class="legend-item"><span class="swatch fixed"></span>固定予定</span>'
    )
    if show_subjects:
        for subject in SUBJECTS:
            html.append(f'<span class="legend-item" translate="no"><span class="swatch {SUBJECT_CLASS[subject]}"></span>{subject}</span>')
    else:
        html.append('<span class="legend-item"><span class="swatch study"></span>勉強</span>')
    html.append("</div>")
    st.html("".join(html))


def render_dependency_table(enabled: set[str]) -> None:
    records = []
    for key in sorted(FORMULA_BLOCKS, key=lambda k: FORMULA_BLOCKS[k].priority):
        block = FORMULA_BLOCKS[key]
        records.append({
            "優先": block.priority,
            "項目": block.label,
            "状態": "入" if key in enabled else "切",
            "必要な項目": "、".join(FORMULA_BLOCKS[d].label for d in block.requires) or "-",
        })
    st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")


def fixed_grid_to_dataframe(fixed_grid: list[list[bool]], slot_minutes: int, days_to_show: int) -> pd.DataFrame:
    rows = []
    for day_index, row in enumerate(fixed_grid[:days_to_show]):
        record = {"曜日": WEEKDAYS[day_index]}
        for slot, is_fixed in enumerate(row):
            record[slot_to_time(slot, slot_minutes)] = is_fixed
        rows.append(record)
    return pd.DataFrame(rows)


def dataframe_to_fixed_grid(df: pd.DataFrame, slot_minutes: int, current_grid: list[list[bool]]) -> list[list[bool]]:
    time_columns = [slot_to_time(slot, slot_minutes) for slot in range(slots_per_day(slot_minutes))]
    updated = [row[:] for row in current_grid]
    for day_index, (_, row) in enumerate(df.iterrows()):
        updated[day_index] = [bool(row[col]) for col in time_columns]
    return updated


def apply_fixed_range(
    fixed_grid: list[list[bool]],
    slot_minutes: int,
    day_label: str,
    start_label: str,
    end_label: str,
    value: bool,
    days_to_show: int,
) -> list[list[bool]]:
    updated = [row[:] for row in fixed_grid]
    time_labels = [slot_to_time(slot, slot_minutes) for slot in range(slots_per_day(slot_minutes) + 1)]
    start_slot = time_labels.index(start_label)
    end_slot = time_labels.index(end_label)
    if end_slot <= start_slot:
        return updated

    day_indices = range(days_to_show) if day_label == "全曜日" else [WEEKDAYS.index(day_label)]
    for day_index in day_indices:
        for slot in range(start_slot, min(end_slot, len(updated[day_index]))):
            updated[day_index][slot] = value
    return updated


def render_fixed_time_editor(slot_minutes: int, days_to_show: int) -> tuple[list[list[bool]], dict[str, int]]:
    grid_key = f"fixed_grid_{slot_minutes}"
    if grid_key not in st.session_state:
        st.session_state[grid_key] = default_fixed_grid(slot_minutes)

    st.subheader("範囲指定でまとめて変更")
    time_labels = [slot_to_time(slot, slot_minutes) for slot in range(slots_per_day(slot_minutes) + 1)]
    day_options = ["全曜日", *WEEKDAYS[:days_to_show]]
    with st.form(f"fixed_range_form_{slot_minutes}"):
        col_day, col_start, col_end, col_action = st.columns(4)
        day_label = col_day.selectbox("曜日", day_options, key=f"range_day_{slot_minutes}")
        start_label = col_start.selectbox("開始", time_labels[:-1], key=f"range_start_{slot_minutes}")
        end_label = col_end.selectbox("終了", time_labels[1:], index=min(2, len(time_labels) - 2), key=f"range_end_{slot_minutes}")
        action = col_action.selectbox("操作", ["固定にする", "固定を外す"], key=f"range_action_{slot_minutes}")
        range_submitted = st.form_submit_button("範囲を反映")

    if range_submitted:
        st.session_state[grid_key] = apply_fixed_range(
            st.session_state[grid_key],
            slot_minutes,
            day_label,
            start_label,
            end_label,
            action == "固定にする",
            days_to_show,
        )
        st.rerun()

    st.caption("固定予定にしたいマスをチェックし、最後に「固定時間を反映」を押してください。")
    with st.form(f"fixed_time_form_{slot_minutes}"):
        edited = st.data_editor(
            fixed_grid_to_dataframe(st.session_state[grid_key], slot_minutes, days_to_show),
            hide_index=True,
            disabled=["曜日"],
            width="stretch",
            key=f"fixed_editor_{slot_minutes}",
        )
        submitted = st.form_submit_button("固定時間を反映")

    if submitted:
        st.session_state[grid_key] = dataframe_to_fixed_grid(edited, slot_minutes, st.session_state[grid_key])
        st.rerun()

    if st.button("標準の固定予定に戻す", key=f"reset_fixed_{slot_minutes}"):
        st.session_state[grid_key] = default_fixed_grid(slot_minutes)
        st.rerun()

    fixed_grid = st.session_state[grid_key]

    blocks = [block for block in detect_fixed_blocks(fixed_grid, slot_minutes) if block["day"] < days_to_show]
    st.subheader("固定予定ブロックごとの回復量")
    if not blocks:
        st.caption("固定予定ブロックはありません。")

    recovery_state_key = f"block_recoveries_{slot_minutes}"
    if recovery_state_key not in st.session_state:
        st.session_state[recovery_state_key] = {}

    with st.form(f"recovery_form_{slot_minutes}"):
        draft_recoveries = {}
        for block in blocks:
            default = st.session_state[recovery_state_key].get(block["id"], 0)
            draft_recoveries[block["id"]] = st.number_input(
                f"{block['label']} の回復量",
                min_value=0,
                value=int(default),
                step=5,
                key=f"recovery_input_{block['id']}",
            )
        recovery_submitted = st.form_submit_button("回復量を反映")

    if recovery_submitted:
        st.session_state[recovery_state_key] = draft_recoveries
        st.rerun()

    recoveries = {
        block["id"]: st.session_state[recovery_state_key].get(block["id"], 0)
        for block in blocks
    }
    return fixed_grid, recoveries


def main() -> None:
    st.set_page_config(page_title="勉強計画モデル", layout="wide")
    components.html(
        """
        <script>
          const root = window.parent.document.documentElement;
          root.setAttribute("lang", "ja");
          root.setAttribute("translate", "no");
          root.classList.add("notranslate");
          if (!window.parent.document.querySelector('meta[name="google"][content="notranslate"]')) {
            const meta = window.parent.document.createElement("meta");
            meta.name = "google";
            meta.content = "notranslate";
            window.parent.document.head.appendChild(meta);
          }
        </script>
        """,
        height=0,
    )
    st.title("勉強計画モデル")
    st.write("選んだ勉強単位・7日間を基本に、優先順位の高い要素から順に数式を表示します。")

    with st.sidebar:
        st.header("入れる要素")
        st.caption("1. 勉強・休憩・自由時間は常に入ります。")
        if st.session_state.get("toggle_schema_version") != 2:
            for key in STEP_KEYS:
                st.session_state[f"toggle_{key}"] = False
            st.session_state["toggle_schema_version"] = 2

        raw_enabled = {}
        raw_enabled["required_study"] = st.toggle("2. 勉強時間の下限・上限", key="toggle_required_study")
        if not raw_enabled["required_study"]:
            reset_steps_after("required_study")

        if raw_enabled["required_study"]:
            raw_enabled["motivation"] = st.toggle("3. モチベーション M", key="toggle_motivation")
            if not raw_enabled["motivation"]:
                reset_steps_after("motivation")
        if raw_enabled.get("motivation", False):
            raw_enabled["week"] = st.toggle("4. 7日間化 D", key="toggle_week")
            if not raw_enabled["week"]:
                reset_steps_after("week")
        if raw_enabled.get("week", False):
            raw_enabled["subjects"] = st.toggle("5. 科目・科目別最低時間", key="toggle_subjects")
            if not raw_enabled["subjects"]:
                reset_steps_after("subjects")

        enabled = resolve_enabled(raw_enabled)

        st.header("パラメータ")
        unit_label = st.selectbox("勉強単位", list(UNIT_OPTIONS.keys()), index=1)
        slot_minutes = UNIT_OPTIONS[unit_label]
        default_h_min = max(1, 12 * 60 // slot_minutes)
        default_h_max = max(default_h_min, 20 * 60 // slot_minutes)
        h_min = 0
        h_max = slots_per_day(slot_minutes) * DAYS_PER_WEEK
        if "required_study" in enabled:
            h_min = st.number_input(
                f"最低勉強コマ数（{unit_label}）",
                min_value=0,
                value=default_h_min,
                step=1,
                key=f"h_min_input_{slot_minutes}",
            )
            h_max = st.number_input(
                f"最大勉強コマ数（{unit_label}）",
                min_value=h_min,
                value=default_h_max,
                step=1,
                key=f"h_max_input_{slot_minutes}",
            )
        else:
            st.caption("Step 2 を入れると、勉強時間の下限・上限を指定できます。")
        params = {
            "h_min": h_min,
            "h_max": h_max,
            "slot_minutes": slot_minutes,
            "a": 20,
            "b": 30,
            "time_limit": 10,
            "subject_hours": {subject: 4 for subject in SUBJECTS},
        }

        if "motivation" in enabled:
            params["a"] = st.number_input("勉強による低下 a", min_value=0, value=20, step=5)
            params["b"] = st.number_input("休憩による回復 b", min_value=0, value=30, step=5)
            st.caption("固定予定後の回復量 G_dt は「固定時間」タブで、連続ブロックごとに設定します。")

        if "subjects" in enabled:
            st.caption(f"科目別最低時間（{unit_label}コマ）")
            default_subject_h = max(1, 2 * 60 // slot_minutes)
            for subject in SUBJECTS:
                params["subject_hours"][subject] = st.number_input(f"{subject}の最小勉強コマ数", min_value=0, value=default_subject_h, step=1)

        params["time_limit"] = st.number_input("PuLP 制限時間（秒）", min_value=3, value=10, step=1)

    tab_plan, tab_fixed = st.tabs(["勉強計画", "固定時間"])
    with tab_fixed:
        fixed_days_to_show = DAYS_PER_WEEK if "week" in enabled else 1
        fixed_grid, block_recoveries = render_fixed_time_editor(slot_minutes, fixed_days_to_show)

    params["fixed_grid"] = fixed_grid
    params["block_recoveries"] = block_recoveries

    schedule, solve_message = solve_schedule(enabled, params)
    study_slots = count_study(schedule)

    with tab_plan:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("時間単位", unit_label)
        col2.metric("決める範囲", "7日" if "week" in enabled else "1日")
        col3.metric("勉強時間", f"{study_slots * slot_minutes / 60:.1f} 時間")
        col4.metric("科目数", len(SUBJECTS) if "subjects" in enabled else "-")

        st.subheader("時間割")
        st.caption(solve_message)
        render_schedule(schedule, "subjects" in enabled, slot_minutes)
        st.caption("固定時間タブで指定した固定予定を使います。自由時間は勉強か休憩に割り当てます。")

        if "subjects" in enabled:
            st.subheader("科目別勉強時間")
            counts = count_subjects(schedule)
            st.dataframe(
                pd.DataFrame([
                    {"科目": subject, "コマ数": count, "時間": f"{count * slot_minutes / 60:.1f} 時間"}
                    for subject, count in counts.items()
                ]),
                hide_index=True,
                width="stretch",
            )

        st.subheader("現在の数式")
        render_current_model_formulas(enabled)

        with st.expander("現在の主要パラメータ"):
            parameter_rows = []
            if "required_study" in enabled:
                parameter_rows.append({"項目": "最低勉強コマ数", "記号": "H^{min}", "値": f"{h_min} コマ"})
                parameter_rows.append({"項目": "最大勉強コマ数", "記号": "H^{max}", "値": f"{h_max} コマ"})
            parameter_rows.extend([
                {"項目": "勉強による低下", "記号": "a", "値": params["a"]},
                {"項目": "休憩による回復", "記号": "b", "値": params["b"]},
            ])
            if "subjects" in enabled:
                for subject in SUBJECTS:
                    parameter_rows.append(
                        {
                            "項目": f"{subject}の最小勉強コマ数",
                            "記号": "H_j",
                            "値": f"{params['subject_hours'][subject]} コマ",
                        }
                    )
            st.dataframe(pd.DataFrame(parameter_rows), hide_index=True, width="stretch")

            enabled_rows = [
                {"優先": FORMULA_BLOCKS[key].priority, "入っている要素": FORMULA_BLOCKS[key].label}
                for key in sorted(enabled, key=lambda k: FORMULA_BLOCKS[k].priority)
            ]
            st.dataframe(pd.DataFrame(enabled_rows), hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
