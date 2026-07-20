from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pulp


UNIT_OPTIONS = {
    "1時間": 60,
    "30分": 30,
    "20分": 20,
    "15分": 15,
    "10分": 10,
    "5分": 5,
}
SUBJECTS = ["国語", "英語", "数学", "社会", "理科"]
FormulaLine = tuple[str, str]


@dataclass(frozen=True)
class StudyParams:
    unit_minutes: int = 30
    days: int = 1
    min_study_slots: int = 4
    max_study_slots: int = 8
    study_motivation_loss: int = 20
    rest_motivation_gain: int = 30
    start_hour: int = 8
    end_hour: int = 22


def slots_per_day(params: StudyParams) -> int:
    return (params.end_hour - params.start_hour) * 60 // params.unit_minutes


def slot_to_time(slot: int, params: StudyParams) -> str:
    minutes = params.start_hour * 60 + slot * params.unit_minutes
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_to_slot(hour: int, minute: int, params: StudyParams) -> int:
    return ((hour - params.start_hour) * 60 + minute) // params.unit_minutes


def default_fixed_schedule(params: StudyParams) -> list[set[int]]:
    fixed_by_day = []
    for day in range(params.days):
        fixed = set()
        if day % 7 < 5:
            fixed.update(
                range(
                    time_to_slot(8, 30, params),
                    time_to_slot(15, 30, params),
                )
            )
        fixed.update(range(time_to_slot(18, 0, params), time_to_slot(19, 0, params)))
        fixed_by_day.append(fixed)
    return fixed_by_day


def default_recovery(params: StudyParams, fixed_by_day: list[set[int]]) -> dict[tuple[int, int], int]:
    recovery = {}
    for day, fixed in enumerate(fixed_by_day):
        if day % 7 < 5:
            lunch_end = time_to_slot(12, 30, params) - 1
            if lunch_end in fixed:
                recovery[(day, lunch_end)] = 15
        dinner_end = time_to_slot(19, 0, params) - 1
        if dinner_end in fixed:
            recovery[(day, dinner_end)] = 25
    return recovery


def formula_explanations(include_week: bool = False, include_subjects: bool = False) -> list[tuple[str, str, str]]:
    grouped = current_model_formulas(include_week=include_week, include_subjects=include_subjects)
    return [(title, formula, explanation) for title, lines in grouped for formula, explanation in lines]


def current_model_formulas(
    include_week: bool = False,
    include_subjects: bool = False,
) -> list[tuple[str, list[FormulaLine]]]:
    idx = r"d\in D,\ t\in T" if include_week else r"t\in T"
    z = "Z_{dt}" if include_week else "Z_t"
    r_var = "R_{dt}" if include_week else "R_t"
    a = "A_{dt}" if include_week else "A_t"
    m = "M_{dt}" if include_week else "M_t"
    w = "W_{dt}" if include_week else "W_t"
    g = "G_{dt}" if include_week else "G_t"
    next_m = "M_{d,t+1}" if include_week else "M_{t+1}"
    sum_z = r"\sum_{d\in D}\sum_{t\in T}Z_{dt}" if include_week else r"\sum_{t\in T}Z_t"
    sum_w = r"\sum_{d\in D}\sum_{t\in T}W_{dt}" if include_week else r"\sum_{t\in T}W_t"

    variables: list[FormulaLine] = [
        (
            r"D=\{1,\ldots,7\},\quad T=\{1,\ldots,|T|\}"
            if include_week
            else r"T=\{1,\ldots,|T|\}",
            "計画で使う日と時刻の範囲。",
        ),
        (rf"{z},{r_var}\in\{{0,1\}}\quad({idx})", "勉強するか、休憩するかを表す。"),
        (rf"{m}\in[0,100]\quad({idx})", "その時刻のモチベーション。"),
        (rf"{w}\ge0\quad({idx})", "モチベーションを考慮した勉強の評価値。"),
    ]
    if include_subjects:
        variables.extend(
            [
                (r"K=\{\text{国語},\text{英語},\text{数学},\text{社会},\text{理科}\}", "扱う科目の集合。"),
                (r"X_{dtj}\in\{0,1\}\quad(d\in D,\ t\in T,\ j\in K)", "その時間に科目jを勉強するなら1。"),
            ]
        )

    constraints: list[tuple[str, list[FormulaLine]]] = [
        (
            "制約1：自由時間の割当て",
            [(rf"{z}+{r_var}={a}\quad({idx})", "自由時間なら勉強か休憩、固定予定ならどちらもできない。")],
        ),
        (
            "制約2：勉強時間の下限・上限",
            [(rf"H^{{\min}}\le {sum_z}\le H^{{\max}}", "勉強時間が少なすぎず、多すぎないようにする。")],
        ),
        (
            "制約3：モチベーション",
            [
                (r"M_{d,1}=100\quad(d\in D)" if include_week else r"M_1=100", "最初のモチベーションを100から始める。"),
                (rf"{next_m}=\min\{{100,\ {m}-a{z}+b{r_var}+{g}\}}", "勉強で下がり、休憩や固定予定後の回復で上がる。"),
                (rf"{w}={m}{z}\quad({idx})", "勉強しない時間の評価は0、勉強する時間はモチベーション分だけ評価する。"),
            ],
        ),
    ]
    if include_week:
        constraints.append(("制約4：7日間化", [(r"d\in D=\{1,\ldots,7\}", "1日モデルを7日間に広げる。")]))
    if include_subjects:
        constraints.append(
            (
                "発展：科目・科目別最低時間",
                [
                    (r"\sum_{j\in K}X_{dtj}=Z_{dt}\quad(d\in D,\ t\in T)", "勉強する時間には、必ず1つの科目を選ぶ。"),
                    (r"\sum_{d\in D}\sum_{t\in T}X_{dtj}\ge H_j\quad(j\in K)", "各科目で最低限必要な勉強コマ数を満たす。"),
                ],
            )
        )

    return [
        ("変数", variables),
        ("目的関数", [(rf"\max\ {sum_w}", "モチベーションが高い時間の勉強を高く評価する。")]),
        *constraints,
    ]


def solve_basic_model(
    params: StudyParams,
    fixed_by_day: list[set[int]] | None = None,
    recovery: dict[tuple[int, int], int] | None = None,
) -> tuple[pd.DataFrame, str]:
    slots = slots_per_day(params)
    fixed_by_day = fixed_by_day or default_fixed_schedule(params)
    recovery = recovery or default_recovery(params, fixed_by_day)

    model = pulp.LpProblem("basic_study_plan", pulp.LpMaximize)

    z = pulp.LpVariable.dicts("Z", (range(params.days), range(slots)), 0, 1, cat="Binary")
    r = pulp.LpVariable.dicts("R", (range(params.days), range(slots)), 0, 1, cat="Binary")
    m = pulp.LpVariable.dicts("M", (range(params.days), range(slots)), 0, 100)
    w = pulp.LpVariable.dicts("W", (range(params.days), range(slots)), 0, 100)

    for day in range(params.days):
        for slot in range(slots):
            available = 0 if slot in fixed_by_day[day] else 1
            model += z[day][slot] + r[day][slot] == available

            model += w[day][slot] <= m[day][slot]
            model += w[day][slot] <= 100 * z[day][slot]
            model += w[day][slot] >= m[day][slot] - 100 * (1 - z[day][slot])

        model += m[day][0] == 100
        for slot in range(slots - 1):
            model += (
                m[day][slot + 1]
                <= m[day][slot]
                - params.study_motivation_loss * z[day][slot]
                + params.rest_motivation_gain * r[day][slot]
                + recovery.get((day, slot), 0)
            )

    total_study = pulp.lpSum(z[day][slot] for day in range(params.days) for slot in range(slots))
    model += total_study >= params.min_study_slots
    model += total_study <= params.max_study_slots
    model += pulp.lpSum(w[day][slot] for day in range(params.days) for slot in range(slots))

    status = model.solve(pulp.PULP_CBC_CMD(msg=False))

    rows = []
    for day in range(params.days):
        for slot in range(slots):
            if slot in fixed_by_day[day]:
                action = "固定予定"
            elif pulp.value(z[day][slot]) > 0.5:
                action = "勉強"
            else:
                action = "休憩"
            rows.append(
                {
                    "日": day + 1,
                    "時刻": slot_to_time(slot, params),
                    "行動": action,
                    "モチベーション": round(pulp.value(m[day][slot]), 1),
                }
            )

    return pd.DataFrame(rows), pulp.LpStatus[status]


def main() -> None:
    params = StudyParams(
        unit_minutes=30,
        days=1,
        min_study_slots=4,
        max_study_slots=8,
        study_motivation_loss=20,
        rest_motivation_gain=30,
    )
    result, status = solve_basic_model(params)
    print("Status:", status)
    print(result)


if __name__ == "__main__":
    main()
